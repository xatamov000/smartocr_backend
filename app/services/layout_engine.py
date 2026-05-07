# app/services/layout_engine.py

"""
Layout Engine — Production v2

PPStructure is kept here for completeness but is DISABLED by default.
It was measured at ~160s/image which makes it impractical for mobile use.
The pipeline in ocr_pipeline.py uses PaddleOCR directly.

To re-enable: set ENABLE_PPSTRUCTURE=1 in the environment.
"""

import logging
import os

logger = logging.getLogger(__name__)

_ENABLE_PPSTRUCTURE = os.getenv("ENABLE_PPSTRUCTURE", "0") == "1"
_use_ppstructure    = False
_structure_engine   = None
_models_ready       = False

if _ENABLE_PPSTRUCTURE:
    try:
        from paddleocr import PPStructure
        _use_ppstructure = True
        logger.info("PPStructure available (ENABLE_PPSTRUCTURE=1)")
    except (ImportError, ModuleNotFoundError) as e:
        logger.warning(f"PPStructure not available: {e}")
else:
    logger.info("PPStructure disabled (ENABLE_PPSTRUCTURE not set)")


def preload_models():
    """No-op unless ENABLE_PPSTRUCTURE=1."""
    if not _use_ppstructure:
        return
    import threading
    t = threading.Thread(target=_load_models, name="ppstructure-loader", daemon=True)
    t.start()


def _load_models():
    global _structure_engine, _models_ready
    try:
        logger.info("PPStructure: loading models...")
        _structure_engine = PPStructure(show_log=False, lang="en")
        _models_ready = True
        logger.info("PPStructure models loaded")
    except Exception as e:
        logger.error(f"PPStructure init failed: {e}")


def analyze_document(image_path: str):
    """Returns None when PPStructure is disabled or not ready."""
    return None


def is_ppstructure_available() -> bool:
    return False