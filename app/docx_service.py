# app/docx_service.py
from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Iterable, List, Dict, Tuple, Optional

import pytesseract
from pytesseract import Output
from PIL import Image, ImageOps, ImageFilter

from docx import Document
from docx.shared import Pt, Inches

# ✅ Tesseract path muammosini oldini olish uchun:
try:
    from .ocr_service import ensure_tesseract
except Exception:
    ensure_tesseract = None


# -----------------------------
# OCR config / preprocessing
# -----------------------------
def _tess_config(psm: int = 6) -> str:
    # psm=6: hujjatdagi text bloklari uchun eng ko‘p mos
    return f"--oem 3 --psm {psm} --dpi 300"


def _maybe_autorotate(img: Image.Image) -> Image.Image:
    """
    OSD ishlasa rotate qiladi (90/180/270).
    Ishlamasa — jim o‘tib ketadi.
    """
    try:
        osd = pytesseract.image_to_osd(img, output_type=Output.DICT)
        rotate = int(osd.get("rotate", 0) or 0)
        if rotate in (90, 180, 270):
            return img.rotate(360 - rotate, expand=True)
    except Exception:
        pass
    return img


def _preprocess_for_ocr(img: Image.Image) -> Image.Image:
    """
    PIL-only preprocessing:
    - EXIF orientation fix
    - grayscale
    - autocontrast
    - yengil denoise
    - simple threshold
    - kichik rasm bo‘lsa upscale
    """
    img = ImageOps.exif_transpose(img)

    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    if img.mode != "L":
        img = img.convert("L")

    w, h = img.size
    if max(w, h) < 1400:
        img = img.resize((w * 2, h * 2), Image.Resampling.LANCZOS)

    img = ImageOps.autocontrast(img)
    img = img.filter(ImageFilter.MedianFilter(size=3))

    # threshold (agressiv emas, lekin foydali)
    img = img.point(lambda p: 255 if p > 160 else 0)

    return img


def _safe_open_image(image_path: Path) -> Image.Image:
    img = Image.open(image_path)
    # RGBA/P -> RGB/L
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    return img


# -----------------------------
# Utils / heuristics
# -----------------------------
def _px_to_pt(px: float) -> float:
    # DPI aniq emas -> heuristika
    return max(9.0, min(28.0, px * 0.75))


def _is_numbered_line(line_text: str) -> bool:
    s = line_text.strip()
    if not s:
        return False
    if s[0].isdigit():
        if len(s) >= 2 and s[1] in [".", ")", " "]:
            return True
        if len(s) >= 3 and s[1].isdigit() and s[2] in [".", ")", " "]:
            return True
    return False


def _is_bulleted_line(line_text: str) -> bool:
    s = line_text.strip()
    return s.startswith(("-", "•", "·", "*"))


def _join_words_with_spacing(words: List[Dict], median_h: float) -> str:
    """
    Wordlarni left koordinata bo‘yicha join qilamiz.
    Gap katta bo‘lsa — 2 space (“tab”ga o‘xshash) qo‘yamiz.
    """
    if not words:
        return ""

    words = sorted(words, key=lambda w: int(w["left"]))

    out: List[str] = []
    prev_right: Optional[int] = None

    gap_1 = max(6.0, median_h * 0.60)   # 1 space
    gap_2 = max(14.0, median_h * 1.40)  # 2 space

    for w in words:
        txt = (w.get("text") or "").strip()
        if not txt:
            continue

        left = int(w["left"])
        right = left + int(w["width"])

        if prev_right is None:
            out.append(txt)
            prev_right = right
            continue

        gap = left - prev_right
        if gap >= gap_2:
            out.append("  " + txt)
        else:
            # aksariyat holatda 1 space kerak
            out.append(" " + txt)

        prev_right = right

    return "".join(out).strip()


# -----------------------------
# Core: extract lines
# -----------------------------
def _extract_lines(img_pil: Image.Image, lang: str) -> List[Dict]:
    """
    Tesseract’dan word-level data olib, line-larga guruhlaymiz.
    Qaytadi: har bir line uchun dict:
      text, left, top, height, words(list)
    """
    if callable(ensure_tesseract):
        ensure_tesseract()

    # ✅ preprocess + auto-rotate
    img = _preprocess_for_ocr(img_pil)
    img = _maybe_autorotate(img)

    data = pytesseract.image_to_data(
        img,
        lang=lang,
        output_type=Output.DICT,
        config=_tess_config(psm=6),
    )

    n = len(data["text"])
    rows: List[Dict] = []

    for i in range(n):
        txt = (data["text"][i] or "").strip()

        conf_raw = data.get("conf", ["-1"])[i]
        try:
            conf = int(float(conf_raw))
        except Exception:
            conf = -1

        if not txt or conf < 0:
            continue

        rows.append(
            {
                "block": int(data["block_num"][i]),
                "par": int(data["par_num"][i]),
                "line": int(data["line_num"][i]),
                "word": int(data["word_num"][i]),
                "text": txt,
                "left": int(data["left"][i]),
                "top": int(data["top"][i]),
                "width": int(data["width"][i]),
                "height": int(data["height"][i]),
                "conf": conf,
            }
        )

    rows.sort(key=lambda r: (r["block"], r["par"], r["line"], r["word"], r["left"]))

    # group by (block, par, line)
    lines_map: Dict[Tuple[int, int, int], Dict] = {}
    for r in rows:
        key = (r["block"], r["par"], r["line"])
        if key not in lines_map:
            lines_map[key] = {
                "words": [],
                "left": r["left"],
                "top": r["top"],
                "height": r["height"],
            }
        lines_map[key]["words"].append(r)
        lines_map[key]["left"] = min(lines_map[key]["left"], r["left"])
        lines_map[key]["top"] = min(lines_map[key]["top"], r["top"])
        lines_map[key]["height"] = max(lines_map[key]["height"], r["height"])

    heights = sorted([v["height"] for v in lines_map.values()])
    median_h = heights[len(heights) // 2] if heights else 16.0

    out: List[Dict] = []
    for _, line in lines_map.items():
        words = line["words"]
        text = _join_words_with_spacing(words, median_h)
        if not text:
            continue

        out.append(
            {
                "text": text,
                "left": int(line["left"]),
                "top": int(line["top"]),
                "height": int(line["height"]),
                "words": words,
            }
        )

    out.sort(key=lambda x: (x["top"], x["left"]))
    return out


def _apply_paragraph_style(
    doc: Document,
    line: Dict,
    min_left: int,
    median_h: float,
    prev_top: Optional[int],
    prev_h: Optional[int],
) -> Tuple[int, int]:
    text = line["text"]

    indent_px = max(0, int(line["left"]) - min_left)
    left_indent_in = min(2.0, indent_px / 260.0)  # 260px ~ 1 inch

    h_pt = _px_to_pt(float(line["height"]))
    is_heading = (line["height"] >= (median_h * 1.35)) and (len(text) <= 80)

    if _is_numbered_line(text):
        p = doc.add_paragraph("", style="List Number")
    elif _is_bulleted_line(text):
        p = doc.add_paragraph("", style="List Bullet")
    elif is_heading:
        p = doc.add_paragraph("", style="Heading 2")
    else:
        p = doc.add_paragraph("")

    # vertikal gap -> paragraf spacing
    if prev_top is not None and prev_h is not None:
        gap = int(line["top"]) - (prev_top + prev_h)
        if gap > median_h * 1.2:
            p.paragraph_format.space_before = Pt(min(18, max(6, _px_to_pt(gap) * 0.6)))

    if left_indent_in > 0:
        p.paragraph_format.left_indent = Inches(left_indent_in)

    run = p.add_run(text)

    if is_heading:
        run.font.size = Pt(min(26, max(14, h_pt + 2)))
        run.bold = True
    else:
        run.font.size = Pt(min(20, max(10, h_pt)))

    return int(line["top"]), int(line["height"])


# -----------------------------
# Public: build DOCX
# -----------------------------
def build_docx_bytes_from_image(image_path: Path, lang: str = "eng") -> bytes:
    """
    1 ta rasm -> strukturali docx
    """
    img_pil = _safe_open_image(image_path)
    lines = _extract_lines(img_pil, lang=lang)

    doc = Document()
    if not lines:
        doc.add_paragraph("")
    else:
        min_left = min(l["left"] for l in lines)
        heights = sorted([l["height"] for l in lines])
        median_h = heights[len(heights) // 2] if heights else 16.0

        prev_top: Optional[int] = None
        prev_h: Optional[int] = None
        for line in lines:
            prev_top, prev_h = _apply_paragraph_style(doc, line, min_left, median_h, prev_top, prev_h)

    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()


def build_docx_bytes_from_images(image_paths: Iterable[Path], lang: str = "eng") -> bytes:
    """
    Ko‘p rasm -> bitta docx (orasida page break)
    """
    doc = Document()
    first = True

    for p in image_paths:
        img_pil = _safe_open_image(p)
        lines = _extract_lines(img_pil, lang=lang)

        if not first:
            doc.add_page_break()
        first = False

        if not lines:
            doc.add_paragraph("")
            continue

        min_left = min(l["left"] for l in lines)
        heights = sorted([l["height"] for l in lines])
        median_h = heights[len(heights) // 2] if heights else 16.0

        prev_top: Optional[int] = None
        prev_h: Optional[int] = None
        for line in lines:
            prev_top, prev_h = _apply_paragraph_style(doc, line, min_left, median_h, prev_top, prev_h)

    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()
