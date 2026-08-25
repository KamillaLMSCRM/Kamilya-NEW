# Karcher synthetic production rehearsal

Date: 2026-08-25. Meeting: 2026-08-27 10:00 GMT+5, online.

## Authority and safety boundary

- `OWNER-CONFIRMED`: execute one node at a time and independently read back its
  result before starting the next node.
- Scope is one synthetic `is_demo=true` production tenant. Never modify Sandyk,
  real employees, other tenants, global objects, CT125 configuration or provider
  settings.
- Use synthetic names and addresses only. Do not send email or notifications.
- Never record credentials, personal access URLs, PINs, tokens, document text or
  other payload data in Git, logs or reports.
- Current production release is
  `d17a9206086d8557f797a13563353c406d0ce9f4`; VM126 uses image
  `kamilya-api:d17a9206086d`, and Alembic is `0131 (head)`.

## Active task graph

| ID | Objective | Owner / writer | Dependencies | State | Exit gate | Evidence | Approval / cleanup |
|---|---|---|---|---|---|---|---|
| KDP-00 | Promote and verify document-upload fix | Root; VM126 single writer | CI | DONE | Exact SHA on API/workers; health, Alembic and watchdog pass | `GIT-DERIVED`, `RUNTIME-DERIVED` | Owner approved; rollback `760eeb72...` retained |
| KDP-01 | Production preflight | Root; read-only | KDP-00 | PENDING | Health/image/worker/DB/backup gates pass; target slug absent | `RUNTIME-DERIVED` | No new approval; no cleanup |
| KDP-02 | Create synthetic demo tenant as superadmin | Root; tenant single writer | KDP-01 | PENDING | One `is_demo=true` tenant with exact slug; no invite/email | `RUNTIME-DERIVED`, `OWNER-CONFIRMED` | Already authorized; tenant enters guarded cleanup manifest |
| KDP-03 | Import synthetic structure | Root; tenant single writer | KDP-02 | PENDING | Preview `4 create / 0 update / 0 invalid`; 2 departments, 4 users, 4 positions; no delivery | `RUNTIME-DERIVED` | Stop on any count mismatch; cleanup remains tenant-scoped |
| KDP-04 | Add common course bases and source document | Root; tenant single writer | KDP-03 | PENDING | Three blueprint version `2026.1` instances; one indexed synthetic DOCX with tenant/blob/job parity | `RUNTIME-DERIVED` | One upload only; stop on duplicate, storage or tenant mismatch |
| KDP-05 | Generate and review role onboarding course | Root; tenant single writer; owner reviews content | KDP-04 | PENDING | One terminal AI job; provenance and content review pass; draft remains unpublished until approval | `RUNTIME-DERIVED`, `OWNER-CONFIRMED` | Never replay blindly; reject unsupported claims |
| KDP-06 | Publish and assign | Root; tenant single writer | KDP-05 | PENDING | Approved immutable releases; common courses assigned to four users; role course to KD-003; no email | `RUNTIME-DERIVED` | Publication stops on incomplete review |
| KDP-07 | Complete learning and obtain certificate | Root; one synthetic learner session | KDP-06 | PENDING | KD-003 completes course/test; admin readback confirms score, completion and certificate | `RUNTIME-DERIVED` | Access URL/PIN process-local only and revoked after use |
| KDP-08 | Final verdict and retained-demo decision | Root | KDP-07 | PENDING | `GO`, `CONDITIONAL GO` or `NO-GO` with exact non-PII evidence and cleanup manifest | `RUNTIME-DERIVED`, `OWNER-CONFIRMED` | Keep tenant through meeting only on GO; deletion needs guarded manifest |

## Exact artifacts

- Tenant name: `Керхер — демонстрация 27.08.2026`.
- Tenant slug: `synthetic-karcher-demo-prod-20260827`.
- Staff file:
  `outputs/01a022ec-ef66-7ac1-8f33-e7e3faec698f/karcher-demo-2026-08-27/karcher-demo-staff-import.xlsx`.
- Role source:
  `outputs/01a022ec-ef66-7ac1-8f33-e7e3faec698f/karcher-demo-2026-08-27/karcher-demo-service-engineer-role-source.docx`.
- Detailed dev rehearsal and content assumptions:
  `outputs/01a022ec-ef66-7ac1-8f33-e7e3faec698f/karcher-demo-2026-08-27/karcher-demo-runbook-2026-08-27.md`.

## Stop conditions

Stop the current node without attempting the next one on any release, image,
worker, database, backup or tenant mismatch; existing slug; unexpected email;
import count other than `4/0/0`; cross-tenant visibility; failed indexing;
unsupported generated content; duplicate generation; publication before review;
or any request to use real personal data.

## Controlling production outcome - 2026-08-25

This section supersedes the earlier draft status table for the Karcher rehearsal.

| Node | State | Evidence / remaining gate |
|---|---|---|
| KDP-01 Exact release and CI | DONE | GIT-DERIVED / PROVIDER-CONFIRMED: release `67477ed5a9fabed92e1bd4805c263697a14826d0`; GitHub Actions run `32849094899` passed all frontend, backend, PostgreSQL 17 + pgvector/RLS, secrets, quality and release gates. |
| KDP-02 Production tenant | DONE | RUNTIME-DERIVED: tenant `bf5bb4a5-a473-4a0e-a649-c578d26f4be9` is retained for the 2026-08-27 demonstration. |
| KDP-03 Organization structure | DONE | RUNTIME-DERIVED: exactly 2 branches (`Филиал Павлодар`, `Филиал Петропавловск`), 0 legacy roots, 4 positions and 4 employees. The adaptive import defect was repaired by a guarded tenant-scoped transaction after preserving all employee links. |
| KDP-04 Common content | DONE | RUNTIME-DERIVED: information-security, occupational-safety and fire-safety courses are published and assigned; the source document embedding is successful. |
| KDP-05 Live AI generation | BLOCKED | RUNTIME-DERIVED / BLOCKED: the production Qwen provider pool was unavailable. No provider was enabled and no uncontrolled retry was performed. |
| KDP-06 Role onboarding course | DONE VIA FALLBACK | RUNTIME-DERIVED: deterministic manual role-course fallback is published and assigned to KD-003; active assignment total remains 13. |
| KDP-07 Learner journey and certificate | DONE | RUNTIME-DERIVED: link exchange, 6 lessons, quiz, 100% progress, completion and certificate download passed in production. Certificate PDF SHA-256: `17270D9854992B02FEEEE0FB3EB3A79A2375C1ACE144631E409915A7091CD5F0`. |
| KDP-08 Demo decision | CONDITIONAL GO | OWNER-CONFIRMED / RUNTIME-DERIVED: the prepared production tenant is usable for the client demonstration. Live AI generation remains unavailable; use the published fallback course during the session. |

Additional runtime evidence:
- Public and private runtime identity matched release `67477ed5a9fabed92e1bd4805c263697a14826d0`; API and all three worker containers used `kamilya-api:67477ed5a9fa`, with zero restarts after deployment.
- Production organization readback after repair: branches 2, legacy roots 0, positions 4, employees 4, active enrollments 13, completed course assignments 1.
- A real tenant-scoped methodologist account was created on the authorized service mailbox and its email-code login was verified. Credentials and OTP were not recorded in Git or logs.
- Temporary release archives, build directories and operator scripts were removed after successful readback. The tenant and its business-demo artifacts are intentionally retained until a separately approved cleanup.
