"""
OCR Engine — Production v3 (multilingual, homoglyph-aware)

Critical fixes vs v2:
- lang='latin' replaced with explicit 'en' alias (paddleocr 2.7 same dict)
- lang='ru' replaced with 'cyrillic' (correct rec dictionary for Russian +
  Uzbek-Cyrillic + Bulgarian + Ukrainian)
- Token-level homoglyph detection (Pyrkoscxaa, aIropuTMbI, cucTeMbI, ...)
- _should_try_cyrillic now triggers on garble even at high confidence
- Winner selection uses garble flag, not just average confidence
- det_limit_side_len reduced 4096 → 1920 (matches modern phone native res,
  ~2x faster, no quality loss)
- det_db_box_thresh lowered 0.6 → 0.3 (don't drop faint body text)
- drop_score lowered to 0.3 (let post-filter handle low-confidence)
"""

import logging
import os
import re
import threading

import cv2
import numpy as np

from ..utils.preprocess_image import preprocess_image as _preprocess_for_paddle

logger = logging.getLogger(__name__)

os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")


# ─────────────────────────────────────────────
# Tunables
# ─────────────────────────────────────────────

# Modern phone screenshots are 1080–1440 px wide; 1920 covers native res
# without forcing downsampling. Larger values (4096) waste compute with
# no quality gain on typical mobile inputs.
DET_LIMIT_SIDE_LEN = 1920

# PaddleOCR default 0.5 silently drops correct-but-unsure recognition
# results. Lower drop_score keeps more candidates; downstream noise filter
# handles the actual garbage.
DROP_SCORE = 0.30

# Default 0.6 is too aggressive on photographed pages with faint text.
DET_DB_BOX_THRESH = 0.30

# Default 1.5 sometimes clips ascenders/descenders on tight line spacing.
DET_DB_UNCLIP_RATIO = 1.8


# ─────────────────────────────────────────────
# Global model cache
# ─────────────────────────────────────────────

_paddle_ocr_by_lang: dict = {}
_init_lock = threading.Lock()
_use_paddle = False

try:
    from paddleocr import PaddleOCR

    _use_paddle = True
    logger.info("PaddleOCR available")
except Exception as e:
    logger.warning(f"PaddleOCR not available: {e}")

import pytesseract
from pytesseract import Output


# ─────────────────────────────────────────────
# Model loader (paddleocr 2.7 compatible)
# ─────────────────────────────────────────────


def _normalize_lang(lang: str) -> str:
    """Map any incoming lang code to one of: 'en', 'cyrillic'."""
    lang = (lang or "").strip().lower()
    if lang in ("latin", "lat", "english", "eng", "en", "uz", "uzb", "uz-latn", "uzb_latn"):
        return "en"
    if lang in ("ru", "rus", "russian", "cyrillic", "cyr", "uz-cyrl", "uzb_cyrl"):
        return "cyrillic"
    if lang == "auto":
        # default first pass
        return "en"
    # Unknown → safest is 'en' (Latin handles English + Uzbek-Latin)
    return "en"


def _get_paddle(lang: str):
    """Return a cached PaddleOCR instance for the requested language."""
    norm = _normalize_lang(lang)

    if norm in _paddle_ocr_by_lang:
        return _paddle_ocr_by_lang[norm]

    with _init_lock:
        if norm in _paddle_ocr_by_lang:
            return _paddle_ocr_by_lang[norm]

        try:
            ocr = PaddleOCR(
                lang=norm,
                use_angle_cls=True,
                det_limit_side_len=DET_LIMIT_SIDE_LEN,
                det_limit_type="max",
                det_db_box_thresh=DET_DB_BOX_THRESH,
                det_db_unclip_ratio=DET_DB_UNCLIP_RATIO,
                drop_score=DROP_SCORE,
                rec_batch_num=8,
                use_space_char=True,
                show_log=False,
            )
            _paddle_ocr_by_lang[norm] = ocr
            logger.info(f"PaddleOCR loaded (lang={norm})")
        except Exception as e:
            logger.error(f"PaddleOCR init failed (lang={norm}): {e}")
            return None

    return _paddle_ocr_by_lang.get(norm)


# ─────────────────────────────────────────────
# Cyrillic homoglyph detection
# ─────────────────────────────────────────────

_CYRILLIC_RANGE = re.compile(r"[\u0400-\u04FF]")
_LATIN_RANGE = re.compile(r"[A-Za-z]")

# Bigrams the Latin recognizer produces when fed Cyrillic.
# These are the unmistakable signature of a wrong-model recognition.
_HOMOGLYPH_BIGRAMS = (
    "bI",     # ы
    "TM",     # тм (capital-mid sequence inside word)
    "IO",     # ю
    "cTe",    # сте
    "cKa",    # ска
    "cKo",    # ско
    "OBC",    # обс
    "aIr",    # алг
    "opu",    # ори
    "cucT",   # сист
    "eMa",    # ема
    "eHH",    # енн
    "aIIa",   # ала (double Latin I from Cyrillic Л)
    "TbCO",   # тьсо
    "Pyrk",   # Рутк (specific to "Рутковская")
    "ckaa",   # ская suffix collapse
)

# Lowercase letters surrounding a stray uppercase H/I/M/T/P/B/K/X
# is the signature of Latin recognizer interpreting Cyrillic
# Н/И/М/Т/Р/В/К/Х inside a Cyrillic word.
_MID_WORD_CYR_CAPITAL = re.compile(r"[a-z]{1,3}[HIMTPBKX][a-z]{1,4}")

_TOKEN_RE = re.compile(r"\S+")


def _token_is_homoglyph_collapse(tok: str) -> bool:
    """Detect a single token being a Latin misreading of Cyrillic text."""
    if len(tok) < 4:
        return False
    # If the token ALREADY contains real Cyrillic codepoints, it's not
    # a pure-Latin collapse case.
    if _CYRILLIC_RANGE.search(tok):
        return False
    # Bigram signatures
    for bg in _HOMOGLYPH_BIGRAMS:
        if bg in tok:
            return True
    # Mid-word capital pattern
    if _MID_WORD_CYR_CAPITAL.search(tok):
        return True
    # Heuristic: capitalised word with many Cyrillic-shaped Latin letters
    if len(tok) >= 6 and tok[0].isupper():
        weird = sum(1 for c in tok[1:] if c in "bIHMTPBK")
        if weird >= 3:
            return True
    return False


def _is_cyrillic_garbled(items: list) -> bool:
    """Page-level garble decision (used to choose model winner)."""
    if not items:
        return False

    full_text = " ".join(i["text"] for i in items)
    if not full_text.strip():
        return False

    cyrillic_chars = len(_CYRILLIC_RANGE.findall(full_text))
    latin_chars = len(_LATIN_RANGE.findall(full_text))
    total = cyrillic_chars + latin_chars
    if total < 20:  # too little text to decide
        return False

    cyrillic_ratio = cyrillic_chars / total

    homoglyph_tokens = 0
    total_tokens = 0
    for tok in _TOKEN_RE.findall(full_text):
        if len(tok) >= 3:
            total_tokens += 1
            if _token_is_homoglyph_collapse(tok):
                homoglyph_tokens += 1

    if total_tokens == 0:
        return False

    homoglyph_ratio = homoglyph_tokens / total_tokens

    # Strong signal: low Cyrillic, lots of homoglyph tokens
    if cyrillic_ratio < 0.05 and homoglyph_ratio > 0.10:
        return True
    # Absolute count threshold (catches mixed pages)
    if homoglyph_tokens >= 5:
        return True

    return False


# ─────────────────────────────────────────────
# Parse PaddleOCR result
# ─────────────────────────────────────────────


def _parse_paddle(results) -> list:
    items: list = []
    if not results:
        return items

    for page in results:
        if page is None:
            continue
        for line in page:
            try:
                if len(line) != 2:
                    continue
                box, text_data = line
                text = text_data[0]
                conf = float(text_data[1])
                if not text or not text.strip():
                    continue
                xs = [p[0] for p in box]
                ys = [p[1] for p in box]
                items.append(
                    {
                        "text": text.strip(),
                        "confidence": conf,
                        "bbox": [min(xs), min(ys), max(xs), max(ys)],
                    }
                )
            except Exception:
                continue

    items.sort(key=lambda x: (x["bbox"][1], x["bbox"][0]))
    return items


# ─────────────────────────────────────────────
# Quality metrics & decision
# ─────────────────────────────────────────────


def _metrics(items):
    if not items:
        return 0.0, 0, 0
    confs = [i["confidence"] for i in items]
    tlen = sum(len(i["text"]) for i in items)
    return sum(confs) / len(confs), tlen, len(items)


def _should_try_cyrillic(parsed_en, avg_conf, text_len, line_count) -> bool:
    """Decide whether the Cyrillic recognizer pass is worth running."""
    # Original quality-based triggers (kept)
    if avg_conf < 0.75 or text_len < 80 or line_count < 3:
        return True
    # NEW: token-level homoglyph collapse detected even at high conf
    if _is_cyrillic_garbled(parsed_en):
        return True
    return False


# ─────────────────────────────────────────────
# Main PaddleOCR path
# ─────────────────────────────────────────────


def _paddle_ocr_path(image_path: str, lang_hint: str = "auto") -> list:
    img = cv2.imread(image_path)
    if img is None:
        raise RuntimeError(f"Failed to load image: {image_path}")

    img = _preprocess_for_paddle(
        img, max_dim=DET_LIMIT_SIDE_LEN, apply_perspective=True
    )

    # ── Pass 1: Latin (en) ────────────────────────────────────────────────
    ocr_en = _get_paddle("en")
    if ocr_en is None:
        # PaddleOCR couldn't load any model; bail to Tesseract
        return _tesseract_ocr(img)

    en_results = ocr_en.ocr(img, cls=True)
    parsed_en = _parse_paddle(en_results)
    avg_en, len_en, lines_en = _metrics(parsed_en)
    en_garbled = _is_cyrillic_garbled(parsed_en)
    logger.info(
        f"[EN]  conf={avg_en:.2f} chars={len_en} lines={lines_en} garbled={en_garbled}"
    )

    # If user explicitly hints Cyrillic, skip the EN/CYR comparison logic
    # and prefer Cyrillic outright
    forced_cyr = _normalize_lang(lang_hint) == "cyrillic"

    if not forced_cyr and not _should_try_cyrillic(parsed_en, avg_en, len_en, lines_en):
        return parsed_en

    # ── Pass 2: Cyrillic ──────────────────────────────────────────────────
    ocr_cyr = _get_paddle("cyrillic")
    if ocr_cyr is None:
        # Cyrillic model unavailable; if EN is garbled, last resort = Tesseract
        if en_garbled:
            tess = _tesseract_ocr(img)
            if tess:
                return tess
        return parsed_en

    cyr_results = ocr_cyr.ocr(img, cls=True)
    parsed_cyr = _parse_paddle(cyr_results)
    avg_cyr, len_cyr, lines_cyr = _metrics(parsed_cyr)
    cyr_garbled = _is_cyrillic_garbled(parsed_cyr)
    logger.info(
        f"[CYR] conf={avg_cyr:.2f} chars={len_cyr} lines={lines_cyr} garbled={cyr_garbled}"
    )

    # ── Winner selection ──────────────────────────────────────────────────
    # If user forced Cyrillic, take it unless empty
    if forced_cyr and lines_cyr >= 1:
        return parsed_cyr

    # EN garbled, CYR clean → CYR wins
    if en_garbled and not cyr_garbled and lines_cyr >= 2:
        logger.info("Using Cyrillic (EN garbled, CYR clean)")
        return parsed_cyr

    # Both clean → score by conf × sqrt(line_count)
    if not en_garbled and not cyr_garbled:
        score_en = avg_en * (lines_en ** 0.5) if lines_en else 0.0
        score_cyr = avg_cyr * (lines_cyr ** 0.5) if lines_cyr else 0.0
        if score_cyr > score_en + 0.05:
            logger.info(f"Using CYR (score {score_cyr:.2f} > EN {score_en:.2f})")
            return parsed_cyr
        return parsed_en

    # Both garbled → Tesseract last resort
    if en_garbled and cyr_garbled:
        logger.info("Both passes garbled → Tesseract fallback")
        tess = _tesseract_ocr(img)
        if tess:
            return tess

    return parsed_en


# ─────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────


def ocr_full_image(image_path: str, lang: str = "auto") -> list:
    """Run OCR on the given image file. Returns a list of item dicts."""
    if _use_paddle:
        try:
            return _paddle_ocr_path(image_path, lang_hint=lang)
        except Exception:
            import traceback

            logger.error("PaddleOCR failed")
            traceback.print_exc()
            img = cv2.imread(image_path)
            if img is not None:
                return _tesseract_ocr(img)
            return []

    img = cv2.imread(image_path)
    return _tesseract_ocr(img) if img is not None else []


# ─────────────────────────────────────────────
# Tesseract fallback (Cyrillic-leaning)
# ─────────────────────────────────────────────


def _tesseract_ocr(image: np.ndarray) -> list:
    """Tesseract OCR used exclusively as a last-resort fallback."""
    if image is None:
        return []

    lang = "uzb+rus+uzb_cyrl+eng"
    config = "--oem 1 --psm 3"

    try:
        data = pytesseract.image_to_data(
            image, lang=lang, config=config, output_type=Output.DICT
        )
    except Exception as e:
        logger.error(f"Tesseract failed: {e}")
        return []

    lines: dict = {}
    for i, word in enumerate(data["text"]):
        word = word.strip()
        try:
            conf = int(float(data["conf"][i]))
        except (ValueError, TypeError):
            continue
        if not word or conf < 25:
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        if key not in lines:
            lines[key] = {
                "words": [],
                "confs": [],
                "left": data["left"][i],
                "top": data["top"][i],
                "right": data["left"][i] + data["width"][i],
                "bottom": data["top"][i] + data["height"][i],
            }
        lines[key]["words"].append(word)
        lines[key]["confs"].append(conf)

    items = []
    for key in sorted(lines):
        ln = lines[key]
        items.append(
            {
                "text": " ".join(ln["words"]),
                "confidence": sum(ln["confs"]) / len(ln["confs"]) / 100.0,
                "bbox": [ln["left"], ln["top"], ln["right"], ln["bottom"]],
            }
        )
    return items


def is_paddle_available() -> bool:
    return _use_paddle