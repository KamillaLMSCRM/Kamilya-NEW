# SEC-RV-001 Python supply-chain extension V1

## Identity and authority

| Field | Value |
|---|---|
| Extension | Python dependency vulnerability gate |
| Status | Accepted |
| Supersedes | `EPIC_V1.md` Python-SCA exclusion only |
| Approved by | Product owner via security-plan continuation on 2026-09-04 |
| Production authority | Not granted |

## Scope

Upgrade the vulnerable locked Python dependencies identified by `pip-audit` and add a
blocking CI audit derived from the exact Poetry production graph. No advisory is ignored
and the gate cannot be marked non-blocking. Application behavior changes only through
the reviewed dependency upgrades.

Container base-image/package scanning, JavaScript SCA, GitHub settings, provider state
and production rollout remain outside this extension.
