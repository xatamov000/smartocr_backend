# app/main.py
"""
SmartOCR Backend v4 - PaddleOCR Direct Pipeline
No PPStructureV3. Fast. Clean.
"""

import os
import shutil
import traceback
import logging
import asyncio
import uvicorn
from pathlib import Path
from typing import List
from concurrent.futures import ThreadPoolExecutor
import uuid

from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, JSONResponse

from .pdf_compress_service import compress_pdf, CompressionLevel
from .universal_merge_service import detect_and_merge
from .services.ocr_pipeline import process_document
from .export.word_export import build_docx_from_blocks, build_docx_from_text, build_multi_page_docx

try:
    from .docx_text_service import build_docx_bytes_from_text
except ImportError:
    build_docx_bytes_from_text = None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ocr")

app = FastAPI(title="SmartOCR Backend", version="4.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def _run_ocr(path: str, lang: str, timeout: float = 300.0) -> dict:
    loop = asyncio.get_event_loop()
    try:
        return await asyncio.wait_for(
            loop.run_in_executor(_executor, process_document, path, lang),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        logger.error(f"OCR timeout {timeout}s: {path}")
        return {
            "blocks": [],
            "plain_text": "[OCR timed out]",
            "confidence": 0.0,
            "processing_time": timeout,
            "engine": "timeout",
        }


@app.get("/health")
async def health():
    from .services.ocr_engine import is_paddle_available

    return {
        "status": "ok",
        "version": "4.0.0",
        "ocr_engine": "paddleocr" if is_paddle_available() else "tesseract",
    }


@app.get("/")
async def root():
    return {
        "message": "SmartOCR v4",
        "endpoints": {
            "health": "/health",
            "ocr": "/ocr",
            "ocr_docx": "/ocr/docx",
            "docs": "/docs",
        },
    }


@app.post("/ocr")
async def ocr_endpoint(image: UploadFile = File(...), lang: str = Form("auto")):
    tmp = None
    try:
        tmp = UPLOAD_DIR / f"{uuid.uuid4().hex}_{image.filename}"
        with open(tmp, "wb") as f:
            shutil.copyfileobj(image.file, f)
        logger.info(f"/ocr: {image.filename}")
        r = await _run_ocr(str(tmp), lang)
        logger.info(f"/ocr done: engine={r['engine']}, time={r['processing_time']}s")
        return JSONResponse(
            content={
                "text": r["plain_text"],
                "confidence": r["confidence"],
                "processing_time": r["processing_time"],
                "engine": r["engine"],
            }
        )
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e), "detail": traceback.format_exc()})
    finally:
        if tmp and tmp.exists():
            tmp.unlink()


@app.post("/ocr/docx")
async def ocr_docx(image: UploadFile = File(...), lang: str = Form("auto")):
    tmp = None
    try:
        tmp = UPLOAD_DIR / f"tmp_{image.filename}"
        with open(tmp, "wb") as f:
            shutil.copyfileobj(image.file, f)
        logger.info(f"/ocr/docx: {image.filename}")
        r = await _run_ocr(str(tmp), lang)
        logger.info(f"/ocr/docx: {len(r['blocks'])} blocks, {r['processing_time']}s")
        docx = build_docx_from_blocks(r["blocks"])
        return Response(
            content=docx,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={
                "Content-Disposition": f'attachment; filename="{Path(image.filename).stem}_ocr.docx"',
                "X-OCR-Confidence": str(r["confidence"]),
                "X-OCR-Engine": r["engine"],
            },
        )
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e), "detail": traceback.format_exc()})
    finally:
        if tmp and tmp.exists():
            tmp.unlink()


@app.post("/ocr/docx/multi")
async def ocr_docx_multi(images: List[UploadFile] = File(...), lang: str = Form("auto")):
    saved = []
    try:
        pages = []
        for img in images:
            tmp = UPLOAD_DIR / f"tmp_{img.filename}"
            with open(tmp, "wb") as f:
                shutil.copyfileobj(img.file, f)
            saved.append(tmp)
            r = await _run_ocr(str(tmp), lang)
            pages.append(r["blocks"])
        docx = build_multi_page_docx(pages)
        return Response(
            content=docx,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": 'attachment; filename="merged_ocr.docx"'},
        )
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e), "detail": traceback.format_exc()})
    finally:
        for p in saved:
            p.unlink(missing_ok=True)


@app.post("/image-to-docx")
async def image_to_docx(image: UploadFile = File(...), lang: str = Form("auto")):
    return await ocr_docx(image, lang)


@app.post("/images-to-docx")
async def images_to_docx(images: List[UploadFile] = File(...), lang: str = Form("auto")):
    return await ocr_docx_multi(images, lang)


@app.post("/text-to-docx")
async def text_to_docx(text: str = Form(...)):
    try:
        docx = build_docx_bytes_from_text(text) if build_docx_bytes_from_text else build_docx_from_text(text)
        return Response(
            content=docx,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": 'attachment; filename="text.docx"'},
        )
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/compress-pdf")
async def compress_pdf_ep(file: UploadFile = File(...), level: str = Form(...)):
    if level not in ("low", "medium", "high"):
        return JSONResponse(status_code=400, content={"error": "Invalid level"})
    tmp_in = tmp_out = None
    try:
        tmp_in = UPLOAD_DIR / f"tmp_{file.filename}"
        with open(tmp_in, "wb") as f:
            shutil.copyfileobj(file.file, f)
        out_name = f"{Path(file.filename).stem}_compressed_{level}.pdf"
        tmp_out = UPLOAD_DIR / out_name
        compress_pdf(str(tmp_in), str(tmp_out), level)
        with open(tmp_out, "rb") as f:
            data = f.read()
        return Response(
            content=data,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{out_name}"'},
        )
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
    finally:
        if tmp_in and tmp_in.exists():
            tmp_in.unlink()
        if tmp_out and tmp_out.exists():
            tmp_out.unlink()


@app.post("/merge")
async def merge_ep(files: List[UploadFile] = File(...)):
    if len(files) < 2:
        return JSONResponse(status_code=400, content={"error": "At least 2 files required"})
    tmps = []
    tmp_out = None
    try:
        for file in files:
            tmp = UPLOAD_DIR / f"tmp_{file.filename}"
            with open(tmp, "wb") as f:
                shutil.copyfileobj(file.file, f)
            tmps.append(tmp)
        out = UPLOAD_DIR / "merged_output"
        ft = detect_and_merge([str(p) for p in tmps], str(out))
        final = Path(f"{out}.{ft}")
        tmp_out = final if final.exists() else Path(str(out))
        with open(tmp_out, "rb") as f:
            data = f.read()
        mt = "application/pdf" if ft == "pdf" else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        return Response(
            content=data,
            media_type=mt,
            headers={"Content-Disposition": f'attachment; filename="merged_output.{ft}"'},
        )
    except Exception as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    finally:
        for p in tmps:
            if p.exists():
                p.unlink()
        if tmp_out and tmp_out.exists():
            tmp_out.unlink()


if __name__ == "__main__":
    uvicorn.run("app.main:app", reload=True)
