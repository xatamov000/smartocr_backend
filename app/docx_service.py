from __future__ import annotations

import os
from io import BytesIO
from pathlib import Path
from typing import Iterable, List, Dict, Tuple, Optional

import pytesseract
from pytesseract import Output
from PIL import Image, ImageOps, ImageFilter

from docx import Document
from docx.shared import Pt, Inches
from docx.oxml.ns import qn

# ============================================================
# GLOBAL DOCX FONT (CYRILLIC SAFE)
# ============================================================

FONT_NAME = "Roboto"

# ============================================================
# Tesseract setup (safe)
# ============================================================

try:
    from .ocr_service import ensure_tesseract
except Exception:
    ensure_tesseract = None

# ============================================================
# OCR helpers
# ============================================================

def _tess_config(psm: int = 6) -> str:
    return f"--oem 3 --psm {psm} --dpi 300"


def _maybe_autorotate(img: Image.Image) -> Image.Image:
    try:
        osd = pytesseract.image_to_osd(img, output_type=Output.DICT)
        rotate = int(osd.get("rotate", 0) or 0)
        if rotate in (90, 180, 270):
            return img.rotate(360 - rotate, expand=True)
    except Exception:
        pass
    return img


def _preprocess_for_ocr(img: Image.Image) -> Image.Image:
    img = ImageOps.exif_transpose(img)

    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    if img.mode != "L":
        img = img.convert("L")

    w, h = img.size
    if max(w, h) < 1400:
        img = img.resize((w * 2, h * 2), Image.LANCZOS)

    img = ImageOps.autocontrast(img)
    img = img.filter(ImageFilter.MedianFilter(size=3))
    img = img.point(lambda p: 255 if p > 160 else 0)

    return img


def _safe_open_image(path: Path) -> Image.Image:
    img = Image.open(path)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    return img

# ============================================================
# Utils
# ============================================================

def _px_to_pt(px: float) -> float:
    return max(9.0, min(28.0, px * 0.75))


def _is_numbered(text: str) -> bool:
    s = text.strip()
    return bool(s and s[0].isdigit() and len(s) > 1)


def _is_bullet(text: str) -> bool:
    return text.strip().startswith(("-", "•", "*", "·"))


def _apply_font(run):
    run.font.name = FONT_NAME

    rPr = run._element.get_or_add_rPr()
    rFonts = rPr.get_or_add_rFonts()

    rFonts.set(qn("w:ascii"), FONT_NAME)
    rFonts.set(qn("w:hAnsi"), FONT_NAME)
    rFonts.set(qn("w:eastAsia"), FONT_NAME)
    rFonts.set(qn("w:cs"), FONT_NAME)


def _join_words(words: List[Dict], median_h: float) -> str:
    words = sorted(words, key=lambda w: int(w["left"]))
    out = []
    prev_right = None

    gap_2 = max(14.0, median_h * 1.4)

    for w in words:
        txt = (w.get("text") or "").strip()
        if not txt:
            continue

        left = int(w["left"])
        right = left + int(w["width"])

        if prev_right is None:
            out.append(txt)
        else:
            out.append(("  " if left - prev_right >= gap_2 else " ") + txt)

        prev_right = right

    return "".join(out)

# ============================================================
# Extract lines
# ============================================================

def _extract_lines(img: Image.Image, lang: str) -> List[Dict]:
    if callable(ensure_tesseract):
        ensure_tesseract()

    img = _maybe_autorotate(_preprocess_for_ocr(img))

    data = pytesseract.image_to_data(
        img,
        lang=lang,
        output_type=Output.DICT,
        config=_tess_config(),
    )

    rows = []
    for i, txt in enumerate(data["text"]):
        txt = (txt or "").strip()
        try:
            conf = int(float(data["conf"][i]))
        except Exception:
            conf = -1

        if not txt or conf < 0:
            continue

        rows.append({
            "block": data["block_num"][i],
            "par": data["par_num"][i],
            "line": data["line_num"][i],
            "text": txt,
            "left": data["left"][i],
            "top": data["top"][i],
            "width": data["width"][i],
            "height": data["height"][i],
        })

    lines = {}
    for r in rows:
        key = (r["block"], r["par"], r["line"])
        lines.setdefault(key, {"words": [], "left": r["left"], "top": r["top"], "height": r["height"]})
        lines[key]["words"].append(r)
        lines[key]["left"] = min(lines[key]["left"], r["left"])
        lines[key]["top"] = min(lines[key]["top"], r["top"])
        lines[key]["height"] = max(lines[key]["height"], r["height"])

    heights = [v["height"] for v in lines.values()]
    median_h = sorted(heights)[len(heights)//2] if heights else 16

    result = []
    for v in lines.values():
        text = _join_words(v["words"], median_h)
        if text:
            result.append({**v, "text": text})

    return sorted(result, key=lambda x: (x["top"], x["left"]))

# ============================================================
# DOCX builders
# ============================================================

def _add_paragraph(doc, line, min_left, median_h, prev_top, prev_h):
    text = line["text"]

    # indent
    indent_px = max(0, int(line["left"]) - int(min_left))
    left_indent = min(2.0, indent_px / 260.0)  # 260px ~ 1 inch

    h_pt = _px_to_pt(float(line["height"]))
    is_heading = float(line["height"]) >= (median_h * 1.35) and len(text) <= 80

    # ✅ HECH QANDAY style= YO‘Q (eng stabil)
    p = doc.add_paragraph("")

    # vertikal gap -> space_before
    if prev_top is not None and prev_h is not None:
        gap = int(line["top"]) - (int(prev_top) + int(prev_h))
        if gap > median_h * 1.2:
            p.paragraph_format.space_before = Pt(min(18, max(6, _px_to_pt(gap) * 0.6)))

    if left_indent > 0:
        p.paragraph_format.left_indent = Inches(left_indent)

    # list belgilarini matnga qo‘shamiz
    final_text = text
    if _is_bullet(text):
        final_text = "• " + text.lstrip("-•*· ").strip()

    run = p.add_run(final_text)
    _apply_font(run)

    if is_heading:
        run.bold = True
        run.font.size = Pt(min(26, max(14, h_pt + 2)))
    else:
        run.font.size = Pt(min(20, max(10, h_pt)))

    return int(line["top"]), int(line["height"])





def build_docx_bytes_from_image(path: Path, lang: str = "eng") -> bytes:
    img = _safe_open_image(path)
    lines = _extract_lines(img, lang)

    doc = Document()
    if not lines:
        doc.add_paragraph("")
    else:
        min_left = min(l["left"] for l in lines)
        median_h = sorted(l["height"] for l in lines)[len(lines)//2]

        prev_top = prev_h = None
        for l in lines:
            prev_top, prev_h = _add_paragraph(doc, l, min_left, median_h, prev_top, prev_h)

    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()


def build_docx_bytes_from_images(paths: Iterable[Path], lang: str = "eng") -> bytes:
    doc = Document()
    first = True

    for p in paths:
        if not first:
            doc.add_page_break()
        first = False

        img = _safe_open_image(p)
        lines = _extract_lines(img, lang)

        if not lines:
            doc.add_paragraph("")
            continue

        min_left = min(l["left"] for l in lines)
        median_h = sorted(l["height"] for l in lines)[len(lines)//2]

        prev_top = prev_h = None
        for l in lines:
            prev_top, prev_h = _add_paragraph(doc, l, min_left, median_h, prev_top, prev_h)

    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()
