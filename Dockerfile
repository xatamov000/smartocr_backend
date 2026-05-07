FROM python:3.11-slim

WORKDIR /app

# Install Tesseract with available languages
# Only install packages that definitely exist
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-eng \
    tesseract-ocr-rus \
    && rm -rf /var/lib/apt/lists/*

# Verify
RUN tesseract --list-langs

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Expose port
EXPOSE 8080

# Start server
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]