# Docling production service

Docling runs on the VPS selected by `VPS_URL`. The public endpoint is
`https://docling.kml.kz`; Caddy terminates TLS and proxies to the local service
on port 8600.

## OCR dependencies

Install the converter and Kazakhstan OCR languages:

```sh
apt-get install -y tesseract-ocr tesseract-ocr-kaz tesseract-ocr-rus tesseract-ocr-eng
python -m pip install -r requirements.txt
```

PDF conversion explicitly enables Tesseract CLI OCR with `kaz,rus,eng`.
Override the comma-separated language list with `DOCLING_OCR_LANGUAGES`.

## Authentication

Set the same strong `DOCLING_API_KEY` in the service environment and in the
backend environment. `/health` remains public. `/convert` requires the
`X-Docling-Key` header whenever the service key is configured.

Keep the VPS environment file outside the repository with mode `0600`, and
load it from the systemd unit using `EnvironmentFile=`.

## Production checks

```sh
curl --fail https://docling.kml.kz/health
curl --fail -H "X-Docling-Key: $DOCLING_API_KEY" \
  -F "file=@image-only.pdf" \
  https://docling.kml.kz/convert
```

The OCR smoke document must include Kazakh, Russian, and English image-only
pages. Confirm the response contains marker text from every page before
considering a deployment complete.
