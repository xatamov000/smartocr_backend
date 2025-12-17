import os
import shutil
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, JSONResponse

from .ocr_service import run_ocr
from .docx_service import (
    build_docx_bytes_from_image,
    build_docx_bytes_from_images,
)
from .docx_text_service import build_docx_bytes_from_text


# ============================================================
# Paths & app
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="SmartOCR Backend", version="0.3.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# Health
# ============================================================

@app.get("/health")
def health():
    return {"status": "ok"}


# ============================================================
# OCR: image -> text (AUTO + document_id)
# ============================================================

@app.post("/ocr")
async def ocr_endpoint(
    image: UploadFile = File(...),
    lang: str = Form("auto"),
    document_id: Optional[str] = Form(None),
):
    save_path: Path | None = None
    try:
        ext = Path(image.filename or "img").suffix or ".jpg"
        save_path = UPLOAD_DIR / f"img_{os.urandom(8).hex()}{ext}"

        with save_path.open("wb") as f:
            shutil.copyfileobj(image.file, f)

        text = run_ocr(
            save_path,
            lang=lang,
            
        )

        return {
            "text": text,
        }

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"detail": f"OCR error: {e}"},
        )

    finally:
        if save_path is not None:
            try:
                save_path.unlink(missing_ok=True)
            except Exception:
                pass


# ============================================================
# DOCX: text -> docx
# ============================================================

@app.post("/build-docx")
async def build_docx_endpoint(text: str = Form(...)):
    try:
        docx_bytes = build_docx_bytes_from_text(text)

        headers = {
            "Content-Disposition": 'attachment; filename="result.docx"'
        }
        return Response(
            content=docx_bytes,
            media_type=(
                "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document"
            ),
            headers=headers,
        )

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"detail": f"DOCX error: {e}"},
        )


@app.post("/build_docx")
async def build_docx_endpoint_alias(text: str = Form(...)):
    return await build_docx_endpoint(text)


# ============================================================
# DOCX: 1 image
# ============================================================

@app.post("/image-to-docx")
async def image_to_docx(
    image: UploadFile = File(...),
    lang: str = Form("auto"),
    document_id: Optional[str] = Form(None),
):
    save_path: Path | None = None
    try:
        ext = Path(image.filename or "img").suffix or ".jpg"
        save_path = UPLOAD_DIR / f"img_{os.urandom(8).hex()}{ext}"

        with save_path.open("wb") as f:
            shutil.copyfileobj(image.file, f)

        docx_bytes = build_docx_bytes_from_image(
            save_path,
            lang=lang,
        )

        headers = {
            "Content-Disposition": 'attachment; filename="result.docx"'
        }
        return Response(
            content=docx_bytes,
            media_type=(
                "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document"
            ),
            headers=headers,
        )

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"detail": f"IMAGE->DOCX error: {e}"},
        )

    finally:
        if save_path is not None:
            try:
                save_path.unlink(missing_ok=True)
            except Exception:
                pass


# ============================================================
# DOCX: many images
# ============================================================

@app.post("/images-to-docx")
async def images_to_docx(
    images: List[UploadFile] = File(...),
    lang: str = Form("auto"),
    document_id: Optional[str] = Form(None),
):
    saved: List[Path] = []
    try:
        for im in images:
            ext = Path(im.filename or "img").suffix or ".jpg"
            save_path = UPLOAD_DIR / f"img_{os.urandom(8).hex()}{ext}"

            with save_path.open("wb") as f:
                shutil.copyfileobj(im.file, f)

            saved.append(save_path)

        docx_bytes = build_docx_bytes_from_images(
            saved,
            lang=lang,
        )

        headers = {
            "Content-Disposition": 'attachment; filename="result.docx"'
        }
        return Response(
            content=docx_bytes,
            media_type=(
                "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document"
            ),
            headers=headers,
        )

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"detail": f"IMAGES->DOCX error: {e}"},
        )

    finally:
        for p in saved:
            try:
                p.unlink(missing_ok=True)
            except Exception:
                pass
