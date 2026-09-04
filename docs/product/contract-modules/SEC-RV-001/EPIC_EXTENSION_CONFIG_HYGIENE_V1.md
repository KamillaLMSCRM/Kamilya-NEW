# SEC-RV-001 configuration-hygiene extension V1

## Identity and authority

| Field | Value |
|---|---|
| Extension | Local MinIO credential ownership |
| Status | Accepted |
| Supersedes | `EPIC_V1.md` exclusions for audit finding A-05 only |
| Approved by | Product owner via security-plan continuation on 2026-09-04 |
| Production authority | Not granted |

## Scope

Remove repository-known MinIO credentials from application defaults and local Compose.
The application currently has no MinIO credential consumer, so dead credential settings
are removed instead of made globally mandatory. Local Compose owns its root credentials
and fails interpolation when either operator-supplied value is absent or empty.

Provider credentials, object-store migration, MinIO image pinning, production storage,
billing and live environments are outside this extension.
