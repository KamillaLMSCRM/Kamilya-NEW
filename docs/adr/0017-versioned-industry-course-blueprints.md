# ADR-0017: Versioned industry course blueprints

- Status: accepted
- Date: 2026-08-07

## Context

Financial organizations need a useful starting point instead of an empty course
constructor. At the same time, a generic information-security course cannot
claim compliance with a tenant's current policies, contacts, systems or local
procedures. A second course lifecycle would duplicate review, release,
assignment and evidence behavior that already exists for native courses.

## Decision

Keep the reviewed, tenant-agnostic blueprint catalogue in code and instantiate a
selected version as a normal tenant-scoped native `Course` draft.

- The first catalogue item is `kz-finance-information-security` version
  `2026.1`, localized in Russian and Kazakh.
- `Course.source_analysis` stores the blueprint id/version/locale, adaptation
  answers, selected tenant documents, readiness and render hashes. No parallel
  tenant table or migration is introduced.
- The advertised 70/30 split is an explicit product estimate. The final 30%
  consists of eight required organization-specific checklist items.
- Only a methodologist or superadmin can instantiate or adapt the blueprint.
  Selected documents are checked against the active tenant.
- One active course per blueprint version and locale is allowed per tenant.
  Instantiation is serialized by locking the tenant row.
- Adaptation may rewrite generated blueprint text only while the course remains
  a draft and its structure/content hashes are unchanged. Manual edits move the
  remaining work to the normal course editor instead of being overwritten.
- Review approval is blocked until all required adaptation items are complete.
  Publication, immutable releases, assignments, attempts and evidence continue
  through the existing course lifecycle.

## Consequences

- Tenants receive an eight-lesson, sixteen-question starting course without an
  AI generation wait, but remain responsible for checking and approving it.
- Uploaded tenant documents are review sources; their selection does not imply
  that their text was automatically inserted or legally assessed.
- A blueprint update is a new explicit version. Existing drafts and published
  releases do not change silently.
- The catalogue remains easy to code-review and deploy for the initial small
  set. If the catalogue later needs non-developer editorial ownership, versioned
  persistence and approval governance will be designed as a separate change.
