# Assignment resource Unicode comparison V1.5

Status: Accepted bounded repair, 2026-10-15. Root/module owner: Root; product
owner: current user authorizing full DEV/production synthetic acceptance and repair.
Reviewer: independent source/evidence worker. Supersedes V1.4 only for the resource
comparison below; all dialogue, transport, tenant, preview and confirmation guards
remain unchanged. No new epic, state owner, API/schema or provider is introduced.

Live DEV53 passed model clarification/follow-up/correction, authoritative preview,
one confirmation, GET-only reload and learner access. Production53 returned
resource_not_found for the exact existing published synthetic course. Independent
runtime read proved exact title equality, current release present, datcollate=C,
and SQL lower(title) different from Python title.lower() for Cyrillic. The model
was responding correctly; this is a database-expression mismatch, not an outage.

Repair only create_assignment_preview's course/department equality predicates:
use lower(btrim(column) COLLATE "und-x-icu") compared with
lower(bound_query COLLATE "und-x-icu"). Never interpolate user names. ICU exists
on the target and its RU/KK lowercase behavior was independently probed. No global
locale, schema, normalized-column backfill, index or package/resource change.
Retain exact trimmed/case-insensitive equality, literal quoted-name priority,
one paired-quote fallback in candidate mode only, tenant/published/active/archive
predicates, ID ordering, LIMIT21, duplicate choices and selected-ID validation.
No fuzzy/substring search, Python catalogue scan, implicit audience widening,
model repair call, budget/route change, activation or email is authorized.

Write scope: assignment_service.py predicates, exact quoted-resource regressions,
owned DEV Unicode-check helper and its contract tests, existing intent gate call,
root version/changelog/release/error/readiness/index/plan documentation.
Negative space: enrollment/receipt transaction/idempotency/RLS, actor ownership,
existing completed learning, notification suppression, frontend protocol and
ChatGPT saved OFF remain unchanged. Voice remains deferred.

Gates: preserve real failed production receipt and RED2 unit tests; prove both
operand collations in SQL; execute actual service against owned C-collated cloned
course/department tables on canonical Supabase DEV, RU/KK case variants and quoted
fallback, runtime role/FORCE RLS/owned cleanup/public neutrality. Then focused
neighbors/full risk-based API/quality/exact CI, existing DEV release and real live
cycle, protected no-migration KZ API/three-worker release, exact readback and same
production synthetic cycle. Native frontend53 is protocol-compatible and need
not be rebuilt for this backend-only repair. Rollback53 remains additive/schema180
compatible. Do not change controller/permissions/topology to finish the repair.

Root accepts the immutable source and live evidence, not the presence of this
document. Stop on missing ICU, ambiguous fixture identity, incomplete cleanup,
unexpected scope, billing effect or rollback/readback failure.
