"""
Post-OCR text normalization for Uzbek-Latin and Cyrillic.

Called from ocr_pipeline.process_document() after OCR but before
DOCX building.

Order of operations:
  1. Unicode NFC normalize (collapse decomposed sequences)
  2. Whitespace cleanup
  3. Uzbek apostrophe restoration (oʻ, gʻ, glottal ʼ)
  4. Mixed-token Cyrillic homoglyph repair
  5. Punctuation regularization
  6. Final NFC pass
"""

import re
import unicodedata


# ─────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────

UZ_OK_APOSTROPHE = "\u02BB"  # ʻ — modifier letter turned comma (oʻ, gʻ)
UZ_GLOTTAL = "\u02BC"  # ʼ — modifier letter apostrophe (maʼlum)

# Apostrophe-like characters OCR may emit, EXCLUDING the canonical
# Uzbek modifier letters (U+02BB, U+02BC) — those are the targets of
# our normalisation, not inputs. Including them in the source set
# would re-process already-correct text on subsequent passes.
_APOS_CHARS = "'\u2018\u2019\u02B9`\u00B4"


# ─────────────────────────────────────────────
# Unicode + whitespace
# ─────────────────────────────────────────────


def to_nfc(text: str) -> str:
    """NFC: 'o' + combining ʻ → single canonical form."""
    return unicodedata.normalize("NFC", text)


_WS_RE = re.compile(r"[ \t]+")
_NL_RE = re.compile(r"\n{3,}")


def clean_whitespace(text: str) -> str:
    text = text.replace("\u00A0", " ")  # non-breaking space → regular
    text = text.replace("\u200B", "")  # zero-width space
    text = text.replace("\uFEFF", "")  # BOM
    text = _WS_RE.sub(" ", text)
    text = _NL_RE.sub("\n\n", text)
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    return text


# ─────────────────────────────────────────────
# Uzbek apostrophe restoration
# ─────────────────────────────────────────────

# Word-internal o' / O' / g' / G' → oʻ / Oʻ / gʻ / Gʻ
# Uzbek-Latin orthography: any 'o' or 'g' immediately followed by an
# apostrophe-like character represents the modifier letter ʻ (U+02BB),
# regardless of position in the word. Examples:
#   o'zbek      → oʻzbek    (word-initial)
#   bo'ladi     → boʻladi   (word-internal after consonant)
#   o'g'il      → oʻgʻil    (both)
_UZ_OG_RE = re.compile(
    rf"([oOgG])([{re.escape(_APOS_CHARS)}])"
)

# Glottal stop ʼ (U+02BC): apostrophe between vowels (a/e/i/u, NOT o)
# and a following letter. Examples:
#   ma'lum      → maʼlum
#   ta'sir      → taʼsir
#   she'r       → sheʼr
# Note: 'o' is excluded from the leading vowel class because o' is
# always handled by the OG rule above.
_UZ_GLOTTAL_RE = re.compile(
    rf"([aeiuAEIU])([{re.escape(_APOS_CHARS)}])([a-zA-Z])"
)


def normalize_uzbek_apostrophes(text: str) -> str:
    """Restore Uzbek modifier-letter apostrophes after OCR."""
    text = _UZ_OG_RE.sub(lambda m: m.group(1) + UZ_OK_APOSTROPHE, text)
    text = _UZ_GLOTTAL_RE.sub(
        lambda m: m.group(1) + UZ_GLOTTAL + m.group(3), text
    )
    return text


# ─────────────────────────────────────────────
# Mixed-token Cyrillic homoglyph repair
# ─────────────────────────────────────────────

# Latin-to-Cyrillic homoglyphs. Only fires on tokens that contain
# BOTH Latin AND Cyrillic chars (signature of partial recognition collapse).
_LAT_TO_CYR = {
    "A": "А", "B": "В", "C": "С", "E": "Е", "H": "Н", "K": "К",
    "M": "М", "O": "О", "P": "Р", "T": "Т", "X": "Х", "Y": "У",
    "a": "а", "c": "с", "e": "е", "o": "о", "p": "р", "x": "х", "y": "у",
}

_TOKEN_RE = re.compile(r"\S+")


def _has_cyr(s: str) -> bool:
    return any("\u0400" <= ch <= "\u04FF" for ch in s)


def _has_lat(s: str) -> bool:
    return any(ch.isascii() and ch.isalpha() for ch in s)


def repair_mixed_tokens(text: str) -> str:
    """Replace Latin homoglyphs with Cyrillic in mixed-script tokens only."""

    def _fix(match):
        tok = match.group(0)
        if not (_has_cyr(tok) and _has_lat(tok)):
            return tok
        return "".join(_LAT_TO_CYR.get(ch, ch) for ch in tok)

    return _TOKEN_RE.sub(_fix, text)


# ─────────────────────────────────────────────
# Punctuation tidy
# ─────────────────────────────────────────────

_DOUBLE_PUNCT_RE = re.compile(r"([,.;:!?])\1+")
_SPACE_BEFORE_PUNCT_RE = re.compile(r"\s+([,.;:!?…])")
_NO_SPACE_AFTER_PUNCT_RE = re.compile(r"([,.;:!?])([A-Za-zА-Яа-я])")


def fix_punctuation(text: str) -> str:
    text = _DOUBLE_PUNCT_RE.sub(r"\1", text)
    text = _SPACE_BEFORE_PUNCT_RE.sub(r"\1", text)
    text = _NO_SPACE_AFTER_PUNCT_RE.sub(r"\1 \2", text)
    return text


# ─────────────────────────────────────────────
# Public entry
# ─────────────────────────────────────────────


def normalize(text: str, lang_hint: str | None = None) -> str:
    """Full normalization. Safe to call on any output language.

    Args:
        text: OCR output text
        lang_hint: 'en'/'eng'/'english' to skip Uzbek apostrophe transform.
                   Anything else (including None and 'auto') applies Uzbek
                   normalization, which is safe for Russian and Uzbek-Latin.
    """
    if not text:
        return ""
    text = to_nfc(text)
    text = clean_whitespace(text)
    if (lang_hint or "").lower() not in ("en", "eng", "english"):
        text = normalize_uzbek_apostrophes(text)
    text = repair_mixed_tokens(text)
    text = fix_punctuation(text)
    text = to_nfc(text)
    return text