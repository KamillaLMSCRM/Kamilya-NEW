# Local MinIO credential integration impact addendum V1

Status: Accepted
Approved by: Product owner via security-plan continuation on 2026-09-04

`Settings` no longer exposes unused MinIO access-key and secret-key defaults. The local
Compose MinIO service now receives both root values through required interpolation.
Developers with existing untracked environment values retain their own credentials;
new environments must supply unique values before `docker compose up`.

Application storage remains `local` or `supabase`; no storage backend, provider,
database, volume or production configuration changes in this packet.
