# Copilot / AI assistant instructions for SmartOCR Backend

This file contains concise, actionable guidance for AI coding agents working on this repository.

## Purpose
Make small, low-risk changes and implement features consistent with the project's minimal FastAPI OCR→DOCX backend.

## Quick facts (what runs where)
- Service: FastAPI app defined in `app/main.py` (app instance: `app`).
- Core components:
  - `app/ocr_service.py` — Tesseract integration, image preprocessing, `run_ocr(...)` and `ensure_tesseract()` (Windows handling).
  - `app/docx_service.py` — builds structured .docx from image(s) using Tesseract word/line heuristics.
  - `app/docx_text_service.py` — builds .docx from plain text with simple heuristics (headings, lists).
- Requirements: see `requirements.txt` (FastAPI, uvicorn, pytesseract, pillow, python-docx, python-multipart).
- Uploads directory: `uploads/` (created automatically by `app/main.py`).

## How to run locally (developer workflow)
1. Install Python deps: `pip install -r requirements.txt`.
2. Install Tesseract OCR separately (system package). On Windows ensure tesseract.exe is on PATH or in one of the common install locations; `app/ocr_service.py::ensure_tesseract()` will try common paths.
3. Start the API server: run Uvicorn pointing at `app.main:app`. Example (dev):
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

Notes:
- The project expects a system Tesseract installation. If Tesseract is not found the code raises a RuntimeError.
- For debugging OCR preprocessing images, set env var `OCR_DEBUG_DIR` or use debug flags in calls when adding feature work.

## Architecture & data flow (short)
- client -> POST /ocr | /image-to-docx | /images-to-docx | /build-docx
- `app/main.py` saves incoming `UploadFile` to `uploads/`, calls service functions, then deletes saved files in finally blocks.
- `run_ocr(image_path, lang=...)` returns normalized text. `build_docx_bytes_from_image(s)` converts OCR-derived line/word boxes into Word paragraphs with heuristics for headings, lists and indentation.

## Project-specific conventions and patterns
- Minimal, deterministic file cleanup: `save_path.unlink(missing_ok=True)` in `finally` blocks — keep this behavior when adding temporary file logic.
- Language default: endpoints accept `lang` form field. When `lang == "auto"` the code maps to `AUTO_LANGS` in `app/ocr_service.py` ("eng+rus+uzb+uzb_cyrl"). Respect this mapping when adding language-related features.
- Windows Tesseract handling: `ensure_tesseract()` mutates `pytesseract.pytesseract.tesseract_cmd`; prefer calling it before pytesseract usage. Avoid hardcoding alternative lookup behavior without testing on Windows.
- OCR heuristics are implemented in Python/PIL (no OpenCV). Keep image-processing logic in `docx_service.py` and reuse `_preprocess_for_ocr`/_maybe_autorotate patterns.
- DOCX formation uses python-docx styles: use `List Number`, `List Bullet`, `Heading 2` consistently as existing code does.

## Debugging hints
- If Tesseract errors occur on Windows, check `ensure_tesseract()`; ensure `tesseract.exe` is installed and accessible.
- To inspect preprocessed images add `OCR_DEBUG_DIR` (point to a writable directory) to capture images saved by `ocr_service.run_ocr` when debug instrumentation is added.

## Example request snippets (for tests / docs)
- OCR (returns JSON {"text": ...}):
  - POST multipart/form-data to `/ocr` with field `image` (file) and `lang` (optional, default `auto`).
- Single image → docx: POST `/image-to-docx` (file `image`) — response is application/vnd.openxmlformats-officedocument.wordprocessingml.document with `Content-Disposition: attachment; filename="result.docx"`.

## Where to look when changing behavior
- Endpoint wiring & request/cleanup patterns: `app/main.py`.
- Low-level OCR + normalization: `app/ocr_service.py`.
- Image→DOCX heuristics and layout logic: `app/docx_service.py`.
- Text→DOCX heuristics: `app/docx_text_service.py`.

## Small safe-change checklist for AI edits
1. Preserve file-saving + cleanup behavior in `main.py` (do not leave temp files).
2. Call `ensure_tesseract()` before using pytesseract in additions if you expect Windows runs.
3. Keep python-docx style names unchanged unless intentionally changing formatting globally.
4. Add unit tests or a small integration test (curl + small image/text) when changing parsing heuristics.

---
If anything above is unclear or you'd like more details/examples (sample request bodies, sample images, or unit-test scaffolding), tell me which area to expand and I'll iterate.
