# SEC-RV-001 runtime-hardening extension V1

## Identity and authority

| Field | Value |
|---|---|
| Extension | API runtime identity and release-compose confinement |
| Status | Accepted |
| Supersedes | `EPIC_V1.md` exclusion of container identity only |
| Approved by | Product owner via security-plan continuation on 2026-09-04 |
| Production authority | Not granted |

## Scope

This extension adds source-level remediation for audit finding A-03. The API image
runs as fixed UID/GID `10001:10001`; application bytes and the virtual environment
remain root-owned. KZ API/worker release services repeat that identity, make the root
filesystem read-only, provide a bounded writable `/tmp`, drop all Linux capabilities
and enable `no-new-privileges`.

No provider, host, database, tenant, secret or live deployment state may be changed.
MinIO credentials, dependency SCA and other audit findings remain separate packets.

## Release boundary

Before any deployment, the operator must prove that the exact immutable image starts
as UID/GID 10001 under the release Compose files and that the configured certificate
bind mount is writable by that identity without broadening host permissions. API health,
all worker queues, Celery beat state under `/tmp`, document/certificate writes and
rollback to the exact prior image are required critical journeys.

Docker daemon unavailability is reported as NOT VERIFIED and cannot be replaced by
static Dockerfile or Compose parsing evidence.
