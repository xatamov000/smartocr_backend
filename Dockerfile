FROM python:3.11-slim

# ===============================
# System dependencies (OCR)
# ===============================
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-eng \
    libgl1 \
    && rm -rf /var/lib/apt/lists/*

# ===============================
# Work directory
# ===============================
WORKDIR /app

# ===============================
# Python dependencies
# ===============================
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ===============================
# App source
# ===============================
COPY . .

# ===============================
# Start FastAPI
# ===============================
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "10000"]
