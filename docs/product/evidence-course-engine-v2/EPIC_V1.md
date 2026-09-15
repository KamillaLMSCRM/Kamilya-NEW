# Evidence-first course generation V2

## Identity

| Field | Value |
|---|---|
| Epic ID | `AI-EVIDENCE-V2` |
| Status | Accepted |
| Root owner | Root Codex, architecture/integration/release acceptance |
| Product owner | Kamilya owner |
| Approved by | Kamilya owner |
| Document version | V1 |
| Template version | V2 |
| Supersedes | None |
| Reason | Initial production integration of the accepted V2 experiment |
| Decision date | 2026-09-15 |
| Change control procedure | Root proposes evidence-backed addendum; product owner approves material behavior/production changes; root may cancel and clean up on a failed gate |

## User-visible objective

A methodologist can use a large or structurally complex source without writing a manual preflight description and receive a coherent, source-grounded draft course and useful non-duplicating tests. The job must not report success with a partial, generic or unsupported result.

## Success evidence

- The normal `/ai/generate` journey completes through the existing job interface.
- Every admitted source fact belongs to one evidence plan and is represented in the generated lessons.
- Questions test source facts, keep server-owned options/answer keys and contain no generic/meta or duplicate prompts.
- A failed embedding route does not discard facts; a failed content route does not persist a completed draft.
- Existing draft review, publication, tenant isolation, cancellation and resumability remain effective.

## Explicit exclusions

- Automatic publication or learner assignment.
- Manual OCR clarification screens.
- Billing/tariff, DNS, proxy, database schema or tenant-limit changes. The
  owner-approved Voyage V4 primary family and batching are part of this release.
- Exact generated wording as a stable contract.

## Roles and authority

| Role | Named owner | Accountable for | Allowed decisions | Forbidden actions |
|---|---|---|---|---|
| Root owner | Root Codex | module map, integration, gates, release readback | implementation inside accepted interfaces | silent scope expansion |
| Module owner | Root Codex | V2 engine and application adapter | internal choices preserving contract | changing unrelated modules |
| Product owner | Kamilya owner | objective, minimum quality, release authority | material behavior and production decision | implicit authorization |
| Reviewer | independent bounded agent, then root | contract/regression findings | review disposition | editing scope during review |

## End-to-end states

```text
selected ready source -> running evidence plan -> running realization
-> quality gate -> existing transactional persistence -> completed draft

provider interruption -> interrupted/retryable (no completed draft)
cancellation -> cancelled (no late or partial course)
quality rejection -> interrupted/retryable (no completed draft)
```

## Critical journeys

| ID | Starting state | Action | Expected terminal evidence |
|---|---|---|---|
| CJ-01 | ready structured source | methodologist starts generation | completed grounded draft with lessons and quizzes |
| CJ-02 | embeddings unavailable | generation continues | all facts preserved and `embedding_degraded` recorded |
| CJ-03 | model output violates evidence contract | validation exhausts retries | interrupted job, no new completed course |
| CJ-04 | running generation | methodologist cancels | cancelled job and no late course |
| CJ-05 | exact deployed synthetic source | production smoke | structure/quiz readback and cleanup, zero invitations |

## Module map

```text
direct source corpus -> Evidence Course Engine V2 -> existing CourseGeneration schemas
-> existing transactional persistence -> draft course and quizzes
```

## Module index

| Module ID | Responsibility | Active mini-spec | Data owner | Writer |
|---|---|---|---|---|
| `EVIDENCE-ENGINE-V2` | evidence planning, grounded realization and publishability decision | `modules/EVIDENCE_ENGINE_V2_V1.md` | immutable in-memory plan/result | root |

## Interface contracts

| Contract ID | Producer | Consumer | Version | Compatibility rule |
|---|---|---|---|---|
| `DIRECT-SOURCE-GENERATION` | V2 engine | existing pipeline/persistence | V1 | map to existing course/content/assessment types; no API or DB schema change |

## Existing-module impact matrix

| Existing module | Impact class | Planned change | Must remain unchanged | Regression check |
|---|---|---|---|---|
| `ai.pipeline` | Interface | select V2 for direct-source generation and map result | job admission, progress, cancellation, checkpoint/persistence transaction | pipeline and resumability tests |
| `ai.direct_source` | Consumer | expose corpus through a V2 adapter | original blob/hash/tenant checks and conversion limits | direct-source tests |
| `ai.llm_client` | Consumer | batch V2 queries through all compatible Voyage V4 routes before private Qwen fallbacks | tenant BYOK and exact embedding-space isolation | provider contract tests |
| `ai.ingestion/embeddings` | Consumer | optional retrieval measurement | indexed corpus and embedding failover semantics | embedding tests and degraded path |
| courses/lessons/quizzes | None | no direct change | DB ownership, review and publish rules | existing save/publish tests |
| frontend | None | no planned source change | current job API/polling UI | existing generation workflow tests |

## Data and migration plan

No database migration. The V2 result is mapped into existing `Course`, `Module`, `Lesson`, `Quiz`, `Question` and `QuizChoice` persistence. Bounded V2 diagnostics are added only to the existing `Course.source_analysis` JSON. Existing tenant key, RLS/FORCE RLS and transactional cancellation/save locking remain the data boundary.

## Security and privacy invariants

- Only the selected tenant-owned direct-source corpus enters the engine.
- Prompts contain bounded evidence for one lesson, never whole tenant inventory.
- No secret, provider key, raw response or tenant payload is logged.
- Provider selection remains server-owned and honors an explicit tenant override.
- V2 cannot publish, assign, send invitations or bypass review.

## Verification plan

| Level | Scope | Command or evidence | Required result |
|---|---|---|---|
| Focused | V2 policy | `pytest tests/unit/test_evidence_course_engine_v2.py` | PASS |
| Contract | V2 to pipeline mapping | new public-seam contract test | PASS |
| Neighbor | cancellation/resume/save/provider | existing focused suites | PASS |
| Integration | `AI-COURSE-01` | required test list and DEV gate | PASS |
| Release | exact candidate | CI, image and no-migration evidence gate | PASS |
| Production | exact revision and flow | synthetic bounded document-to-course smoke | PASS and cleanup |

## Agent allocation

| Agent | Read scope | Write scope | Forbidden scope | Completion packet |
|---|---|---|---|---|
| root | whole affected chain | candidate integration and canonical docs | unrelated worktrees/modules | exact diff/tests/release evidence |
| read-only worker | AI source/tests and V2 commits | none | secrets/providers/DB/deploy | five-field integration map |
| independent reviewer | final candidate diff/tests | none | edits/external systems | severity-ranked five-field handoff |

## Rollout and stop conditions

Release order is local candidate -> Supabase DEV/Render acceptance -> exact CI/image -> protected no-migration VM126 rollout -> synthetic production smoke. Stop on an unplanned schema change, missing provider route, partial persistence, broken cancellation/resume, failed `AI-COURSE-01`, mixed API/worker identity, or inability to clean synthetic state. Roll back to the recorded immutable production image on a production capability failure.

## Definition of Ready

- Objective, public seam, data ownership, impact and negative space are explicit.
- Current owner approved implementation and gated production rollout.
- Baseline and expected module map are recorded.

## Definition of Done

- Focused, contract, neighbor and critical-journey gates pass.
- Exact production API/workers and frontend compatibility are independently read back.
- Bounded production generation and cleanup pass.
- Active contract/documentation indexes and release notes are updated.
