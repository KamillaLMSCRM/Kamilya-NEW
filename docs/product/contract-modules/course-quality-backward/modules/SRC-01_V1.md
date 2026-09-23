# SRC-01: сохранение учебных секций (V1)

Status: Accepted for local synthetic verification. Template: V2. Approved by: product owner (four seams, 2026-09-23). Change control: root proposes/reviews versioned addendum; owner approves material business or release changes.

Responsibility: classify parsed sections and return a source document retaining teachable narrative and separating reference-only sheets. Non-responsibilities: writing lessons, questions, provider calls, persistence and UI. User-visible contribution: neither a one-paragraph course disappears, nor SKU catalog becomes extra lessons.

External interface: `build_evidence_source(DirectSourceCorpus) -> EvidenceSourceBundle.document: SourceDocument`; upstream `build_document_passport(corpus) -> DocumentPassport` provides section roles. Input is already converted, revision-bound tenant corpus; output preserves source locators and roles. Stateless; repeated input returns equivalent roles and facts. Errors: missing/invalid corpus fails closed; uncertain values are not guessed. No network or DB side effects; performance remains bounded by existing corpus chunk budgets.

Data ownership: immutable in-memory derived source; original bytes and tenant records remain with Document Ingestion. Tenant/revision identity in locators must remain unchanged. No PII in fixtures or diagnostics. Dependencies: existing passport and source chunking; test adapter is a synthetic `DirectSourceCorpus`. Forbidden: route, DB, auth, Celery, provider, migration, legacy generation edits.

Invariants: one meaningful narrative section is primary even when its heading equals the file title; a title-only preamble in a multi-section document remains supporting; a named SKU/reference sheet with stronger reference than learning signals stays supporting beside a primary learning sheet; no row becomes an unsupported fact.

Verification: red/green `tests/unit/test_backward_quality_corpus.py`; existing document passport, direct-source and evidence application tests; `AI-COURSE-01` before release. Read scope: AI source map and existing tests. Write scope: `document_passport.py`, `evidence_engine/application.py`, new synthetic tests/fixtures and this contract only. Stop on changed lesson/question interface, customer data, provider billing or unplanned module impact. Done when focused and neighboring tests pass, source provenance stays intact, and graph update shows no unexpected dependency.
