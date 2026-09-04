# Local MinIO credentials mini-spec

## Identity

| Field | Value |
|---|---|
| Module ID | `LOCAL-MINIO-CREDENTIALS` |
| Status | Accepted |
| Document version | V1 |
| Owning extension | `../EPIC_EXTENSION_CONFIG_HYGIENE_V1.md` |

## Responsibility and invariants

- No MinIO access/root credential value is embedded in tracked application or Compose
  configuration.
- Dead application credential settings are absent while there is no application MinIO
  client.
- Local Compose requires non-empty `MINIO_ROOT_USER` and `MINIO_ROOT_PASSWORD` values
  from the process environment or an untracked repository-root `.env` file.
- Credential values are never logged, copied into docs or added to test fixtures.
- Missing values fail before Compose creates or starts services.

## Verification and rollback

Contract tests scan the two tracked ownership points. Compose parsing must fail for
empty values and succeed for synthetic non-secret values. Rollback restores only code;
existing local volumes and operator-owned credentials are not read or modified.
