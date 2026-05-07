from typing import List
from pathlib import Path
import os

from PyPDF2 import PdfMerger
from docx import Document


# ============================================================
# PDF MERGE
# ============================================================

def merge_pdfs(input_paths: List[str], output_path: str):
    merger = PdfMerger()
    try:
        for path in input_paths:
            if not os.path.exists(path):
                raise FileNotFoundError(f"File not found: {path}")
            merger.append(path)

        with open(output_path, "wb") as f_out:
            merger.write(f_out)

    finally:
        merger.close()


# ============================================================
# DOCX MERGE
# ============================================================

def merge_docx(input_paths: List[str], output_path: str):
    if not input_paths:
        raise ValueError("No DOCX files provided")

    merged_document = Document(input_paths[0])

    for path in input_paths[1:]:
        sub_doc = Document(path)

        # Sahifa ajratish
        merged_document.add_page_break()

        for element in sub_doc.element.body:
            merged_document.element.body.append(element)

    merged_document.save(output_path)


# ============================================================
# UNIVERSAL MERGE LOGIC
# ============================================================

def detect_and_merge(input_paths: List[str], output_path: str):
    extensions = {Path(p).suffix.lower() for p in input_paths}

    if len(extensions) != 1:
        raise ValueError("All files must be the same type (PDF or DOCX)")

    ext = extensions.pop()

    if ext == ".pdf":
        merge_pdfs(input_paths, output_path)
        return "pdf"

    elif ext == ".docx":
        merge_docx(input_paths, output_path)
        return "docx"

    else:
        raise ValueError("Unsupported file type. Only PDF and DOCX are allowed.")
