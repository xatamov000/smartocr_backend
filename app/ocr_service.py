from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

import pytesseract
from pytesseract import Output
from PIL import Image, ImageOps, ImageFilter


# ============================================================
# OCR language config
# ============================================================

# 🔥 AUTO = barcha kerakli tillar
AUTO_LANGS = "eng+rus+uzb+uzb_cyrl"


# ============================================================
# Tesseract setup
# ============================================================

def ensure_tesseract() -> str:
    """
    Windowsda ko‘p muammo bo‘ladi: uvicorn ishlayotgan muhit PATH’da
    tesseract bo‘lmasligi mumkin. Shu funksiya tesseract’ni topib
    pytesseract’ga set qiladi.
    """
    current = getattr(pytesseract.pytesseract, "tesseract_cmd", "")
    if current and Path(current).exists():
        return current

    found = shutil.which("tesseract")
    if found:
        pytesseract.pytesseract.tesseract_cmd = found
        return found

    candidates = [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ]
    for c in candidates:
        if Path(c).exists():
            pytesseract.pytesseract.tesseract_cmd = c
            return c

    raise RuntimeError(
        "Tesseract topilmadi. Tesseract o‘rnatilganini va PATH to‘g‘riligini tekshir."
    )


# ============================================================
# Tesseract config
# ============================================================

def _tess_config(psm: int = 6) -> str:
    """
    psm=6: hujjat uchun eng mos (uniform block of text)
    dpi=300: aniqlikni oshiradi
    """
    return f"--oem 3 --psm {psm} --dpi 300"


# ============================================================
# Image helpers
# ============================================================

def _maybe_autorotate(img: Image.Image) -> Image.Image:
    """
    Telefon rasmlarida 90/180/270 muammo bo‘ladi.
    OSD ishlasa rotate qiladi, ishlamasa tegmaydi.
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
    PIL-only preprocessing (opencv YO‘Q):
    - EXIF transpose
    - grayscale
    - autocontrast
    - yengil denoise
    - threshold
    - kichik rasm bo‘lsa upscale
    """
    # EXIF orientation
    img = ImageOps.exif_transpose(img)

    # RGB/L ga o‘tkazish
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    if img.mode != "L":
        img = img.convert("L")

    # kichik rasm bo‘lsa upscale
    w, h = img.size
    if max(w, h) < 1400:
        img = img.resize((w * 2, h * 2), Image.Resampling.LANCZOS)

    # kontrast
    img = ImageOps.autocontrast(img)

    # yengil shovqin kamaytirish
    img = img.filter(ImageFilter.MedianFilter(size=3))

    # oddiy threshold
    img = img.point(lambda p: 255 if p > 160 else 0)

    return img


# ============================================================
# Text normalize
# ============================================================

def _normalize_text(text: str) -> str:
    """
    OCR chiqishini ozgina tozalash:
    - CRLF -> LF
    - ortiqcha bo‘shliqlar
    - juda ko‘p bo‘sh qatorlarni kamaytirish
    """
    t = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


# ============================================================
# MAIN OCR FUNCTION
# ============================================================

def run_ocr(
    image_path: Path,
    lang: str = "eng",
    *,
    psm: int = 6,
    auto_rotate: bool = True,
    debug_save: bool = False,
) -> str:
    """
    Berilgan rasm faylidan matn ajratadi.

    🔥 Agar lang = "auto" bo‘lsa:
        eng + rus + uzb + uzb_cyrl
    """
    ensure_tesseract()

    # 🔥 AUTO LANGUAGE HANDLING
    if not lang or lang.lower() == "auto":
        lang = AUTO_LANGS

    img = Image.open(image_path)
    img = _preprocess_for_ocr(img)

    if auto_rotate:
        img = _maybe_autorotate(img)

    if debug_save:
        debug_dir = Path(os.getenv("OCR_DEBUG_DIR", "")) or (
            image_path.parent / "debug"
        )
        debug_dir.mkdir(parents=True, exist_ok=True)
        try:
            img.save(debug_dir / f"pre_{image_path.stem}.png")
        except Exception:
            pass

    text = pytesseract.image_to_string(
        img,
        lang=lang,
        config=_tess_config(psm),
    )

    return _normalize_text(text)
