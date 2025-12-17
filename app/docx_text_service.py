# app/docx_text_service.py
from io import BytesIO
from docx import Document


def _is_heading(line: str) -> bool:
    s = line.strip()
    if not s:
        return False
    # qisqa + ko‘proq katta harf (oddiy heuristika)
    if len(s) <= 60 and sum(1 for c in s if c.isupper()) >= max(3, int(len(s) * 0.25)):
        return True
    return False


def _is_numbered(line: str) -> bool:
    s = line.strip()
    if not s:
        return False
    if s[0].isdigit():
        if len(s) >= 2 and s[1] in [".", ")", " "]:
            return True
        if len(s) >= 3 and s[1].isdigit() and s[2] in [".", ")", " "]:
            return True
    return False


def _is_bullet(line: str) -> bool:
    s = line.strip()
    return s.startswith(("-", "•", "·", "*"))


def build_docx_bytes_from_text(text: str) -> bytes:
    """
    Text -> DOCX bytes (heuristic formatting):
    - blank lines => new paragraph spacing
    - numbered/bulleted lines => list styles
    - heading-ish lines => Heading 2
    """
    doc = Document()
    text = (text or "").replace("\r\n", "\n").strip("\n")

    if not text.strip():
        doc.add_paragraph("")
        buf = BytesIO()
        doc.save(buf)
        return buf.getvalue()

    lines = text.split("\n")
    blank_streak = 0

    for raw in lines:
        line = raw.rstrip()
        if not line.strip():
            blank_streak += 1
            continue

        # agar orada blank bo‘lsa — paragraph spacing effekt
        if blank_streak > 0:
            doc.add_paragraph("")  # bo‘sh paragraf (Word’da gap)

        blank_streak = 0
        s = line.strip()

        if _is_numbered(s):
            p = doc.add_paragraph("", style="List Number")
            p.add_run(s)
        elif _is_bullet(s):
            p = doc.add_paragraph("", style="List Bullet")
            p.add_run(s)
        elif _is_heading(s):
            p = doc.add_paragraph("", style="Heading 2")
            p.add_run(s)
        else:
            doc.add_paragraph(s)

    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()
