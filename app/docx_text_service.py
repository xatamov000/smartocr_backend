from io import BytesIO
from docx import Document
from docx.shared import Pt
from docx.oxml.ns import qn

FONT_NAME = "Times New Roman"


def _apply_font(run):
    """
    🔥 SAFE Cyrillic / Uzbek-Cyrl font apply
    """
    run.font.name = FONT_NAME

    rPr = run._element.get_or_add_rPr()
    rFonts = rPr.get_or_add_rFonts()

    rFonts.set(qn("w:ascii"), FONT_NAME)
    rFonts.set(qn("w:hAnsi"), FONT_NAME)
    rFonts.set(qn("w:eastAsia"), FONT_NAME)
    rFonts.set(qn("w:cs"), FONT_NAME)


def _is_heading(line: str) -> bool:
    s = line.strip()
    if not s:
        return False
    return len(s) <= 60 and sum(1 for c in s if c.isupper()) >= max(3, int(len(s) * 0.25))


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
    return line.strip().startswith(("-", "•", "·", "*"))


def build_docx_bytes_from_text(text: str) -> bytes:
    """
    Text -> DOCX bytes
    - 🔥 Cyrillic safe
    - ❌ No 500 error
    """
    doc = Document()
    text = (text or "").replace("\r\n", "\n").strip("\n")

    if not text.strip():
        doc.add_paragraph("")
        buf = BytesIO()
        doc.save(buf)
        return buf.getvalue()

    lines = text.split("\n")
    blank = False

    for raw in lines:
        line = raw.rstrip()

        if not line.strip():
            blank = True
            continue

        if blank:
            doc.add_paragraph("")
            blank = False

        s = line.strip()

        if _is_numbered(s):
            p = doc.add_paragraph("", style="List Number")
        elif _is_bullet(s):
            p = doc.add_paragraph("", style="List Bullet")
        elif _is_heading(s):
            p = doc.add_paragraph("", style="Heading 2")
        else:
            p = doc.add_paragraph("")

        run = p.add_run(s)
        _apply_font(run)

        if _is_heading(s):
            run.bold = True
            run.font.size = Pt(14)

    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()
