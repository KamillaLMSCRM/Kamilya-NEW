# Python dependency audit mini-spec

## Identity

| Field | Value |
|---|---|
| Module ID | `PYTHON-DEPENDENCY-AUDIT` |
| Status | Accepted |
| Document version | V1 |
| Owning extension | `../EPIC_EXTENSION_SUPPLY_CHAIN_V1.md` |

## Responsibility and interface

The Dockerfile install and CI export both use explicit
`--with observability --without dev` selectors from `poetry.lock`,
matching the production-image graph (`main + observability`),
and passes that exact graph to pinned `pip-audit==2.10.1`. The internal editable
monorepo package is skipped because it has no package-index identity; all third-party
image dependencies remain audited.

## Invariants

- The audit job is blocking and contains no `continue-on-error`, `|| true` or advisory
  ignore list.
- `poetry-plugin-export` and `pip-audit` tool versions are pinned.
- The lock is the production-image dependency authority; loose Render development
  requirements retain patched minimum versions but are not release identity evidence.
- Vulnerability data is time-dependent, so every CI run re-queries the advisory service.
- A future advisory fails CI until the dependency is upgraded or a separately reviewed,
  time-bounded exception contract is explicitly approved.

## Current compatibility evidence

The upgraded graph includes modern FastAPI/Starlette, multipart, PDF, JSON-repair,
cryptography and SMTP dependencies. The pytest toolchain is also upgraded so the full
local/CI environment audits cleanly. Backend unit and focused auth/PDF/email/upload
regressions must pass after lock changes. The tenant SMTP probe has hermetic success
and failure-path tests against the real `aiosmtplib.send` call seam; transport exception
details are not returned to clients or persisted in tenant audit metadata.

## Rollback

Rollback cannot restore a known-vulnerable lock as a release candidate. If an upgrade
causes a functional regression, hold the release and prepare a reviewed compatible fix;
do not disable the gate or ignore the advisory by default.
