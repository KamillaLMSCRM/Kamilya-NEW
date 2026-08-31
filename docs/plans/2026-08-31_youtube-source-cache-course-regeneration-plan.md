# YouTube source cache and course regeneration implementation plan

**Created:** 2026-08-31
**Status:** PROPOSED
**Scope:** Kamilya LMS only
**Execution mode:** one gated step at a time; no production mutation from this plan

## 1. Purpose

This plan joins the previously agreed product decisions into one executable
sequence:

- a methodologist first receives a factual, very short YouTube preview and only
  then confirms import or course creation;
- the primary UI does not ask an ordinary HR employee to guess a module count;
- one course may be created from one document, multiple documents, or a
  YouTube transcript through the same source-analysis contract;
- repeated use of the same public YouTube source must not repeatedly fetch and
  normalize identical captions when a verified reusable revision exists;
- source acquisition may be shared internally, but tenant documents, prompts,
  courses, tests, edits, assignments, analytics, and learner results must never
  be shared across tenants;
- regenerating an old course under new generation rules creates a new draft
  edition and never silently rewrites a published course or its learner history;
- generated tests must not expose the correct answer through systematic answer
  length or other superficial patterns;
- a methodologist may ask the editor assistant for a bounded change, and those
  requests must be logged without source text or PII so recurring weaknesses can
  be measured and used to improve generation policies.

This plan refines, but does not replace:

- `docs/plans/2026-08-29_youtube-course-generation-plan.md`;
- `docs/plans/2026-08-29_youtube-preview-auto-course-structure-plan.md`;
- `docs/plans/2026-08-29_multi-document-course-generation-plan.md`.

## 2. Confirmed current behavior

The current implementation has useful tenant safety but no cross-tenant source
cache:

- YouTube analysis fetches and normalizes a transcript without creating a
  permanent `Document`;
- confirmation starts a separate import job using the canonical URL and
  preferred languages;
- import fetches the transcript again, so one ordinary preview-and-confirm flow
  can call the caption provider twice;
- import reuses an active `Document` only when the same
  `content_sha256` already exists inside the same tenant;
- jobs, documents, indexing, generation, and status reads are tenant-scoped;
- `TranscriptResult` already carries the main stable source identity:
  `video_id`, `canonical_url`, language, provider, retrieval time, and
  `content_sha256`.

The first optimization target is therefore not course reuse. It is reliable
source acquisition and revision reuse.

## 3. Non-negotiable architecture boundaries

### 3.1 What may be shared

Only a normalized immutable revision acquired from a genuinely public YouTube
source may be stored in the internal shared cache:

- canonical video identity;
- public caption track identity and language;
- manual or auto-generated caption classification;
- public title, channel, duration, and retrieval provenance;
- normalized transcript segments with timestamps;
- content hash and extractor/normalizer versions;
- freshness and availability state.

### 3.2 What must remain tenant-scoped

The following objects must never be shared across tenants:

- provisional analysis session and its user-visible status;
- the tenant `Document` and source assignment;
- uploaded, corrected, translated, or annotated transcripts;
- source bundles and generation settings;
- embeddings and active index revisions in the first implementation;
- generated course, modules, lessons, questions, answers, and citations;
- editor-assistant requests and previews;
- publication, assignment, learner progress, results, and certificates;
- audit records that identify a tenant actor or tenant object.

### 3.3 Access boundary

The shared source cache is an internal infrastructure table/object store prefix.
The normal application tenant role must not receive direct `SELECT`, object
storage access, or existence lookup against it. A trusted worker resolves a
shared revision and materializes an ordinary tenant-owned document.

The API must not reveal whether another tenant previously imported a URL. Cache
hit state is internal telemetry, not a tenant-visible cross-tenant fact.

## 4. Target data model

Names below are proposed and must be reconciled with existing model conventions
before migration authoring.

### 4.1 Internal public source revision

`youtube_public_source_revisions`:

| Field | Purpose |
|---|---|
| `id` | Opaque revision ID |
| `video_id` | Canonical YouTube video identity |
| `canonical_url` | Normalized URL without sensitive query data |
| `caption_track_key` | Stable provider track identity where available |
| `language` | Normalized caption language |
| `caption_kind` | `manual` or `auto_generated` |
| `title`, `channel`, `duration_seconds` | Public source metadata |
| `provider` | Acquisition adapter |
| `extractor_version` | Reproducible acquisition implementation version |
| `normalizer_version` | Reproducible normalized-text contract version |
| `content_sha256` | Immutable normalized transcript identity |
| `storage_key` | Internal encrypted object reference |
| `retrieved_at` | First successful acquisition time |
| `last_validated_at` | Last successful source revalidation |
| `fresh_until` | Time before revalidation is required |
| `availability_status` | Current technical status without tenant data |

An immutable revision uniqueness contract should cover at least:

```text
video_id + language + caption_track_key + content_sha256 + normalizer_version
```

An active-head lookup may point from
`video_id + language + caption_track_key` to the latest verified immutable
revision. A changed transcript creates a new revision; it never mutates the old
revision in place.

### 4.2 Tenant import/materialization

`youtube_tenant_imports`:

| Field | Purpose |
|---|---|
| `id` | Tenant-visible import operation ID |
| `tenant_id` | Mandatory ownership boundary |
| `requested_by` | Authorized methodologist |
| `source_revision_id` | Internal resolved public revision reference |
| `original_url_fingerprint` | Non-reversible correlation, not a raw log URL |
| `preferred_language` | User choice |
| `document_id` | Tenant-owned materialized document |
| `analysis_job_id`, `import_job_id` | Tenant-scoped job lineage |
| `status` | Provisional/imported/failed/expired state |
| `expires_at` | Cleanup boundary for provisional state |
| timestamps | Auditable lifecycle |

This table requires `tenant_id`, ownership checks, RLS, FORCE RLS, a runtime
role without `BYPASSRLS`, and cross-tenant tests.

### 4.3 Generation lineage

Every generation or regeneration run must persist enough provenance to explain
which rules and source revisions produced it:

```text
source_bundle_revision_id
generation_policy_version
prompt_contract_version
model_provider
model_name
model_revision when available
course_format
manual_module_override when used
parent_course_id or parent_course_version_id
generation_reason
created_by
created_at
```

Model/provider fields are operational provenance. They must not contain secrets,
tokens, raw prompts, or tenant source content.

## 5. Target request flow

### 5.1 Preview

```text
methodologist submits URL
  -> allowlisted URL resolver returns canonical video ID
  -> tenant quota and rate-limit preflight
  -> internal source-cache lookup
  -> fresh hit: read verified immutable revision
  -> miss/stale: acquire one provider lock and fetch captions once
  -> normalize, validate, hash, and persist immutable revision
  -> create tenant-scoped provisional analysis result
  -> show factual 1-2 sentence preview, language, duration, caption quality,
     key topics, warnings, and recommended course format
```

The preview screen must not create a permanent `Document`. It must show the
destination action only after a real transcript was obtained and validated.

Primary action: `Создать курс из видео`.
Secondary action: `Сохранить субтитры в документы`.

### 5.2 Confirmation

```text
methodologist confirms action
  -> lock tenant analysis row
  -> reject expired, reused, or incomplete confirmation
  -> reuse the exact already resolved source revision
  -> materialize one tenant Document idempotently
  -> enqueue ordinary indexing
  -> wait for verified active index revision
  -> run the existing course-generation pipeline
```

Confirmation must not call YouTube again merely because it is a separate job.

### 5.3 Two tenants request the same source concurrently

```text
tenant A requests video X / language RU
tenant B requests video X / language RU
  -> both miss durable cache
  -> A obtains internal single-flight lock
  -> B joins/waits on the source-acquisition operation
  -> provider is called once
  -> one immutable public source revision is stored
  -> A receives tenant import A and document A
  -> B receives tenant import B and document B
  -> indexing, generation, courses, tests, and analytics remain separate
```

No shared lock, job, status, or cache metadata may expose tenant A to tenant B.

## 6. Cache, freshness, and failure policy

Initial configurable defaults:

| State | Initial policy |
|---|---|
| Verified public captions | Fresh for 24 hours, then revalidate on a new request |
| Immutable revision referenced by tenant objects | Retain while referenced and under retention policy |
| No transcript found | Negative cache 15 minutes |
| Provider blocked or rate-limited | Short exponential backoff, initially 5 minutes |
| Deleted/private/unavailable source | Cache classification for 1 hour, allow safe manual retry later |
| Provisional tenant preview | Expire after 30 minutes |

These values are launch defaults, not permanent product constants. They must be
configuration-backed and adjusted from provider reliability and hit-rate data.

Failure rules:

- no unbounded automatic retry;
- no residential proxy or provider restriction bypass;
- no stale cache entry silently presented as freshly validated;
- a cache outage falls back to one bounded provider attempt only if the normal
  provider circuit is healthy;
- a provider failure must not break ordinary document upload or other AI jobs;
- negative cache entries never become tenant documents;
- unavailable or changed source state never rewrites an existing published
  course.

## 7. Course structure UX

The primary form must replace raw `module_count` with a meaningful course
format:

| Format | User meaning |
|---|---|
| `automatic` | Kamilya recommends structure from source size and semantic boundaries |
| `brief` | Short introduction with only essential material |
| `standard` | Normal working course with explanations and checks |
| `detailed` | Extended course for complex or regulated material |

`automatic` is the default. The backend recommendation uses source duration,
normalized character count, semantic topic boundaries, expected learning time,
lesson density, and assessment density.

Manual module count remains under `Расширенные настройки`. It is optional,
explained as an override, bounded by server validation, and may produce a warning
when it conflicts with source size. It is never required from an ordinary HR
employee.

The same format contract applies to:

- one document;
- multiple documents in one source bundle;
- a YouTube transcript materialized as a tenant document;
- regeneration of an existing draft or creation of a new edition.

## 8. Regenerating an old course from the same source

The methodologist must see an explicit action:

`Создать новую редакцию по этим материалам`.

The next screen must offer two source choices:

- `Использовать те же версии источников` for reproducible regeneration under a
  newer generation policy;
- `Проверить обновления источников` to create a new source bundle revision when
  a document or YouTube transcript changed.

The new run must:

- create a new draft edition;
- preserve the old published course, assignments, attempts, results, and
  certificates;
- record parent lineage and the exact source bundle revision;
- show the generation-policy version and generation date;
- allow a structured comparison before publication;
- never replace an old published version silently;
- require normal methodologist review and publication.

For an unpublished draft, the UI may additionally offer `Пересобрать текущий
черновик`, but it must warn that unsaved draft edits will be replaced. Published
content always uses a new edition.

## 9. Multi-document source bundle

One course generated from several documents must pin an immutable ordered
manifest:

```text
document_id
active_source_revision_id
content_sha256
display_order
detected_language
source_role
```

The backend must validate before accepting generation:

- all documents belong to the current tenant;
- all selected revisions are active and fully indexed;
- the configured document-count and aggregate-size limits are respected;
- duplicate source revisions are removed deterministically;
- mixed languages require an explicit methodologist choice;
- conflicting or low-quality sources produce a review warning;
- the request fingerprint is stable and concurrency-safe;
- the same source bundle and settings cannot create duplicate jobs through a
  repeated click or concurrent submission.

The YouTube source becomes an ordinary tenant document after confirmation and
therefore participates in this same bundle contract rather than creating a
second RAG pipeline.

## 10. Assessment quality improvements

Each generated assessment question must preserve evidence provenance and pass a
deterministic validation layer before it becomes an editable draft.

Required checks:

- the correct answer is supported by a cited source fragment;
- every distractor is plausible in the same semantic category;
- distractors are not contradicted by wording artefacts alone;
- options use comparable grammatical form and level of detail;
- the correct answer is not systematically the only longest, most specific, or
  professionally worded option;
- `all of the above`, obvious negation tricks, and answer-position patterns are
  rejected unless explicitly allowed by a future policy;
- duplicate or near-duplicate options are rejected;
- names, dates, amounts, limits, and regulated statements require stronger
  evidence checks;
- the question language matches the confirmed course language.

The synthetic RU/KK/EN benchmark must report at least:

```text
evidence coverage
unsupported answer rate
duplicate option rate
correct-answer position distribution
correct-answer unique-longest rate
manual reviewer acceptance rate
generation latency and provider/model route
```

The `correct-answer unique-longest rate` is a warning metric, not a substitute
for semantic validation. Initial release review should reject a benchmark where
length alone becomes a useful answer strategy.

## 11. Editor assistant and improvement telemetry

The methodologist may request bounded edits such as:

- `Добавь больше информации в третий вопрос`;
- `Предложи другие варианты ответов`;
- `Сделай неверные ответы правдоподобнее`;
- `Упрости объяснение урока`;
- `Раздели этот урок на два`.

The assistant must operate on an explicit selected object and return a preview.
Nothing is applied automatically. The user accepts or rejects the proposed
patch, and normal course validation runs again after acceptance.

Telemetry must store structured, PII-free categories rather than raw source
text or unrestricted user prompts:

```text
tenant_id or approved pseudonymous tenant key
actor_role
object_type
operation_category
reason_category when selected
generation_policy_version
model route
preview_created
accepted or rejected
validation_result
latency
created_at
```

Permitted aggregate categories include:

```text
add_detail
rewrite_lesson
split_or_merge_structure
replace_distractors
fix_correct_answer
fix_language
fix_source_grounding
fix_tone
other
```

Raw prompts may be retained only under a separately reviewed privacy and
retention policy. The default analytics path must not require them.

This telemetry is used to identify recurring generation defects. It does not
automatically modify prompts, skills, policies, models, or production behavior.
Any policy change requires reviewed code/configuration, benchmark comparison,
versioning, and a release gate.

## 12. Observability

Add low-cardinality technical metrics without raw URL, transcript, PII, tenant
payload, or credentials:

```text
youtube_source_cache_hit_total
youtube_source_cache_miss_total
youtube_source_singleflight_join_total
youtube_source_fetch_duration_ms
youtube_source_fetch_failure_total{classification}
youtube_source_revision_changed_total
youtube_tenant_materialization_duration_ms
youtube_index_duration_ms
course_generation_duration_ms{format,provider_route}
course_regeneration_total{reason}
assessment_validation_failure_total{classification}
editor_assistant_request_total{operation_category,outcome}
```

Job/audit records may retain opaque IDs for incident correlation, but ordinary
logs must not contain the submitted URL, transcript, user prompt, learner data,
or cross-tenant cache details.

## 13. Security and tenancy test matrix

Required automated cases:

| Area | Required result |
|---|---|
| URL resolver | Only supported YouTube HTTPS hosts and forms; SSRF/private targets rejected |
| Tenant import | Tenant B cannot read, confirm, cancel, or reuse tenant A import ID |
| Shared cache | Application tenant role has no direct table/object access |
| Cache side channel | API response does not reveal another tenant's cache/import history |
| Concurrent same tenant | One import/document and deterministic idempotent response |
| Concurrent different tenants | One provider acquisition, two isolated tenant imports/documents |
| Changed transcript | New immutable source revision; old course remains unchanged |
| Expired preview | Confirmation rejected; no document or generation job created |
| Replayed confirmation | Exactly one materialization/generation path |
| Uploaded/private transcript | Never enters the shared public cache |
| RLS | FORCE RLS and ownership checks cover every tenant-scoped table/mutation |
| Logging | No URL, transcript, prompt, PII, token, or tenant payload leakage |
| Resource abuse | Per-tenant quotas, duration/size limits, bounded retries and concurrency |

## 14. Delivery sequence

Only one step is implemented and reviewed at a time. A later step does not
start because an earlier agent merely reported success.

| ID | Step | Main result | Gate |
|---|---|---|---|
| YSC-00 | Contract and source audit | Reconcile this plan with actual schema, jobs, storage, roles, and current migrations | Root source review; no mutation |
| YSC-01 | Remove preview/import double fetch | Tenant-scoped temporary artifact or exact immutable source revision reused by confirmation | Unit and integration tests prove one provider call |
| YSC-02 | Shared public-source revision store | Additive schema, internal storage prefix, retention and grants | Migration/RLS/grant/security review |
| YSC-03 | Single-flight acquisition | Concurrent requests share one bounded provider acquisition | Deterministic concurrency tests |
| YSC-04 | Tenant materialization | Each tenant receives its own ordinary document and index path | Cross-tenant and idempotency tests |
| YSC-05 | Preview and automatic format UX | Short factual preview; import button only after success; no primary module-count decision | Frontend tests and methodologist browser E2E |
| YSC-06 | Source bundle and regeneration lineage | New draft edition from pinned same or refreshed sources | Migration, API, and published-history regression tests |
| YSC-07 | Assessment quality gate | Evidence-bound questions and reduced answer-pattern leakage | RU/KK/EN benchmark and reviewer rubric |
| YSC-08 | Editor assistant telemetry | Bounded preview/apply flow and PII-free structured categories | API/frontend tests and privacy review |
| YSC-09 | Disposable full E2E | URL -> preview -> import -> index -> draft -> tests -> publish -> learner | Non-production exact-SHA evidence |
| YSC-10 | Dev canary | Feature-flagged deployment and one public-safe synthetic source | Runtime, worker, DB, storage, and browser readback |
| YSC-11 | Production release packet | Exact SHA, migrations, flags, rollback and acceptance packet | Separate current owner authorization |
| YSC-12 | Production canary | One authorized public-safe source with bounded monitoring | Separate action-time approval and independent readback |

## 15. Agent allocation

Cheap agents may prepare narrowly scoped tests, UI copy variants, migration
contract tests, benchmark fixtures, and documentation. Every delegated prompt
must be English-only and include exact read/write scope, no Git/push/deploy,
stop conditions, and required evidence.

Root orchestrator retains ownership of:

- architecture and tenancy boundaries;
- schema/grant/RLS integration;
- concurrency and idempotency contract;
- final diff review;
- benchmark interpretation;
- exact-SHA release packet;
- production authorization and acceptance decision.

No agent report is accepted as runtime evidence without independent root
readback.

## 16. Rollout controls

Feature flags should permit independent shutdown of:

```text
YouTube URL import
shared public-source cache reads
shared public-source cache writes
automatic course-format recommendation
editor assistant
```

Safe rollback behavior:

- stop new YouTube acquisitions;
- retain existing immutable source revisions and tenant documents;
- fall back to uploaded SRT/VTT/TXT and ordinary documents;
- never delete published courses or learner history;
- disable shared-cache use without making tenant documents unreadable;
- keep old generation-policy versions readable;
- do not downgrade destructive migrations; use additive/expand-compatible
  schema and a separately reviewed cleanup phase.

## 17. Acceptance criteria

The epic is ready for a bounded production release only when all statements are
verified on an exact SHA:

1. Preview plus confirmation performs no duplicate caption-provider call for
   the same resolved source revision.
2. Two simultaneous tenants requesting the same public video/language cause one
   provider acquisition and two isolated tenant documents.
3. The tenant application role cannot read the shared cache directly.
4. No API response leaks whether another tenant used a source.
5. Confirmation is expiring, single-consumption safe, replay-resistant, and
   idempotent.
6. A changed transcript creates a new immutable revision and never silently
   changes a published course.
7. The default methodologist flow requires course format, not module count.
8. One-document, multi-document, and YouTube generation use the same source
   bundle and recommendation contract.
9. Regeneration creates a new draft edition with complete source and policy
   lineage while preserving learner history.
10. Assessment benchmarks show evidence grounding and no practically useful
    correct-answer length/position shortcut.
11. Editor-assistant requests are previewed before apply and produce structured,
    retention-controlled telemetry without raw source content by default.
12. Public-caption cache failure does not break ordinary document upload,
    indexing, or generation.
13. Full methodologist and learner E2E passes on the target environment.
14. Release evidence identifies exact SHA, image, migration head, worker
    identity, feature flags, rollback target, and post-release business smoke.

## 18. Immediate next step

Execute `YSC-00` as a read-only source and schema reconciliation. Its output must
be a compact claim table with `VERIFIED`, `PARTIALLY VERIFIED`, or `BLOCKED` for:

- current double-fetch behavior;
- current tenant-only document reuse;
- current temporary analysis persistence;
- current storage and cleanup behavior;
- current runtime DB roles and grants;
- the exact additive migration head available for `YSC-02`;
- existing course/source version lineage;
- existing assessment validator and editor-assistant telemetry seams.

Only after root review of that evidence should `YSC-01` receive an implementation
write scope.
