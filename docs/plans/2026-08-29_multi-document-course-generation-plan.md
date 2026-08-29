# Multi-Document Course Generation — Vertical Slice Plan

Experiment: `KAMILYA-MULTIDOC-GLM53-01` · Date: 2026-08-29 · Branch: `master` @ `a4438bc`

## 1. Current architecture (confirmed from source)

### UI
- `apps/web/src/app/ai/generate/page.tsx` — single generation page. Already supports
  multi-select: `selectedDocIds` array, cap 20 in `toggleDoc` (line ~341), blocks
  selection of documents with `embedding_status !== 'success'`, runs
  `POST /v1/ai/document-compatibility` debounced (350 ms) and renders thematic
  cluster UI (`requires_decision`) with `single_topic` vs `intentional_combination`
  (+ `combination_goal` ≥ 20 chars). Submit posts `/v1/ai/generate-course` with the
  whole `selectedDocIds` array.
- Workflow state: `apps/web/src/features/ai-generation/generationWorkflow.ts` +
  `useGenerationWorkflow.ts`; progress panel `GenerationProgressPanel.tsx`;
  reuse dialog `SourceReuseDialog.tsx`.

### API
- `POST /v1/ai/generate-course` (`apps/api/app/modules/ai/router.py:221`):
  1. `analyze_document_set(..., lock_for_update=True)` — tenant-scoped, only
     `lifecycle_status == 'active'`, 404 `documents_not_found` on missing,
     409 `documents_not_ready` when `embedding_status != 'success'`, 409
     `document_embeddings_missing` when no centroid row exists
     (`apps/api/app/modules/ai/source_analysis.py:149`).
  2. 409 `mixed_document_topics` unless `source_strategy == 'intentional_combination'`
     with a ≥ 20-char goal.
  3. 409 `source_documents_already_used` when the sources already cite a course
     (unless `reuse_reason` or explicit `course_id` draft regeneration).
  4. Trial quota + admission limits (`submit_ai_job`), then Celery task
     `ai.generate_course` with `documents=[...ids]`.
- `POST /v1/ai/document-compatibility` — same analysis without locks.
- Request schema `AIGenerateRequest` (`apps/api/app/modules/ai/schemas.py:8`):
  `documents: List[UUID]` `min_length=1, max_length=20`. No uniqueness or
  dedup enforcement.

### Generation job
- `ai.generate_course` (`apps/api/app/modules/ai/tasks.py:42`): durable claim via
  `claim_generation_execution` (pending → running, idempotent redelivery guard),
  then `run_generation_pipeline`. Failure is terminal; no automatic replay.
- `run_generation_pipeline` (`apps/api/app/modules/ai/pipeline.py:334`):
  ingestion-embedding spot check (fails only if ALL docs missing embeddings),
  architect (`run_architect` with `doc_ids` scope), grounded writer
  (`write_course` → `write_lesson` per lesson with `require_sources=True`),
  reviewer, assessment agent, then `_save_generation_to_db`.

### Retrieval / RAG
- `VectorStore` (pgvector, `apps/api/app/modules/ai/ingestion.py:251`) is always
  tenant-scoped; writer retrieval requires `tenant_id` before embedding
  (`test_retrieval_requires_tenant_before_embedding_or_store_access`).
- Lessons may only cite chunks from `doc_ids` in the selected set
  (`resolve_lesson_doc_ids`); multi-document lessons without explicit
  `source_doc_ids` are rejected by the writer. Lexical fallback chunks must
  carry verified provenance metadata.

### Persistence / provenance
- `Course.source_document_ids` (JSONB, array of doc UUID strings),
  `source_strategy`, `source_combination_goal`, `source_analysis`
  (`apps/api/app/modules/courses/models.py:36-39`).
- `Lesson.source_document_ids` + `Lesson.source_references` (per-lesson chunk
  provenance incl. headings/context) — `apps/api/app/modules/lessons/models.py:37-38`,
  populated in `pipeline._save_generation_to_db` from writer `source_references`.
- Draft regeneration (`course_id`) replaces modules/lessons of the same course.

### Existing tests
- Unit: `tests/unit/test_document_compatibility.py` (profile clustering, request
  validation, retrieval/provenance invariants).
- Integration: `tests/integration/test_document_compatibility_api.py` (mixed
  topics 409; `deletion_pending` document rejected 404), admission concurrency,
  execution claim tests (`test_ai_generation_execution_claim.py`,
  `test_ai_execution_claim.py`).
- Frontend: `apps/web/tests/aiGenerationPage.test.tsx` (job restore, duplicate
  upload), `aiGenerationWorkflow.test.ts`, reuse-page/safety tests.

## 2. Confirmed gaps vs the required v1 contract

| # | Requirement | Current state | Gap |
|---|---|---|---|
| G1 | 2–5 unique documents | Schema allows 1–20 | `max_length=20`, `min_length=1`; no 2–5 window |
| G2 | Duplicate IDs | `analyze_document_set` dedups internally, but the job/task receive the raw list; request echoes duplicates | Duplicates are not rejected or normalized at the contract level |
| G3 | Generation-ready only | Checks `embedding_status == 'success'` + `lifecycle_status == 'active'` | `index_status` (`ready`/`partial`) is not enforced server-side; a doc with embeddings but `index_status='failed'` could slip through legacy paths |
| G4 | Stale-revision rejection | Retrieval filters to active index revision | No request-time revision pin; acceptable for v1 (retrieval uses only current revision chunks) |
| G5 | Aggregate content/token budget | No aggregate check anywhere | Silent unbounded concatenation of up to 20 docs; must 413/422 with a clear error instead of truncating |
| G6 | Provenance | Course/lesson already persist source ids/references | Works; needs a regression test for multi-doc |
| G7 | Idempotency | `claim_generation_execution` makes redelivery safe; duplicate *submission* is blocked by `source_documents_already_used` except with `reuse_reason` (product-intended) | Documented; no duplicate job rows for identical in-flight submissions because of the reuse gate + admission; test exists at claim level |
| G8 | Single-doc path preserved | API currently accepts 1 doc | v1 contract change to 2–5 would break the existing single-document flow and `AIGenerateRequest` consumers |

## 3. Design decision — how to enforce the v1 contract without breaking the single-doc path

The single-document flow is a working critical journey (`AI-COURSE-01` adjacent)
and must keep working. Therefore the v1 multi-document contract is enforced
**only when more than one distinct document is submitted**:

- 1 document → existing behavior unchanged (backward compatible), including
  the aggregate chunk budget which does not apply to single-document runs.
- 2–5 documents → the full multi-document v1 contract applies.
- 6+ documents → 422 `too_many_documents` with a stable machine-readable
  `details.code` (endpoint-level `HTTPException`, not a Pydantic message).
- Duplicates: the request is normalized by deduplicating IDs while preserving
  first-occurrence order (`dict.fromkeys`) in the schema; the endpoint then
  validates the normalized list. Retries with duplicated payloads are
  deterministic and cannot change the document set.
- Aggregate budget (multi-doc only): sum of `index_chunks_total` of selected
  docs must not exceed `AI_MULTI_DOC_MAX_TOTAL_CHUNKS` (settings default 4000).
  Exceeding it returns 422 `aggregate_source_budget_exceeded` with per-document
  counts — no silent truncation. Chunk count is a coarse proxy; a token-level
  budget is the noted follow-up.
- Readiness allowlist: docs must be `lifecycle_status='active'`,
  `embedding_status='success'`, and `index_status IN ('ready','partial')`
  (`GENERATION_READY_INDEX_STATUSES`). `processing`/`failed`/any future state
  → 409 `documents_index_failed`; `deletion_pending`/`delete_failed` → 404
  `documents_not_found`; embedding pending/failed → 409 `documents_not_ready`.
- Idempotent submission: before creating a job, the endpoint rejects a new
  submission when the same tenant already has a `pending`/`running` job with
  the identical ordered `params.documents` list (409
  `generation_already_in_progress`). The execution claim remains the replay
  guard; this gate prevents two near-simultaneous HTTP submissions from
  creating duplicate jobs/courses. Draft regen (`course_id`) and explicit
  `reuse_reason` bypass the gate by contract.
- Mixed-language sources: a deterministic language detector (`dominant_language`)
  classifies indexed chunk text as `ru`, `kk` (Cyrillic + Kazakh letters), or a
  script name (latin/cjk/arabic). When a multi-document selection spans more
  than one detected language and `language_confirmed` is not set, the endpoint
  refuses with 409 `mixed_language_sources` carrying `detected_languages`
  BEFORE queueing anything. After explicit confirmation
  (`language_confirmed: true`) the 202 response carries
  `mixed_language_warning: {code, detected_languages, course_language}`. No
  hidden guessing; generation is not silently blocked either.
- Contradictory topics: the existing embedding-cluster analysis still returns
  409 `mixed_document_topics` with an explicit cluster choice.

## 4. API/data contract (v1)

`POST /v1/ai/generate-course` request (no shape change):

```
documents: UUID[]            // after normalization: 1 (single-doc path) or 2..5 (multi-doc path)
source_strategy: single_topic | intentional_combination
combination_goal: string     // required ≥20 chars for intentional_combination
... (unchanged fields)
```

New/updated errors:
- 422 `too_many_documents` — > 5 documents after dedup (stable `details.code`).
- 422 `aggregate_source_budget_exceeded` — Σ index_chunks_total > budget,
  payload includes `document_chunks` and `limit` (multi-doc submissions only).
- 409 `documents_index_not_ready` — selected doc with a non-allowlist
  `index_status` such as `pending`/`processing` (retryable states).
- 409 `documents_index_failed` — selected doc with `index_status = 'failed'`
  (terminal state, distinct code).
- 409 `generation_already_in_progress` — an active job with the identical
  ordered document set already exists for the tenant.
- 409 `mixed_language_sources` — multi-document selection spans more than one
  detected language and `language_confirmed` is false; resubmit with
  `language_confirmed: true` to proceed.

Request additions:
- `language_confirmed: bool = False` — explicit methodologist acknowledgement
  for mixed-language multi-document sets.

Response additions:
- Optional `mixed_language_warning` on the 202 `AIJobResponse` when the
  multi-document selection spans multiple languages (only after confirmation).

Response and job semantics unchanged (202 + AIJobResponse). Params persisted on
the job and the task receive the deduped, ordered document list, so provenance
(`Course.source_document_ids`, `Lesson.source_document_ids`/`source_references`)
stays traceable to contributing document IDs.

## 5. Validation rules (enforced server-side)

1. Pydantic: dedup preserving first-occurrence order in `AIGenerateRequest`
   (model validator); enforce ≤ 5 after dedup; ≥ 1 kept for single-doc compat.
2. Endpoint: readiness gate (active + embeddings success + index not failed)
   inside `analyze_document_set`'s document fetch (extended with index_status
   check), then aggregate budget check using `index_chunks_total` already loaded.
3. All checks are tenant-scoped by construction (`Document.tenant_id == tenant_id`).

## 6. Test matrix

Backend (`apps/api/tests/unit/test_multi_document_contract.py`, no DB required):
- dedup preserves deterministic first-occurrence order;
- schema tolerates >5 (cap owned by endpoint with stable code);
- 1 doc passes (single-doc compat);
- 2–5 unique docs pass;
- `intentional_combination` goal rule still enforced;
- `reuse_reason` + `course_id` exclusivity still enforced;
- budget setting positive; `document_chunk_totals` casts/filtering;
- `dominant_script` detection determinism.

Backend (`apps/api/tests/integration/test_multi_document_generation_api.py`,
DB-backed, tenant-isolated):
- aggregate budget exceeded (multi-doc) → 422 with `details.code`;
- single-document submission exempt from the multi-doc budget → 202;
- multi-doc at the budget limit → allowed;
- 6 unique docs → 422 `too_many_documents` with `limit: 5`;
- `index_status='failed'` → 409 `documents_index_failed`;
- `index_status='processing'` → rejected by the allowlist;
- `deletion_pending` / `delete_failed` → 404;
- cross-tenant document IDs are invisible → 404 `documents_not_found`;
- duplicates normalized before job submission (job params contain the
  deduped list);
- in-flight same-document-set job → 409 `generation_already_in_progress`;
- concurrent identical submissions under a tenant-scoped transaction-level
  advisory lock → exactly one committed job, responses `[202, 409]`
  (`pg_advisory_xact_lock` serializes the in-flight check + insert);
- mixed-language selection without confirmation → 409 `mixed_language_sources`
  with `detected_languages` and no job created; with
  `language_confirmed=true` → 202 with structured `mixed_language_sources`
  warning carrying `detected_languages` and `course_language`;
- mixed topics still 409 (existing behavior preserved);
- provenance: pipeline save path persists course-level `source_document_ids`
  and per-lesson `source_document_ids`/`source_references` covering two
  contributing documents.

Frontend (`apps/web/tests/aiGenerationPage.test.tsx` additions):
- not-ready documents render disabled with a visible reason;
- submit payload contains the selected document IDs in selection order and
  the selected count is rendered;
- selection beyond five documents is blocked.
- a `409 mixed_language_sources` response opens an explicit confirmation
  dialog with the detected languages and selected course language; generation
  is retried only after the methodologist confirms, with
  `language_confirmed: true`.
- combined 409 sequences keep both acknowledgements in either order:
  `mixed_language_sources` then `source_documents_already_used`, and the
  reverse. The final successful request carries
  `language_confirmed: true` and `reuse_reason` exactly once; the submission
  count is exactly 3 (initial + one 409 round each).

## 7. Observability

- Job failure messages already land on `AIJob.message` / `errors` and are shown
  in the progress panel. New validation errors are synchronous 4xx with stable
  codes (machine-readable `detail.code`), consistent with existing
  `mixed_document_topics` handling.
- No new metrics/ logging of PII; validation logs only document IDs and counts.

## 8. Rollout / rollback

- Pure application-level guards; no schema migration, no provider/config change.
- Rollback = revert the single commit (guards are additive validators).
- Existing single-document path and API compatibility verified by tests.

## 9. Later separate phase — YouTube ingestion (OUT OF SCOPE here)

YouTube transcript ingestion will introduce a new source type with its own
readiness states and budget accounting. This plan's contract intentionally keeps
`documents` as existing document IDs only; no URL/YouTube fields are added in v1.

## 10. Blockers / proposals requiring root review

- No migration needed for v1. If product later wants hard duplicate rejection
  (422 instead of normalization) or > 5 docs, that is a contract change.
- Chunk-count budget is a coarse upper bound; a token/character-level budget
  with per-run `estimated_tokens` observability is the proposed follow-up.
- Script-level language detection is intentionally coarse (cyrillic vs latin
  vs cjk vs arabic); `dominant_language` now separates `ru` vs `kk` inside the
  Cyrillic script via Kazakh-specific letters (`әғқңөұүһіѵ`), with unknown /
  no-signal rows excluded from the mixed-language check.
- Frontend language confirmation is implemented as an explicit, non-automatic
  retry: the methodologist sees detected languages and the selected course
  language, can return to the document selection, or confirms one retry with
  `language_confirmed: true`.
- Acknowledgement state machine (2026-08-29 fix): `languageConfirmed` and
  `reuseReason` live in a dedicated `acknowledgements` state independent of
  which 409 dialog opened last. Each 409 handler merges the current call's
  values into it; the language-dialog confirm button passes
  `language_confirmed=true` explicitly and the reuse-dialog confirm passes the
  chosen reason; `handleGenerate` merges dialog arguments with stored
  acknowledgements. State resets only on success or an explicit dialog cancel,
  so neither order (language → reuse or reuse → language) can loop, drop an
  acknowledgement, or duplicate `reuse_reason` in the request.
