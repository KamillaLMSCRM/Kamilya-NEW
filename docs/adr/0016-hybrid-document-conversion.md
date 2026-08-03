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

- PDF and images: Docling primary;
- DOCX, XLS and XLSX: MarkItDown 0.1.6 primary, Docling fallback;
- DOC: headless LibreOffice to DOCX, then the Office route;
- digital PDF: MarkItDown only as a degraded fallback when Docling fails.

MarkItDown plugins and network/URI conversion are disabled. Every successful
response reports the engine, package version, fallback flag and warnings. A
small deterministic gate rejects empty, binary-like or non-alphanumeric output;
failure of all allowed routes is terminal and must not create placeholder
embeddings.

## Consequences

- Native Office files no longer consume the heavier Docling path by default.
- PDF OCR and table/layout fidelity stay with Docling.
- Operations can identify the actual engine from the indexing job result.
- The public endpoint and API-key contract remain backward compatible.
- PPTX, HTML and EPUB are not exposed by the product upload contract until
  format-specific quality and security acceptance tests exist.
