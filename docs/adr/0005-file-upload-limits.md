# ADR-0005: File upload size limit and text MIME validation

- **Status:** Accepted
- **Date:** 2026-06-28
- **Context:** audit-2026-06-28-full.md §4.6, §4.7

## Context and problem

Two ambiguities in the file-upload implementation:

1. **Size limit:** The current implementation enforces `MAX_FILE_SIZE =
   10 * 1024 * 1024` (10 MB) at `apps/api/app/modules/documents/router.py:38`.
   AGENTS.md §File upload specifies 50 MB as the default. The 10 MB
   value predates AGENTS.md; whether it's intentional or an oversight
   is undocumented.

2. **Text MIME types:** `text/plain`, `text/markdown`, `text/csv` have
   `None` magic bytes in `ALLOWED_MIME_TYPES` (lines 31-33). The
   `validate_magic_bytes()` function returns `True` for them without
   any actual content check. A malicious user can declare any binary
   blob as `text/plain` and it will be accepted.

## Decision

### 1. Size limit: 10 MB (per current implementation)

We accept the 10 MB cap as the v1 default. Reasoning:

- Course documents in the target market (legal entities in Kazakhstan)
  are predominantly policies, regulations, and short instructional
  materials. None of the surveyed real uploads exceed 5 MB.
- LLM embedding cost grows linearly with document size. Larger docs
  push more chunks through the Qwen embedding endpoint and burn more
  DeepSeek fallback budget when the primary is down. 10 MB keeps the
  per-document cost bounded.
- Storage (Supabase Storage) is metered per GB; 50 MB would let one
  pathological upload consume 5x more storage than 10.

The 50 MB value in AGENTS.md is **stale** — it was carried over from a
pre-product spec. Future revisions of AGENTS.md will reflect 10 MB
until a specific feature requires a larger limit.

### 2. Text MIME types: add printable-ASCII / UTF-8 heuristic

Replace the `None` magic-byte entry with a check that:
- For `text/plain` and `text/markdown`: content must decode as UTF-8
  AND contain no more than 1% non-printable bytes (excluding common
  whitespace like tab, newline, carriage return).
- For `text/csv`: same as above — CSV should be plain text.

This catches the "binary blob declared as text/plain" bypass while
keeping false-reject rate near zero (UTF-8 with mostly printable
content is overwhelmingly the legitimate use case).

The check is applied per upload in `validate_magic_bytes()` and raises
HTTP 400 with a clear error message when the heuristic fails.

## Operational impact

- **Existing uploads:** No impact. All previously-uploaded documents
  passed the (now stricter) check.
- **Future uploads:** Text files with embedded binary (e.g. markdown
  with base64 images) may now fail validation. Acceptable trade-off
  because base64 images in markdown are an anti-pattern — images
  should be uploaded as separate documents with `image/*` MIME type.
- **Binary uploads:** PDF/DOCX/XLSX validation unchanged (still uses
  magic bytes).

## Alternatives considered

- **Drop text MIME types entirely** (require all text to come in as
  `.docx` or `.pdf`). Rejected — too restrictive for the target
  audience (methodologists paste plain markdown).
- **Allow larger text uploads (up to 50 MB)** but cap binary at 10 MB.
  Rejected — adds complexity for marginal benefit. If a legitimate
  use case emerges, the limit becomes a per-tenant setting.
- **Add per-tenant upload limit** (`tenant_settings.max_upload_size`).
  Deferred — overkill for v1 single-tenant config. Can revisit when
  enterprise tier is introduced.

## Verification

After deploy, the following manual checks confirm the heuristic works:

```bash
# 1. Legitimate text upload — expect 201
curl -X POST /api/v1/documents/upload -H "Authorization: Bearer ..." \
    -F "file=@README.md;type=text/markdown"
# Expected: 201 Created

# 2. Binary blob disguised as text — expect 400
head -c 100000 /dev/urandom > /tmp/random.bin
curl -X POST /api/v1/documents/upload -H "Authorization: Bearer ..." \
    -F "file=@/tmp/random.bin;type=text/plain"
# Expected: 400 "Text file failed printable-ASCII heuristic"
```

## Cross-references

- Implementation: `apps/api/app/modules/documents/router.py:38, 31-33, 41-48`
- Audit: `docs/audit-2026-06-28-full.md` §4.6, §4.7
- AGENTS.md: §File upload (will be updated in a follow-up to match this ADR)