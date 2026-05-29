# app/services/ocr_pipeline.py

"""
OCR Pipeline — Production v3

Changes vs v2:
- Geometry-aware paragraph merging (uses bbox y-gaps, not just length)
- Hyphenation join across line breaks
- Heading classifier requires ≥70% uppercase letters (cuts false positives)
- Additional noise patterns (scanner app filenames, page indicators, Uzbek UI)
- Post-OCR Uzbek/Cyrillic normalization via text_normalize.normalize()
- _blocks_to_text emits blank lines between paragraphs so DOCX builders
  produce real paragraph breaks
"""

import re
import time
import logging
from typing import Dict, List

from .ocr_engine import ocr_full_image
from .text_normalize import normalize as normalize_text

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# Noise patterns (phone UI artifacts)
# ─────────────────────────────────────────────

_NOISE_PATTERNS = [
    # Status-bar / system UI
    re.compile(r"^\d{1,2}:\d{2}$"),                       # "21:12"
    re.compile(r"^\d+%$"),                                # "97%"
    re.compile(r"^(\d+[,.]?\d*\s*)?KB/s$", re.I),         # "10.3 KB/s"
    re.compile(r"^4G[+]?$|^5G[+]?$|^LTE$", re.I),         # "4G+"
    re.compile(r"^\d+/\d+$"),                             # "1/117" page indicator
    re.compile(r"^chrome-native://", re.I),               # Chrome PDF URL bar
    re.compile(r"^https?://", re.I),                      # any URL
    re.compile(r"^\+$"),                                  # stray "+"
    re.compile(r"^\d+$"),                                 # bare number (page number)

    # Scanner app filename headers (e.g. "Scan_20260507_155830")
    re.compile(r"^Scan[_\-]\d{8}[_\-]?\d*$", re.I),

    # Notification text in status bar
    re.compile(r"^\d+\s+ta\s+qurilma$", re.I),            # "1 ta qurilma"

    # Common phone UI labels (Uzbek + English)
    re.compile(r"^(Ulashish|Tahrirlash|O[\u02BB\u02BC'`'']?chirish|Yana)$", re.I),
    re.compile(r"^(Tools|Mobile View|Share|Edit on PC|School Tools|Edit)$", re.I),
]

_NUMBERED_LIST = re.compile(r"^(\d{1,2})[.)]\s+\S")
_BULLET_LIST = re.compile(r"^[•\-–—*]\s+\S")
# Heading must be at least 5 chars and end without sentence-final punctuation.
# Final upper-ratio check is done in _classify().
_HEADING_CAPS = re.compile(r"^[A-ZЁІЎҚҒҲА-Я][A-ZЁІЎҚҒҲА-Яа-яa-z\s\-:,.]{4,80}$")


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

        # ── 2. Per-line text normalisation (Uzbek/Cyrillic) ───────────────
        for it in items:
            it["text"] = normalize_text(it["text"], lang_hint=lang)

        # ── 3. Classify each line ─────────────────────────────────────────
        classified = [_classify(item) for item in items]

        # ── 4. Geometry-aware block merging ───────────────────────────────
        blocks = _merge_blocks(classified)

        # ── 5. Final per-block normalisation (after merging) ──────────────
        for b in blocks:
            content = b.get("content")
            if isinstance(content, str):
                b["content"] = normalize_text(content, lang_hint=lang)

        plain_text = _blocks_to_text(blocks)
        confidence = _estimate_confidence(blocks)

        return {
            "blocks":          blocks,
            "plain_text":      plain_text,
            "confidence":      confidence,
            "processing_time": round(time.time() - start, 3),
            "engine":          "paddle",
        }

    except Exception as e:
        logger.error(f"OCR pipeline error: {e}", exc_info=True)
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
    elif _HEADING_CAPS.match(text) and len(text) <= 80:
        # Additional safety: must be MOSTLY uppercase letters.
        # Otherwise body sentences without final periods get
        # mis-classified as headings.
        letters = [c for c in text if c.isalpha()]
        if letters:
            upper_ratio = sum(1 for c in letters if c.isupper()) / len(letters)
            if upper_ratio >= 0.70:
                block_type = "heading"

    return {
        "type":       block_type,
        "content":    text,
        "bbox":       item.get("bbox", [0, 0, 0, 0]),
        "confidence": item.get("confidence", 0.9),
    }


# ─────────────────────────────────────────────
# Geometry helpers
# ─────────────────────────────────────────────


def _line_height(block: dict) -> float:
    bbox = block.get("bbox", [0, 0, 0, 0])
    return max(1.0, float(bbox[3]) - float(bbox[1]))


def _vertical_gap(prev: dict, cur: dict) -> float:
    return float(cur["bbox"][1]) - float(prev["bbox"][3])


def _x_left(block: dict) -> float:
    return float(block["bbox"][0])


# ─────────────────────────────────────────────
# Block merging (geometry-aware)
# ─────────────────────────────────────────────

_HYPHEN_END = re.compile(r"[-‐‑‒–—]$")


def _merge_blocks(classified: List[dict]) -> List[dict]:
    """
    Merge consecutive 'text' blocks into paragraphs using geometry:
      - Same paragraph: small vertical gap, similar left margin
      - New paragraph: large gap (>0.9× line height) OR significant
                       indent jump

    Lists and headings are kept as separate blocks (never merged).
    Hyphenation across line breaks is collapsed when joining.
    """
    if not classified:
        return []

    # Estimate median line height
    line_heights = [_line_height(b) for b in classified if b["type"] == "text"]
    if not line_heights:
        return classified
    sorted_heights = sorted(line_heights)
    median_h = sorted_heights[len(sorted_heights) // 2]

    # Estimate column left edge (10th percentile of x_left)
    text_lefts = sorted([_x_left(b) for b in classified if b["type"] == "text"])
    if text_lefts:
        col_left = text_lefts[max(0, len(text_lefts) // 10)]
    else:
        col_left = 0.0

    merged: List[dict] = []
    buf: List[dict] = []

    def flush_buf():
        if not buf:
            return
        if len(buf) == 1:
            merged.append(buf[0])
        else:
            # Smart join with hyphenation handling
            parts: List[str] = []
            for i, b in enumerate(buf):
                txt = b["content"]
                if i > 0 and parts and _HYPHEN_END.search(parts[-1]):
                    parts[-1] = _HYPHEN_END.sub("", parts[-1]) + txt
                else:
                    parts.append(txt)
            merged.append(
                {
                    "type": "text",
                    "content": " ".join(parts),
                    "bbox": [
                        min(float(b["bbox"][0]) for b in buf),
                        float(buf[0]["bbox"][1]),
                        max(float(b["bbox"][2]) for b in buf),
                        float(buf[-1]["bbox"][3]),
                    ],
                    "confidence": sum(b["confidence"] for b in buf) / len(buf),
                }
            )
        buf.clear()

    for block in classified:
        btype = block["type"]

        # Non-text → flush and emit alone
        if btype != "text":
            flush_buf()
            merged.append(block)
            continue

        if not buf:
            buf.append(block)
            continue

        prev = buf[-1]
        gap = _vertical_gap(prev, block)
        cur_indent = _x_left(block) - col_left
        prev_indent = _x_left(prev) - col_left

        big_gap = gap > median_h * 0.9
        indent_jump = cur_indent > median_h * 0.7 and prev_indent < median_h * 0.4

        if big_gap or indent_jump:
            flush_buf()

        buf.append(block)

    flush_buf()
    return merged


# ─────────────────────────────────────────────
# Render to plain text
# ─────────────────────────────────────────────


def _blocks_to_text(blocks: List[dict]) -> str:
    """
    Render blocks to plain text with blank-line paragraph separation,
    so downstream DOCX builders produce real paragraph breaks.
    """
    parts: List[str] = []
    for b in blocks:
        btype = b.get("type", "text")
        content = b.get("content", "")

        if isinstance(content, list):
            # Tables
            for row in content:
                parts.append(" | ".join(str(c) for c in row))
            parts.append("")
        elif btype == "heading":
            parts.append("")
            parts.append(content)
            parts.append("")
        elif btype == "list":
            parts.append(content)
        else:
            parts.append(content)
            parts.append("")

    # Collapse runs of blank lines
    out: List[str] = []
    prev_blank = False
    for line in parts:
        is_blank = line.strip() == ""
        if is_blank and prev_blank:
            continue
        out.append(line)
        prev_blank = is_blank
    return "\n".join(out).strip()


def _estimate_confidence(blocks: List[dict]) -> float:
    confs = [b["confidence"] for b in blocks if b.get("confidence") is not None]
    if not confs:
        return 0.0
    return round(sum(confs) / len(confs), 3)