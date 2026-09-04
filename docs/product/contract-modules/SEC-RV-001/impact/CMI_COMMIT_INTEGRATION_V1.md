# CMI commit integration impact addendum V1

Status: Accepted
Approved by: Product owner via SEC-RV-001 approval on 2026-09-04

The existing attempt commit route validates through `CmiCommitPolicy` before changing
ORM fields. Supported flat SCORM 1.2 values retain merge/completion behavior. Previously
accepted unknown, nested, non-string or over-budget data now receives a stable 413/422
without mutation. Authorization, tenant/enrollment/package matching, response shape,
certificate issuance and isolated-origin requirements remain unchanged. Existing-data
inventory and any DB constraint require a later addendum.
