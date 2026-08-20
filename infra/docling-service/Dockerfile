FROM python:3.12-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DOCLING_ENV=production \
    HOME=/tmp/docling-home \
    XDG_CACHE_HOME=/tmp/docling-cache

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libreoffice-writer \
        tesseract-ocr \
        tesseract-ocr-eng \
        tesseract-ocr-kaz \
        tesseract-ocr-rus \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/docling-service
COPY requirements.txt ./
RUN python -m pip install --upgrade pip \
    && python -m pip install \
        --index-url https://download.pytorch.org/whl/cpu \
        torch==2.7.1+cpu \
        torchvision==0.22.1+cpu \
    && python -m pip install -r requirements.txt

COPY main.py ./

RUN groupadd --system --gid 10001 docling \
    && useradd --system --uid 10001 --gid docling --home-dir /nonexistent --shell /usr/sbin/nologin docling \
    && chown -R docling:docling /opt/docling-service

EXPOSE 8600
USER docling
CMD ["python", "main.py"]
