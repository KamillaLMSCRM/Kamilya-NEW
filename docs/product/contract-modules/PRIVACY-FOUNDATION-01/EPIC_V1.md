# PRIVACY-FOUNDATION-01 — Central processing decisions and evidence

| Field | Value |
|---|---|
| Status | Accepted |
| Version | V1 |
| Approved by | Kamilya owner, 2026-09-29 |
| Root owner | Codex root agent |
| Product owner | Kamilya owner |
| Reviewer | Root final-diff review |

## Observable outcome

Every covered employee, team-member and training-report operation receives one
deterministic privacy decision and, after success, one tenant-scoped value-free
processing record committed with the business transaction.

## Critical journeys

1. Admin creates, changes, deactivates or resets a tenant team account.
2. Methodologist edits or terminates an employee and previews/commits staff
   import.
3. Authorized role exports employees, enrollments or quiz results.
4. Unknown operation or unauthorized role fails closed before a ledger write.
5. Runtime role cannot update or delete ledger rows.

## Exclusions

- Public or contractual compliance claims.
- Customer operating restrictions or document-upload instructions.
- Provider, billing, DNS, deployment and infrastructure changes.
- UI changes, masking adapters, retention automation and external reporting.

## Module map

```text
users/admin adapters
  -> privacy_control.evaluate_processing
  -> privacy_control.record_processing
  -> audit.log_action
  -> audit_logs (RLS/FORCE RLS, runtime append-only)
```

## Impact matrix and negative space

| Module | Impact | Required unchanged behavior |
|---|---|---|
| users router | Consumer | Existing RBAC, payloads, responses and welcome delivery |
| staff import router | Consumer | Preview/commit, hierarchy and rule application |
| admin exports | Consumer | CSV columns, encoding and role boundaries |
| audit | Invariant | Tenant RLS, superadmin context and bounded tenant purge |
| auth/session | None | Tokens, sessions and login flows |
| AI generation | None | Provider routing and document generation |

## Acceptance

- Pure policy tests cover allowed and fail-closed outcomes.
- Supabase DEV integration proves business mutation/export and ledger record.
- Migration contract and isolated database gate prove runtime append-only grants.
- Graphify post-change comparison shows only accepted adapter dependencies.
- No DEV or production release is part of V1 implementation acceptance.

## Mandatory implementation register

Every later change related to the 2026 personal-data protection or
masking/hashing requirements must update
`docs/legal/kazakhstan-2026-personal-data-implementation-register-ru.md` in the
same commit. The update records the requirement ID, implementation status,
tests, release SHA/environment, readback evidence and the boundary of any
future customer-facing statement.
