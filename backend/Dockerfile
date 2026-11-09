FROM python:3.12-slim

# Tesseract (used by Docling for OCR, English + Hindi), LibreOffice for .doc/.xls/.xlsb/.ppt conversion,
# libgl/libglib for Docling's image processing.
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr tesseract-ocr-eng tesseract-ocr-hin \
        libreoffice-writer-nogui libreoffice-calc-nogui libreoffice-impress-nogui \
        fonts-dejavu fonts-liberation libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY rag ./rag
COPY main.py .
COPY tests ./tests

RUN useradd --create-home app && mkdir -p /data && chown app /data
USER app
ENV DATA_DIR=/data PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["uvicorn", "rag.api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
