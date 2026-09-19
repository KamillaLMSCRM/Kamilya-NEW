# Axis-owned assessment contract

## Identity

| Field | Value |
|---|---|
| Module ID | `AXIS-CONTRACT` |
| Name | Source-owned assessment axis and key |
| Status | Accepted for implementation 2026-09-19 |
| Document version | V1 |
| Template version | V2 |
| Supersedes | None |
| Approved by | Root after CQ-01 defect classification and CQ-02 source-oracle review |
| Change control | Evidence -> root review -> V2/addendum or cancellation |
| Owning epic | `CQCL-001` |

## Responsibility [Core]

Derive the smallest assessable contract from one coherent source-owned information
block: immutable identity, tested axis, one supported keyed answer, exact evidence
references, question intent and allowed distractor constraints.

## Non-responsibilities [Core]

Does not author distractors, call a model/provider, review final prose, decide course
status, persist quizzes, publish courses or create content to meet a count.

## User-visible contribution [Core]

Prevents the model from choosing what fact is being tested or which answer is correct.

## External interface [Core]

```text
derive_assessment_contracts(lesson, source_facts) -> tuple[AssessmentContract | Unassessable]
materialize_candidate(contract, authored_distractors) -> CandidateQuestion | ContractIssue
```

Ordering is deterministic by lesson/source order. Identity, evidence and keyed answer
cannot change during materialization. Performance is linear in the lesson's admitted
facts and requires no external configuration.

## Inputs and outputs [Core]

| Direction | Name | Version | Validation | Sensitive fields |
|---|---|---|---|---|
| Input | Lesson + admitted SourceFacts | Existing/V1 | Same lesson/source block; usable exact evidence | Source text; local only |
| Output | AssessmentContract | V1 | Stable ID, supported axis/key, evidence, constraints | Exact source quote |
| Output | Unassessable | V1 | Stable bounded reason code | None |

## Data ownership [Core]

Owns only ephemeral assessment-contract values. It owns no table or tenant record.
The application module owns persisted drafts/quizzes and tenant context.

## Invariants [Core]

- The keyed answer is derived from admitted source evidence, never model output.
- Axis, answer and evidence belong to the same coherent information block.
- Conditions, negation, optionality and necessary/sufficient meaning are preserved.
- Short exact values remain valid when their source semantics are complete.
- Binary/normative source does not fabricate three near-identical distractors.
- Unassessable input returns a reason; it is never padded.
- Same input produces the same contract IDs/order.

## State machine [Core]

| Current | Command/event | Next | Guard | Side effect |
|---|---|---|---|---|
| source block | derive | assessable | supported atomic axis/key exists | emit contract |
| source block | derive | unassessable | ambiguity/dependency/unsafe OCR | emit reason only |
| contract | materialize | candidate | distractors satisfy shape | emit candidate |
| contract | materialize | issue | identity/key/evidence/shape changed | reject candidate |

## Idempotency and concurrency [Extended]

Pure deterministic computation; repeated calls return equivalent ordered results.
No shared mutable state or locking.

## Error modes [Core]

| Error | Class | Caller behavior | Retry | Visible evidence |
|---|---|---|---|---|
| `unassessable_source_block` | Permanent for input | Record reason and continue | No | Bounded reason |
| `candidate_contract_mismatch` | Candidate defect | Reject candidate | Completion module may request one repair | Issue code |
| Invalid internal contract | Programming defect | Fail focused test/application safely | No blind retry | Exception without payload |

## Dependencies and adapters [Extended]

| Dependency | Interface used | Why needed | Test adapter |
|---|---|---|---|
| Existing evidence models | `LessonDraft`, `SourceFact`, axis types | Current source ownership | Literal fixtures |

## Forbidden dependencies and side effects [Extended]

No LLM/embedding/provider, DB, tenant, HTTP, filesystem, TypeSafe, progress or UI access.

## Existing-module impact addendum [Extended]

| Affected module | Existing contract | Change | Compatibility | Regression test |
|---|---|---|---|---|
| `assessment_axes` | `derive_assessment_axes`, `materialize_assessment` | Deepen into immutable source-owned contract | Preserve safe existing callers or adapt once at application seam | Existing + new interface tests |
| evidence models | Axis/authored assessment dataclasses | Add only fields required by contract | Constructor compatibility decided before acceptance | Model/application tests |

## Security and privacy [Core]

No secrets or tenant identity. Diagnostics contain reason codes and opaque IDs, not raw
source payloads. Exact source text remains process-local and may appear only in approved
development artifacts.

## Observability [Extended]

Counts by safe reason code: assessable, unassessable, contract mismatch. No source text.

## Verification [Core]

| Level | Scenario | Test/evidence | Required result |
|---|---|---|---|
| Unit | Conditions/negation/short values/list axes | `test_assessment_axes.py` plus new RED cases | PASS |
| Interface | Deterministic contract and materialization | New `test_assessment_contract.py` | PASS |
| Contract | Consumer cannot change key/evidence | Application seam fixture | PASS |
| Database | Not applicable: no persistence | N/A | N/A |
| Neighbor | Existing evidence source behavior | Existing evidence tests | PASS |
| Integration | Frozen replay | CQ-07 | Accepted |

## Implementation packet [Core]

| Field | Value |
|---|---|
| Read scope | Accepted tests, `models.py`, `assessment_axes.py`, direct callers |
| Write scope | Frozen after CQ-03; expected `assessment_axes.py` and one dedicated test file |
| Forbidden scope | Application integration, semantic review, providers, DB, frontend, docs |
| Required checks | RED/GREEN focused interface tests and existing assessment-axis suite |
| Stop conditions | Shared model/interface change not accepted; source oracle conflict; neighbor edit needed |
| Handoff evidence | Five fields with exact paths and commands/results |

## Rollout and rollback [Extended]

No direct rollout. Root integrates the interface. Git revert of isolated module change is
the rollback before release; production rollback uses the previous exact release.

## Definition of Ready [Core]

- [x] CQ-01/CQ-02 evidence is reconciled.
- [x] Interface semantics and write scope are frozen; concrete Python names may adapt to existing public APIs.
- [x] RED fixtures are source-verified for XLSX and bounded non-numeric PDF rules.
- [x] Module owner and root reviewer are assigned.

## Definition of Done [Core]

- [ ] Interface and regressions pass.
- [ ] No provider/persistence dependency exists.
- [ ] Root verifies diff and contract behavior.
- [ ] Epic chain passes after integration.
