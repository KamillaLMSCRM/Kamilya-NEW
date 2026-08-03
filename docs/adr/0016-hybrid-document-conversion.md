# ADR-0016: Hybrid local document conversion

- Status: accepted
- Date: 2026-08-03

## Context

Kamilya LMS needs reliable extraction from PDF, scanned documents, modern
Office files and legacy Word `.doc`. Docling provides OCR, page layout and table
reconstruction, but using it for every Office document adds avoidable latency
and resource use. MarkItDown produces compact Markdown efficiently for native
Office formats, but it is not a replacement for OCR or layout-aware PDF parsing.

## Decision

Keep one authenticated converter service on the VPS and route locally:

- digital PDF with a usable text layer: MarkItDown 0.1.6 primary;
- scanned or text-poor PDF and images: Docling OCR/layout primary;
- DOCX, XLS and XLSX: MarkItDown 0.1.6 primary, Docling fallback;
- DOC: headless LibreOffice to DOCX, then the Office route.

The PDF classifier inspects a bounded sample of pages before choosing the
route. It does not run OCR merely because the file extension is PDF. The
converter accepts at most one conversion at a time on the current VPS, waits no
more than 30 seconds for that slot and rejects uploads above 50 MiB. Blocking
library calls execute outside the FastAPI event loop.

MarkItDown plugins and network/URI conversion are disabled. Every successful
response reports the engine, package version, fallback flag and warnings. A
small deterministic gate rejects empty, binary-like or non-alphanumeric output;
failure of all allowed routes is terminal and must not create placeholder
embeddings.

## Consequences

- Native Office files and text-layer PDFs no longer consume the heavier Docling
  path by default.
- Scanned PDF OCR and table/layout fidelity stay with Docling.
- A burst cannot create multiple concurrent Docling model loads on the 8 GiB
  VPS; excess work remains in the durable document queue.
- Operations can identify the actual engine from the indexing job result.
- The public endpoint and API-key contract remain backward compatible.
- PPTX, HTML and EPUB are not exposed by the product upload contract until
  format-specific quality and security acceptance tests exist.
