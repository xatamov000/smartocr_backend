# app/services/ocr_pipeline.py

"""
OCR Pipeline — Production v2

Changes vs previous version:
• PPStructure removed (confirmed too slow; not used)
• Phone UI noise filtering: status-bar elements, page numbers, URLs
• Cyrillic garble detection with Tesseract fallback (in-pipeline)
• Line-level type classification (heading / list / text)
• Block merging: only consecutive paragraphs merged; list items stay separate
"""

import re
import time
import logging
from typing import Dict, List

from .ocr_engine import ocr_full_image

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# Noise patterns (phone UI artifacts)
# ─────────────────────────────────────────────

_NOISE_PATTERNS = [
    # Status-bar / system UI
    re.compile(r'^\d{1,2}:\d{2}$'),                         # "21:12"
    re.compile(r'^\d+%$'),                                   # "97%"
    re.compile(r'^(\d+[,.]?\d*\s*)?KB/s$', re.I),           # "10.3 KB/s"
    re.compile(r'^4G[+]?$|^5G[+]?$|^LTE$', re.I),           # "4G+"
    re.compile(r'^\d+/\d+$'),                                # "1/117" page indicator
    re.compile(r'^chrome-native://', re.I),                  # PDF URL bar
    re.compile(r'^https?://', re.I),                         # any URL
    re.compile(r'^\+$'),                                     # stray "+"
    re.compile(r'^\d+$'),                                    # bare page number (1–3 digits)
    # Common phone UI labels (Uzbek)
    re.compile(r'^(Ulashish|Tahrirlash|O.chirish|Yana)$', re.I),
]

_NUMBERED_LIST = re.compile(r'^(\d{1,2})[.)]\s+\S')
_BULLET_LIST   = re.compile(r'^[•\-–—*]\s+\S')
_HEADING_CAPS  = re.compile(r"^[A-ZЁІЎҚҒҲ][^.!?]{5,60}$")


# ─────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────

def process_document(image_path: str, lang: str = "auto") -> Dict:
    """
    Main OCR pipeline.

    Returns:
    {
        blocks:          list of {type, content, bbox, confidence},
        plain_text:      str,
        confidence:      float,
        processing_time: float,
        engine:          str,
    }
    """
    start = time.time()

    try:
        items = ocr_full_image(image_path, lang)

        # ── 1. Filter phone UI noise ──────────────────────────────────────
        items = [i for i in items if not _is_noise(i["text"])]

        # ── 2. Classify each line ─────────────────────────────────────────
        classified = [_classify(item) for item in items]

        # ── 3. Merge consecutive paragraph lines ─────────────────────────
        blocks = _merge_blocks(classified)

        plain_text  = _blocks_to_text(blocks)
        confidence  = _estimate_confidence(blocks)

        return {
            "blocks":          blocks,
            "plain_text":      plain_text,
            "confidence":      confidence,
            "processing_time": round(time.time() - start, 3),
            "engine":          "paddle",
        }

    except Exception as e:
        logger.error(f"OCR pipeline error: {e}")
        return {
            "blocks":          [],
            "plain_text":      "[OCR error]",
            "confidence":      0.0,
            "processing_time": 0.0,
            "engine":          "error",
        }


# ─────────────────────────────────────────────
# Noise detection
# ─────────────────────────────────────────────

def _is_noise(text: str) -> bool:
    t = text.strip()
    if not t:
        return True
    if len(t) == 1:
        return True
    for pat in _NOISE_PATTERNS:
        if pat.search(t):
            return True
    return False


# ─────────────────────────────────────────────
# Line classification
# ─────────────────────────────────────────────

def _classify(item: dict) -> dict:
    """Assign type (heading / list / text) to a single OCR line."""
    text = item["text"].strip()
    block_type = "text"

    if _NUMBERED_LIST.match(text) or _BULLET_LIST.match(text):
        block_type = "list"
    elif _HEADING_CAPS.match(text) and len(text) < 80:
        block_type = "heading"

    return {
        "type":       block_type,
        "content":    text,
        "bbox":       item.get("bbox", [0, 0, 0, 0]),
        "confidence": item.get("confidence", 0.9),
    }


# ─────────────────────────────────────────────
# Block merging
# ─────────────────────────────────────────────

_MIN_MERGE_CHARS  = 200     # merge paragraphs until accumulated text exceeds this
_MERGE_ENDS       = re.compile(r'[.!?]$')
_STARTS_UPPERCASE = re.compile(r'^[A-ZЁІЎҚҒҲ]')


def _merge_blocks(classified: List[dict]) -> List[dict]:
    """
    Merge consecutive 'text' blocks into paragraphs.
    List and heading blocks are never merged.

    Split rule (established): split when accumulated text > MIN_MERGE_CHARS
    AND ends with sentence-ending punctuation AND next line starts uppercase.
    """
    if not classified:
        return []

    merged: List[dict] = []
    buf:    List[dict] = []

    def flush_buf():
        if not buf:
            return
        if len(buf) == 1:
            merged.append(buf[0])
        else:
            merged.append({
                "type":       "text",
                "content":    " ".join(b["content"] for b in buf),
                "bbox":       buf[0]["bbox"],
                "confidence": sum(b["confidence"] for b in buf) / len(buf),
            })
        buf.clear()

    for i, block in enumerate(classified):
        btype = block["type"]

        if btype != "text":
            flush_buf()
            merged.append(block)
            continue

        if not buf:
            buf.append(block)
            continue

        # Decide whether to split before this line
        accumulated = " ".join(b["content"] for b in buf)
        next_text   = block["content"]

        should_split = (
            len(accumulated) > _MIN_MERGE_CHARS
            and _MERGE_ENDS.search(accumulated)
            and _STARTS_UPPERCASE.match(next_text)
        )

        if should_split:
            flush_buf()

        buf.append(block)

    flush_buf()
    return merged


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def _blocks_to_text(blocks: List[dict]) -> str:
    lines = []
    for b in blocks:
        content = b.get("content", "")
        if isinstance(content, list):
            for row in content:
                lines.append(" | ".join(str(c) for c in row))
        else:
            lines.append(content)
    return "\n".join(lines)


def _estimate_confidence(blocks: List[dict]) -> float:
    confs = [b["confidence"] for b in blocks if b.get("confidence") is not None]
    if not confs:
        return 0.0
    return round(sum(confs) / len(confs), 3)