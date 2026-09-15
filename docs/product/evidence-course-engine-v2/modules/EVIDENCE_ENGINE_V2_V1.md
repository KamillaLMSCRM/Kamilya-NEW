# Evidence Course Engine V2 module mini-spec

## Identity

| Field | Value |
|---|---|
| Module ID | `EVIDENCE-ENGINE-V2` |
| Name | Evidence Course Engine V2 |
| Status | Accepted |
| Document version | V1 |
| Template version | V2 |
| Supersedes | None |
| Approved by | Kamilya owner, 2026-09-15 |
| Change control | root proposal -> independent review -> owner approval for material behavior -> supersede/cancel |
| Owning epic | `AI-EVIDENCE-V2` |

## Responsibility [Core]

Turn one verified direct-source corpus and optional methodologist intent into an immutable evidence plan, grounded lessons, server-owned assessments and a deterministic publishability result.

## Non-responsibilities [Core]

The module does not own source upload/conversion, tenant authorization, job admission, DB persistence, review/publication, assignment, provider credentials or billing.

## User-visible contribution [Core]

Complex sources produce a coherent draft with useful questions; invalid or incomplete output is not reported as a successful course.

## External interface [Core]

```text
generate_evidence_course(corpus, intent, generation_client, embedding_client,
                         progress_callback, cancellation_callback)
  -> EvidenceGenerationOutput
```

The result is immutable and contains the existing course/content/assessment projection plus bounded quality/provenance metadata. Provider calls are asynchronous and cancellation-aware. Embeddings are optional; generation content is not.

## Inputs and outputs [Core]

| Direction | Name | Version | Validation | Sensitive fields |
|---|---|---|---|---|
| Input | verified direct-source corpus | existing | tenant/source revision already verified; non-empty bounded facts | source content |
| Input | course intent | V1 | bounded strings/list | none |
| Output | evidence generation result | V1 | full fact coverage and publishability rules | generated content |

## Data ownership [Core]

The module owns immutable in-memory facts, plan, grounded blocks and quality report only. It writes no table. Existing pipeline/persistence owns tenant records and retention.

## Invariants [Core]

- Each admitted fact is assigned exactly once to the plan and covered by grounded output.
- Supporting/catalog data cannot silently become the main curriculum.
- Question options and correct answer keys remain deterministic and server-owned.
- No generic/meta/duplicate question, unsupported number or visible OCR artifact passes.
- Missing embeddings set degraded evidence but do not remove facts.
- Missing/invalid generation output fails before completed persistence.
- Small sources are not padded to a quota; large sources are split by evidence capacity.

## State machine [Core]

| Current | Command/event | Next | Guard | Side effect |
|---|---|---|---|---|
| ready | build plan | planned | admitted facts non-empty | immutable plan |
| planned | realize lesson | realizing | cancellation clear | bounded provider call |
| realizing | all lessons valid | evaluated | full coverage | quality report |
| evaluated | publishable | complete | all quality rules pass | mapped result |
| any running | cancellation | cancelled | callback raises | no completed result |
| realizing | provider/contract exhausted | failed | no acceptable response | controlled error |

## Idempotency and concurrency [Extended]

The deterministic plan/fingerprint depends only on normalized source, intent and policy version. Existing job claim/checkpoint ownership serializes retries. The module does not perform shared writes.

## Error modes [Core]

| Error | Class | Caller behavior | Retry | Visible evidence |
|---|---|---|---|---|
| unusable source/facts | permanent | fail job | after source correction | safe code |
| all content providers unavailable | transient | interrupt job | existing resume path | safe code |
| content contract rejected | retryable then terminal | retry bounded; interrupt | resume/new provider | safe reason codes |
| embedding providers unavailable | degraded | continue | none inside job | bounded degraded flag |
| cancellation | terminal | abort | existing explicit resume rules | cancelled job |

## Dependencies and adapters [Extended]

| Dependency | Interface used | Why needed | Test adapter |
|---|---|---|---|
| `DirectSourceCorpus` | read-only corpus adapter | verified source and structure | in-memory fixture |
| `ResilientLLMClient` | validated async completion | tenant/global route and failover | scripted client |
| `ResilientEmbeddingsClient` | async document/query embeddings | optional retrieval measurement | failing/in-memory client |
| existing pipeline mapper | existing schema projection | transactional persistence compatibility | in-memory session fixtures |

## Forbidden dependencies and side effects [Extended]

No direct DB/storage/provider-key access, no logging of source/response, no publish/assignment/invitation, no fallback to general model knowledge, no synthetic/hash embeddings.

## Existing-module impact addendum [Extended]

| Affected module | Existing contract | Change | Compatibility | Regression test |
|---|---|---|---|---|
| `ai.pipeline` | `run_generation_pipeline` | direct-source internal engine selection | same signature/states/persistence seam | public pipeline contract and cancellation/resume suites |
| `ai.direct_source` | verified corpus | read-only V2 adapter | no change to conversion/security | existing direct-source suite |

## Security and privacy [Core]

Tenant context and source ownership remain outside and mandatory before the call. Adapter accepts only a verified corpus. Prompts are lesson-bounded. Secrets and raw output never enter logs or persisted diagnostics.

## Observability [Extended]

Safe stage timings, completed/total units, embedding degraded state, provider route name/model ID, quality counters and semantic fingerprint. No prompt, response body, key, tenant content or PII.

## Verification [Core]

Focused V2 tests, one producer-consumer mapping contract, existing cancellation/resume/save tests, `AI-COURSE-01`, DEV provider flow and disposable production smoke are mandatory.

## Implementation packet [Core]

| Field | Value |
|---|---|
| Read scope | `apps/api/app/modules/ai/**`, relevant schemas/tests, critical journey |
| Write scope | V2 package, one integration/mapper seam, focused tests, changelog/docs |
| Forbidden scope | migrations, provider configuration, tenant limits, unrelated frontend/domain modules |
| Required checks | focused tests -> contracts/neighbors -> AI-COURSE-01 -> release suite |
| Stop conditions | unplanned schema/interface ownership change, partial persistence, security/tenant regression |
| Handoff evidence | exact paths, commands/results, SHA and runtime readbacks |

## Rollout and rollback [Extended]

No schema migration. Deploy one immutable image to API and all workers. Roll back all four to the previous image on wrong identity, unhealthy service or failed capability smoke.

## Definition of Ready [Core]

Accepted by the owner with interface, invariants, impacts, scopes and stop conditions recorded.

## Definition of Done [Core]

Implementation and all required test/runtime gates pass with no unexpected graph edge or residual synthetic state.
