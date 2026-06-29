FROM python:3.10-slim AS runtime

WORKDIR /app

# Install Tesseract OCR (optional — only needed for vision_backend=tesseract)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-eng \
        tesseract-ocr-chi-sim \
    && rm -rf /var/lib/apt/lists/*

# Copy build artifacts
COPY pyproject.toml ./
COPY VERSION ./
COPY src/ ./src/

# Install the package & prepare data directory
RUN pip install --no-cache-dir . \
    && mkdir -p /data

# Copy entrypoint
COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

EXPOSE 9000

ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["docker-entrypoint.sh"]
