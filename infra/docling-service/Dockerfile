FROM python:3.12-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DOCLING_ENV=production \
    HOME=/var/lib/docling \
    XDG_CACHE_HOME=/var/lib/docling/cache \
    HF_HOME=/var/lib/docling/cache/huggingface

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libreoffice-writer \
        libgl1 \
        libglib2.0-0 \
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
    && mkdir -p /var/lib/docling \
    && chown -R docling:docling /opt/docling-service /var/lib/docling

EXPOSE 8600
VOLUME ["/var/lib/docling"]
USER docling
CMD ["python", "main.py"]
