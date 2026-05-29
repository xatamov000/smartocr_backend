"""
Image Preprocessing for OCR — Production v3

Changes vs v2:
- NEW: phone chrome cropping (status bar + nav bar) before any other step.
       Eliminates "Tools / Mobile View / Share / Edit on PC" appearing in OCR.
- Perspective correction is still SKIPPED for portrait phone screenshots.
- Deskew kept but only applied when |angle| > 1°.
- Default max_dim aligned with ocr_engine.DET_LIMIT_SIDE_LEN (1920).
"""

import cv2
import numpy as np


# ─────────────────────────────────────────────
# Geometry helpers
# ─────────────────────────────────────────────


def order_points(pts):
    rect = np.zeros((4, 2), dtype="float32")
    s = pts.sum(axis=1)
    diff = np.diff(pts, axis=1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]
    rect[1] = pts[np.argmin(diff)]
    rect[3] = pts[np.argmax(diff)]
    return rect


def four_point_transform(image, pts):
    rect = order_points(pts)
    tl, tr, br, bl = rect

    widthA = np.linalg.norm(br - bl)
    widthB = np.linalg.norm(tr - tl)
    maxW = max(int(widthA), int(widthB))

    heightA = np.linalg.norm(tr - br)
    heightB = np.linalg.norm(tl - bl)
    maxH = max(int(heightA), int(heightB))

    dst = np.array(
        [[0, 0], [maxW - 1, 0], [maxW - 1, maxH - 1], [0, maxH - 1]],
        dtype="float32",
    )

    M = cv2.getPerspectiveTransform(rect, dst)
    warped = cv2.warpPerspective(image, M, (maxW, maxH))
    return warped


# ─────────────────────────────────────────────
# Border / contour analysis
# ─────────────────────────────────────────────


def _border_strength(gray):
    h, w = gray.shape[:2]
    band = max(4, int(round(min(h, w) * 0.03)))
    if h <= band * 2 or w <= band * 2:
        return 0.0

    border = np.concatenate(
        [
            gray[:band, :].ravel(),
            gray[-band:, :].ravel(),
            gray[band:-band, :band].ravel(),
            gray[band:-band, -band:].ravel(),
        ]
    )
    center = gray[band:-band, band:-band]
    if center.size == 0 or border.size == 0:
        return 0.0
    return abs(float(border.mean()) - float(center.mean())) / 255.0


def _document_candidate(image):
    """
    Find the best quadrilateral page candidate.
    Returns (pts, confidence, border_strength).
    """
    if image is None:
        return None, 0.0, 0.0

    h0, w0 = image.shape[:2]
    if h0 < 10 or w0 < 10:
        return None, 0.0, 0.0

    target = 1200
    scale = min(1.0, target / float(max(h0, w0)))
    small = (
        cv2.resize(image, (int(w0 * scale), int(h0 * scale)), interpolation=cv2.INTER_AREA)
        if scale < 1.0
        else image
    )

    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    border_strength = _border_strength(gray)

    edges = cv2.Canny(gray, 50, 150)
    k = max(3, int(round(min(small.shape[:2]) * 0.01)) | 1)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (k, k))
    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel, iterations=2)

    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None, 0.0, border_strength

    contours = sorted(contours, key=cv2.contourArea, reverse=True)[:10]
    img_area = float(small.shape[0] * small.shape[1])
    best = None
    best_conf = 0.0

    for c in contours:
        area = cv2.contourArea(c)
        if area < img_area * 0.10:
            continue
        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.02 * peri, True)
        if len(approx) != 4:
            continue
        confidence = min(1.0, (area / img_area) / 0.55)
        if confidence > best_conf:
            best = approx
            best_conf = confidence

    if best is None:
        return None, 0.0, border_strength

    pts = best.reshape(4, 2).astype("float32")
    if scale < 1.0:
        pts = pts / scale
    return pts, best_conf, border_strength


# ─────────────────────────────────────────────
# Phone chrome cropping (NEW)
# ─────────────────────────────────────────────


def _has_phone_chrome(image) -> bool:
    """
    Detect whether the image has solid dark bands at top and/or bottom
    (phone status bar / nav bar). Used to decide whether to invoke
    chrome cropping.
    """
    if image is None:
        return False
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
    h, w = gray.shape
    if h < 100 or w < 100:
        return False
    top_band = gray[: max(40, int(h * 0.04))]
    bot_band = gray[-max(40, int(h * 0.08)) :]
    top_dark = float((top_band < 30).mean())
    bot_dark = float((bot_band < 30).mean())
    return top_dark > 0.55 or bot_dark > 0.35


def _crop_phone_chrome(image):
    """
    Crop solid dark bands at top and bottom.
    Conservative safety rules:
      - Never crop more than the top/bottom 20% of the image
      - Never let total cropped height exceed 50% of original
    """
    if image is None:
        return image
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
    h, w = gray.shape
    if h < 100 or w < 100:
        return image

    row_dark_frac = (gray < 30).mean(axis=1)

    limit = int(h * 0.20)
    top = 0
    for i in range(limit):
        if row_dark_frac[i] < 0.85:
            top = i
            break
    bot = h
    for i in range(limit):
        if row_dark_frac[h - 1 - i] < 0.85:
            bot = h - i
            break

    if top == 0 and bot == h:
        return image
    if (bot - top) < (h * 0.50):
        return image

    return image[top:bot, :]


# ─────────────────────────────────────────────
# Phone screenshot detection
# ─────────────────────────────────────────────


def _is_phone_screenshot(image) -> bool:
    """
    Return True when the image is likely a phone screenshot or digital capture
    (as opposed to a camera photo of a physical document).

    Phone screenshots don't need perspective correction; applying it can
    actively degrade quality by warping the document area within the UI.

    Heuristics:
    - Portrait aspect ratio > 1.75
    - Very wide landscape (rotated phone) aspect ratio < 0.57
    - Near-zero noise in border pixels (digitally generated)
    """
    if image is None:
        return False
    h, w = image.shape[:2]
    aspect = h / float(w) if w > 0 else 1.0

    if aspect > 1.75:
        return True
    if aspect < 0.57:
        return True

    band = max(2, int(min(h, w) * 0.015))
    if h <= band * 2 or w <= band * 2:
        return False

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
    top = gray[:band, :].astype(float)
    bottom = gray[-band:, :].astype(float)
    left = gray[band:-band, :band].astype(float)
    right = gray[band:-band, -band:].astype(float)

    border_std = float(np.concatenate([top.ravel(), bottom.ravel(), left.ravel(), right.ravel()]).std())
    return border_std < 8.0


# ─────────────────────────────────────────────
# Document candidate / perspective
# ─────────────────────────────────────────────


def detect_document(image):
    """Perspective-correct a physical document photo."""
    if image is None:
        return image
    pts, confidence, _ = _document_candidate(image)
    if pts is None or confidence < 0.35:
        return image
    return four_point_transform(image, pts)


# ─────────────────────────────────────────────
# Deskew
# ─────────────────────────────────────────────


def deskew(image):
    """Correct skew. Only applied when |angle| > 1°."""
    if image is None:
        return image

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
    gray_blur = cv2.GaussianBlur(gray, (3, 3), 0)
    _, bw = cv2.threshold(gray_blur, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    bw = cv2.morphologyEx(bw, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8), iterations=1)

    coords = cv2.findNonZero(bw)
    if coords is None or len(coords) < 200:
        return image

    rect = cv2.minAreaRect(coords)
    angle = rect[-1]
    if angle < -45:
        angle = 90 + angle

    if abs(angle) < 1.0:
        return image

    h, w = image.shape[:2]
    M = cv2.getRotationMatrix2D((w // 2, h // 2), angle, 1.0)
    return cv2.warpAffine(
        image,
        M,
        (w, h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )


# ─────────────────────────────────────────────
# Size normalisation
# ─────────────────────────────────────────────


def normalize_size(image, max_dim=1920):
    """
    Only downscale when the image exceeds max_dim on its longest edge.
    Never upscale (upscaling adds no OCR information).
    """
    if image is None:
        return image
    h, w = image.shape[:2]
    m = max(h, w)
    if m > max_dim:
        scale = max_dim / float(m)
        new_w = max(1, int(round(w * scale)))
        new_h = max(1, int(round(h * scale)))
        return cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_AREA)
    return image


# ─────────────────────────────────────────────
# Public pipeline
# ─────────────────────────────────────────────


def preprocess_image(image, max_dim=1920, apply_perspective=True):
    """
    Full preprocessing pipeline.

    Order:
      1. Phone chrome crop (if status bar / nav bar detected)
      2. Perspective correction (skipped for phone screenshots)
      3. Deskew (skipped for phone screenshots)
      4. Size normalisation (downscale only if > max_dim)

    Returns a BGR ndarray ready for PaddleOCR.
    """
    if image is None:
        return image

    is_screenshot = _is_phone_screenshot(image)

    # ── 1. Phone chrome crop ──────────────────────────────────────────────
    # Even non-screenshot photos can have phone chrome (user photographs
    # their phone screen). Use chrome detection independent of aspect.
    if is_screenshot or _has_phone_chrome(image):
        image = _crop_phone_chrome(image)
        # Re-evaluate screenshot status after crop
        is_screenshot = _is_phone_screenshot(image)

    # ── 2. Perspective correction (only for non-screenshot photos) ────────
    if apply_perspective and not is_screenshot:
        h, w = image.shape[:2]
        aspect_ratio = max(h, w) / float(max(1, min(h, w)))
        near_rect = 1.2 <= aspect_ratio <= 1.6

        _, contour_conf, border_str = _document_candidate(image)
        should_warp = contour_conf >= 0.35

        if near_rect and border_str < 0.12 and contour_conf < 0.55:
            should_warp = False

        if should_warp:
            image = detect_document(image)

    # ── 3. Deskew (only for non-screenshot) ───────────────────────────────
    if not is_screenshot:
        image = deskew(image)

    # ── 4. Size normalisation ─────────────────────────────────────────────
    image = normalize_size(image, max_dim=max_dim)
    return image


# ─────────────────────────────────────────────
# Convenience aliases (kept for backward compatibility)
# ─────────────────────────────────────────────


def preprocess_for_paddle(image, max_dim: int = 1920) -> np.ndarray:
    return preprocess_image(image, max_dim=max_dim, apply_perspective=True)


def preprocess_for_tesseract(image, max_dim=3000):
    """Legacy Tesseract preprocessing (binarised). Kept for fallback path."""
    image = detect_document(image)
    image = deskew(image)

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
    h, w = gray.shape

    if max(h, w) < 3000:
        scale = 3000 / max(h, w)
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    elif max(h, w) > 5000:
        scale = 5000 / max(h, w)
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    gray = clahe.apply(gray)
    gray = cv2.fastNlMeansDenoising(gray, h=10)
    thresh = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 10
    )
    return thresh