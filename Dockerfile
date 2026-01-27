FROM python:3.11-slim

# =========================================================
# System dependencies:
# - Tesseract OCR (eng + rus + osd)
# - Fonts for DOCX (Times-like + latin + cyrillic)
# =========================================================
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-eng \
    tesseract-ocr-rus \
    tesseract-ocr-osd \
    libgl1 \
    fontconfig \
    fonts-dejavu \
    fonts-liberation \
    fonts-noto \
    fonts-open-sans \
    fonts-crosextra-carlito \
    && rm -rf /var/lib/apt/lists/*

# =========================================================
# Work directory
# =========================================================
WORKDIR /app

# =========================================================
# Python dependencies
# =========================================================
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# =========================================================
# App source
# =========================================================
COPY . .

# =========================================================
# Start FastAPI
# =========================================================
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "10000"]
