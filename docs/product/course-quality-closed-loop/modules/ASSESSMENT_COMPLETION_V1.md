# Assessment completion and coverage

## Identity

| Field | Value |
|---|---|
| Module ID | `ASSESSMENT-COMPLETION` |
| Name | Bounded assessment completion, repair and coverage |
| Status | Accepted for implementation 2026-09-19 |
| Document version | V1 |
| Template version | V2 |
| Supersedes | None |
| Approved by | Root after CQ-01 defect classification and CQ-02 source-oracle review |
| Change control | Evidence -> root review -> V2/addendum or cancellation |
| Owning epic | `CQCL-001` |

## Responsibility [Core]

Turn immutable assessment contracts plus model-authored candidate distractors into a
validated assessment outcome: deterministic repair, one bounded identity-preserving
model repair, safe omission, exact coverage audit and targeted supplementation.

## Non-responsibilities [Core]

Does not choose the source-owned key/axis, rewrite lessons, alter source conversion,
select provider routing, persist a course, publish, or invent quota-filling questions.

## User-visible contribution [Core]

Automatically fixes detectable question defects and leaves only exact unresolved
coverage/review reasons instead of presenting weak tests or a generic crash.

## External interface [Core]

```text
complete_assessment(contracts, candidate_author, reviewer, policy) -> AssessmentOutcome
```

The result contains retained questions, omitted contract IDs/reasons, coverage,
attempt counters and one terminal status. Maximum per-contract work is deterministic
validation plus one repair and one replacement attempt; timeouts remain caller/provider
policy. The interface is async only where an injected model adapter is invoked.

## Inputs and outputs [Core]

| Direction | Name | Version | Validation | Sensitive fields |
|---|---|---|---|---|
| Input | Immutable AssessmentContracts | V1 | Unique IDs and source ownership | Exact source quote |
| Input | Candidate author/reviewer adapters | V1 | Bounded structured response | No credentials in payload/logs |
| Output | AssessmentOutcome | V1 | Retained questions + omissions + coverage + status | Safe diagnostics only |

## Data ownership [Core]

Owns ephemeral completion state and reason counters. It does not own persisted courses,
quizzes or jobs; the application seam remains the sole durable writer.

## Invariants [Core]

- A retained question preserves contract ID, key, evidence and assessed axis.
- Every option is relevant to the same question/block; truth alone is insufficient.
- Deterministic repair runs before another provider request where possible.
- At most one model repair and one replacement attempt per uncovered contract.
- Repair never consumes rejected prose as a new source of truth.
- Irreparable candidates are omitted without quota padding.
- Coverage is calculated over assessable contracts, not desired question count.
- Targeted supplementation addresses only exact uncovered contract IDs.
- Terminal status is honest: complete, complete-with-warnings, or review-required.
- Provider/parse failures remain distinct from semantic rejection.

## State machine [Core]

| Current | Command/event | Next | Guard | Side effect |
|---|---|---|---|---|
| contract | author | candidate | structured candidate returned | increment authored attempt |
| candidate | validate | retained | all deterministic/semantic gates pass | add question |
| candidate | deterministic repair | retained/rejected | safe local correction exists | no provider call |
| rejected | model repair | retained/rejected | repair budget unused | one provider call |
| rejected/uncovered | replacement | retained/omitted | replacement budget unused | one targeted call |
| assessed set | coverage audit | terminal | every assessable contract classified | emit outcome |

## Idempotency and concurrency [Extended]

For fixed contracts, policy and recorded provider responses, replay is deterministic.
No internal parallel provider fan-out in V1. The application owns job cancellation and
persistence locks; this module checks cancellation only through an injected callback if
the accepted integration requires it.

## Error modes [Core]

| Error | Class | Caller behavior | Retry | Visible evidence |
|---|---|---|---|---|
| Candidate semantic defect | Permanent for candidate | Repair then omit | Bounded per policy | Reason code |
| Missing coverage after budget | Quality outcome | Save reviewable draft | No hidden retry | Uncovered contract IDs |
| Malformed provider response | Provider/contract failure | Existing provider policy | Existing bounded retry only | Classified failure |
| Adapter unavailable/timeout | Transient provider failure | Existing failover policy | Existing policy | Sanitized provider class |

## Dependencies and adapters [Extended]

| Dependency | Interface used | Why needed | Test adapter |
|---|---|---|---|
| AXIS-CONTRACT | AssessmentContract | Immutable source truth | Literal contracts |
| Candidate author | Structured candidate operation | Produce distractors only | Recorded fake adapter |
| Semantic reviewer | Blind all-option result | Detect unresolved relation/logic errors | Recorded fake adapter |
| Existing validators | Question-set checks | Preserve mature deterministic policies | Pure calls |

## Forbidden dependencies and side effects [Extended]

No DB/table write, course publication, source/lesson mutation, provider selection,
credential access, TypeSafe runtime call, frontend behavior or billing change.

## Existing-module impact addendum [Extended]

| Affected module | Existing contract | Change | Compatibility | Regression test |
|---|---|---|---|---|
| `semantic_assessment` | block generation/review | Delegate key/axis ownership and bounded completion | Preserve provider/parse failure semantics | semantic focused tests |
| `assessment_coverage` | topic diagnostics | Audit assessable contract IDs and exact omissions | Keep existing diagnostics additive | coverage tests |
| application/publishability | assessment review outcome | Consume terminal outcome | Existing draft persistence remains | application/pipeline tests |

## Security and privacy [Core]

Model packets contain only bounded exact source evidence required for the contract.
Logs/metrics contain IDs, counts, reason codes, timing and token counters—not prompts,
responses, credentials, hidden reasoning or raw tenant data.

## Observability [Extended]

Record authored/repaired/replaced/retained/omitted counts, per-reason counts, coverage
ratio, terminal status, provider/model ID returned and optional token/cache counters.
Missing counters remain unknown, never zero.

## Verification [Core]

| Level | Scenario | Test/evidence | Required result |
|---|---|---|---|
| Unit | Relevant distractors, optionality, duplication, repair budget | New completion tests | PASS |
| Interface | Outcome and bounded attempts | `test_assessment_completion.py` | PASS |
| Contract | Exact contract IDs survive author/repair | Application seam fixture | PASS |
| Database | Not applicable inside module | N/A | N/A |
| Neighbor | Provider failures/cancellation/draft status | Existing application/pipeline tests | PASS |
| Integration | Repeated PDF/XLSX replay | CQ-07/CQ-08 | Accepted |

## Implementation packet [Core]

| Field | Value |
|---|---|
| Read scope | Accepted contract, semantic/coverage modules, focused tests, replay runner |
| Write scope | Frozen after CQ-03; expected dedicated completion module/tests plus accepted narrow semantic/coverage edits |
| Forbidden scope | Axis/key module, application integration, providers, DB, frontend, docs |
| Required checks | RED/GREEN focused tests; recorded-response replay; existing semantic/coverage tests |
| Stop conditions | Key/axis mutation required; unlisted module impact; provider policy change; source oracle conflict |
| Handoff evidence | Five fields with paths, tests and unresolved quality cases |

## Rollout and rollback [Extended]

Root integrates the module. No direct rollout or migration. Roll back isolated code or
the exact release revision without data transformation.

## Definition of Ready [Core]

- [x] CQ-01/CQ-02 evidence is reconciled.
- [x] Attempt policy/statuses/write scope are frozen.
- [x] RED fixtures cover unrelated true options and missing coverage.
- [x] Module owner and root reviewer are assigned.

## Definition of Done [Core]

- [ ] Interface, bounded-attempt and replay tests pass.
- [ ] No quota padding or source/key mutation is possible.
- [ ] Root verifies diff and application integration.
- [ ] Epic critical journeys pass.
