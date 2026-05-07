"""
DATASET BUILDER
Rasmlardan OCR chiqarib, CSV dataset yaratadi.
Label ustuni bo'sh qoladi — siz Excel/CSV da to'ldirasiz.

Ishlatish:
    python dataset_builder.py --images docs/ --output dataset.csv
"""

import argparse
import os
import glob
import cv2
import numpy as np
import pandas as pd
import pytesseract
from pytesseract import Output
import re


OCR_LANG = "uzb_cyrl+uzb+rus+eng"


def preprocess(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
    h, w = gray.shape
    if max(h, w) < 2000:
        scale = 2500 / max(h, w)
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
    gray = clahe.apply(gray)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return binary


def extract_features(image_path):
    image = cv2.imread(image_path)
    if image is None:
        return []

    h_img, w_img = image.shape[:2]
    processed = preprocess(image)

    data = pytesseract.image_to_data(
        processed, lang=OCR_LANG,
        config="--oem 1 --psm 3",
        output_type=Output.DICT
    )

    lines_map = {}
    for i in range(len(data["text"])):
        word = (data["text"][i] or "").strip()
        try:
            conf = int(float(data["conf"][i]))
        except Exception:
            conf = -1
        if not word or conf < 10:
            continue

        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        if key not in lines_map:
            lines_map[key] = {
                "words": [], "top": data["top"][i], "left": data["left"][i],
                "height": data["height"][i], "conf_list": []
            }
        lines_map[key]["words"].append(word)
        lines_map[key]["conf_list"].append(conf)
        lines_map[key]["top"] = min(lines_map[key]["top"], data["top"][i])
        lines_map[key]["height"] = max(lines_map[key]["height"], data["height"][i])

    if not lines_map:
        return []

    all_heights = [v["height"] for v in lines_map.values() if v["height"] > 0]
    avg_height = float(np.mean(all_heights)) if all_heights else 20.0

    rows = []
    sorted_keys = sorted(lines_map.keys(), key=lambda k: lines_map[k]["top"])
    prev_bottom = 0

    for key in sorted_keys:
        ldata = lines_map[key]
        text = " ".join(ldata["words"]).strip()
        if not text:
            continue

        height = ldata["height"]
        top = ldata["top"]
        left = ldata["left"]
        bottom = top + height

        rel_height = round(height / avg_height, 3) if avg_height > 0 else 1.0
        x_pos = round(left / w_img, 3) if w_img > 0 else 0.0
        y_gap = max(0, top - prev_bottom)
        avg_conf = round(float(np.mean(ldata["conf_list"])), 1) if ldata["conf_list"] else 0.0

        upper_ratio = round(sum(1 for c in text if c.isupper()) / len(text), 3) if text else 0.0
        digit_ratio = round(sum(1 for c in text if c.isdigit()) / len(text), 3) if text else 0.0
        word_count = len(text.split())
        starts_symbol = int(text[0] in "-•*·–—") if text else 0
        is_numbered = int(bool(re.match(r"^\d{1,2}[\.\)]\s", text)))
        ends_colon = int(text.endswith(":"))
        char_count = len(text)

        rows.append({
            "source_file": os.path.basename(image_path),
            "text": text,
            "height": height,
            "rel_height": rel_height,
            "x_pos": x_pos,
            "y_gap": y_gap,
            "uppercase_ratio": upper_ratio,
            "digit_ratio": digit_ratio,
            "word_count": word_count,
            "char_count": char_count,
            "starts_symbol": starts_symbol,
            "is_numbered": is_numbered,
            "ends_colon": ends_colon,
            "confidence": avg_conf,
            "label": ""  # << SHUNGA LABEL YOZASIZ
        })
        prev_bottom = bottom

    return rows


def build_dataset(image_dir: str, output_csv: str):
    image_paths = []
    for ext in ["*.jpg", "*.jpeg", "*.png", "*.bmp", "*.tiff"]:
        image_paths.extend(glob.glob(os.path.join(image_dir, ext)))
        image_paths.extend(glob.glob(os.path.join(image_dir, ext.upper())))

    if not image_paths:
        print(f"Rasm topilmadi: {image_dir}")
        return

    print(f"{len(image_paths)} ta rasm topildi.")
    all_rows = []

    for i, path in enumerate(image_paths):
        print(f"  [{i+1}/{len(image_paths)}] {os.path.basename(path)}")
        rows = extract_features(path)
        all_rows.extend(rows)

    df = pd.DataFrame(all_rows)
    df.to_csv(output_csv, index=False, encoding="utf-8-sig")
    print(f"\nDataset saqlandi: {output_csv}")
    print(f"Jami qatorlar: {len(df)}")
    print(f"\nEndi '{output_csv}' ni Excel/LibreOffice da oching")
    print("va 'label' ustuniga quyidagilardan birini yozing:")
    print("  heading1  - asosiy sarlavha")
    print("  heading2  - kichik sarlavha")
    print("  bullet    - nuqtali ro'yxat")
    print("  numbered  - raqamli ro'yxat")
    print("  paragraph - oddiy abzats")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--images", default="docs", help="Rasmlar joylashgan papka")
    parser.add_argument("--output", default="dataset.csv", help="Chiqish CSV fayli")
    args = parser.parse_args()
    build_dataset(args.images, args.output)