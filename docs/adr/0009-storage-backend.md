# ADR-0009: Storage backend — Supabase Storage (prod) + local MinIO (dev)

- **Status:** Accepted
- **Date:** 2026-06-28
- **Context:** AGENTS.md §Storage, audit §Phase 1

## Decision

We abstract document storage behind a `Storage` interface so the same
code path works against Supabase Storage (production) and MinIO
(local dev). The choice between backends is governed by the
`STORAGE_BACKEND` env var.

### Backends

**Production: Supabase Storage**
- Bucket: `Kamilya LMS` (Supabase allows spaces in bucket names; the
  supabase-py client handles URL-encoding internally).
- Region: eu-central-1 (Frankfurt), co-located with the DB and
  Render backend.
- Signed URLs for time-limited read access (TTL: 5 min default).
- Service-role credentials (`SUPABASE_KEY`) used; never user JWTs.

**Development: MinIO**
- S3-compatible, runs in docker-compose.
- Same signed-URL semantics for development parity.

### Storage key format

```
tenants/{tenant_id}/{server-generated-uuid}
```

Server-generated UUID, never derived from filename. This is mandated
by AGENTS.md §File upload ("Storage key = server-generated UUID (не
user-provided filename)") and prevents two uploads with the same
filename from clobbering each other.

### Encryption-at-rest

- **Supabase Storage:** AES-256 server-side encryption enabled by
  default on the Supabase project. Per-object keys managed by
  Supabase; rotated quarterly by Supabase.
- **MinIO:** AES-256 server-side encryption can be enabled via
  `MINIO_KMS_AUTO_KEY` env var (not configured in docker-compose —
  dev data is non-sensitive).

### Signed URL flow

When a user requests document download:
1. Server validates user has read access to the document
   (tenant-scoped).
2. Server calls `storage.get_signed_url(key, ttl=300)`.
3. Client receives a 5-minute URL and can `GET` it directly.

The signed URL itself is HMAC-signed by the storage backend; the
proxy server doesn't see the actual document bytes for download
(saves egress on the backend).

### Lifecycle / cleanup

- Documents in `failed` embedding status for >30 days are flagged
  for cleanup by a Celery beat task (deferred to v1.1).
- Soft-delete via `Document.embedding_status='deleted'` first, then
  physical delete after 30 days. v1.0 only does soft-delete.

## Alternatives considered

- **AWS S3 directly.** More flexible but adds AWS account dependency
  for the team. Supabase Storage is "good enough S3" with simpler
  IAM and is already part of the Supabase bill.
- **Local filesystem only.** Fastest dev experience but doesn't
  replicate production. MinIO chosen for S3 parity.
- **CDN in front of Supabase Storage.** Cloudflare in front of
  Supabase signed URLs adds latency and complexity. Acceptable for
  v1.1 if performance data shows the bottleneck.

## Open items

- **Tenant-scoped bucket per tenant** (instead of one shared bucket
  with tenant-prefixed keys). Would simplify access control but
  multiplies bucket count. Defer until >100 tenants.
- **Direct browser upload** (bypass backend for large files). Adds
  complexity; current max file size is 10 MB so not worth it.