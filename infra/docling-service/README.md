# Document converter service

Docling and the local MarkItDown adapter run on the VPS selected by `VPS_URL`.
The public endpoint is `https://docling.kml.kz`; Caddy terminates TLS and
proxies to the local service on port 8600.

## Conversion routing

- Digital PDF files with sufficient embedded text: a lightweight PDF preflight
  selects local MarkItDown without initializing Docling. If the output is empty
  or unusable, Docling is used as a quality fallback.
- Scanned or low-text PDF files: Docling is primary because it provides OCR,
  layout, and table extraction. If Docling fails, MarkItDown remains an
  explicitly degraded text-only fallback.
- Image files: Docling is primary and remains the only route because OCR is
  required.
- DOCX, XLS, and XLSX: MarkItDown 0.1.6 is primary; Docling is the fallback.
- Legacy DOC: LibreOffice converts it to DOCX first, then the Office route is
  used.

MarkItDown is instantiated with plugins disabled and is called only with a
local temporary path through `convert_local`. The endpoint does not accept
URLs or perform network conversion. Every response keeps `markdown`, `pages`,
`tables`, and `filename`, and also reports `engine`, `engine_version`,
`fallback_used`, and `warnings`. New backward-compatible fields `profile` and
`routing_reason` explain the route.

## Upload and concurrency controls

Uploads are streamed to a temporary file and are never read into memory as one
large byte string. Conversion is executed in a worker thread so `/health`
remains responsive while Docling or LibreOffice is running. A bounded async
slot protects the resident Docling models; the default is one conversion at a
time. Requests that wait longer than the configured timeout receive HTTP 503
with `Retry-After`.

Configuration:

```sh
CONVERTER_MAX_UPLOAD_BYTES=52428800
CONVERTER_MAX_CONCURRENCY=1
CONVERTER_QUEUE_WAIT_TIMEOUT_SECONDS=30
CONVERTER_PDF_SAMPLE_PAGES=3
CONVERTER_PDF_MIN_EMBEDDED_TEXT_CHARS=80
CONVERTER_PDF_MIN_TEXT_PAGE_RATIO=0.6
```

Do not increase `CONVERTER_MAX_CONCURRENCY` on a small VPS without measuring
peak RSS: a Docling OCR/table conversion can load models and rasterized pages
into memory concurrently.

## OCR dependencies

Install the converter and Kazakhstan OCR languages:

```sh
apt-get install -y libreoffice-writer tesseract-ocr tesseract-ocr-kaz tesseract-ocr-rus tesseract-ocr-eng
python -m pip install -r requirements.txt
```

PDF conversion explicitly enables Tesseract CLI OCR with `kaz,rus,eng`.
Override the comma-separated language list with `DOCLING_OCR_LANGUAGES`.
Legacy `.doc` files are converted to `.docx` with headless LibreOffice before
Docling processes them.

## Authentication

Set the same strong `DOCLING_API_KEY` (minimum 32 characters in production) in
the service environment and in the backend environment. `/health` remains
public. `/convert` always requires the `X-Docling-Key` header. Production
startup fails closed when the key is absent or too short.

DOCX/XLSX are checked as bounded OOXML archives before MarkItDown/Docling:
unsafe paths, symlinks, encrypted entries, generic ZIPs, excessive entry count,
expanded bytes and compression ratios are rejected before parser invocation.
The container and systemd service run as the dedicated non-root `docling` user.
The native unit stores only its writable model cache under the systemd-managed
`/var/lib/docling` state directory and applies an 8 GiB memory ceiling, four-CPU
quota, bounded task count, private temporary directory, strict umask and an
empty capability set. Validate these limits against measured document sizes
before changing them; do not increase concurrency to compensate for a queue.

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
