# Evidence-course assessment quality closed loop

## Identity

| Field | Value |
|---|---|
| Epic ID | `CQCL-001` |
| Status | Implementation accepted; exact-SHA DEV/production gates pending |
| Root owner | Codex root orchestrator (Astra) |
| Product owner | Kamilya owner |
| Approved by | Kamilya owner for implementation of the agreed plan |
| Document version | V1 |
| Template version | V2 |
| Supersedes | None |
| Reason | Initial contract for automatic assessment correction and coverage |
| Decision date | 2026-09-19 |
| Change control procedure | Module owner proposes evidence -> root reviews impact -> product owner approves material scope change -> new version/addendum or cancellation |

## User-visible objective

A methodologist who generates a course from a small, large or structurally complex
supported source receives an unpublished but usable draft whose retained questions
test the same source-owned information block as their lesson, have one defensible
correct answer and plausible relevant distractors. Detectable defects are corrected
or removed automatically; only unresolved source coverage remains explicitly marked
for review. The system never invents questions to satisfy a target count.

## Success evidence

- One paragraph can produce one short lesson and only the questions supported by it.
- Additional coherent source blocks increase lessons/questions discretely without a quota.
- Correct answer, assessed axis and evidence identity are server-owned, not model-selected.
- Every retained option answers the same question and belongs to the same information block.
- Invalid options/questions are repaired within a bounded budget or omitted.
- Omission triggers a coverage re-audit and targeted supplementation only for an exact
  uncovered assessable block.
- A saved draft exposes `completed`, `completed_with_warnings` or `review_required`
  accurately; detectable quality gaps are not presented as generic success or crash.
- Repeated PDF/XLSX replays meet the acceptance thresholds in `acceptance/CRITICAL_JOURNEYS_V1.md`.

## Explicit exclusions

- No guaranteed fixed lesson/question count.
- No model training, fine-tuning or distillation.
- No TypeSafe call in the production/client flow.
- No changes to provider billing, plans, credentials or tenant custom-model interface.
- No automatic publication or approval.
- No customer-document mutation during testing.
- No replacement of the existing evidence V2 generation path.

## Roles and authority

| Role | Named owner | Accountable for | Allowed decisions | Forbidden actions |
|---|---|---|---|---|
| Root owner | Codex/Astra | Module map, contracts, integration, stop/release decisions | Technical decisions preserving approved objective | Silent scope/authority expansion |
| Module owner | Assigned bounded Terra worker per accepted mini-spec | One module implementation and focused evidence | Internal choices preserving interface | Neighbor/shared-contract changes |
| Product owner | Kamilya owner | Objective, exclusions, business acceptance and production authority | Material scope and production decisions | Implicit authorization from history |
| Reviewer | Independent Luna worker; final acceptance by root | Contract, semantic and regression review | Review disposition only | Editing the reviewed module |

## End-to-end states

```text
normalized source blocks
  -> assessable contracts + explicit unassessable reasons
  -> model-authored candidate distractors
  -> deterministic validation
  -> bounded local repair/replacement
  -> course-wide coverage audit
  -> completed | completed_with_warnings | review_required
```

Provider/parse failure remains a classified generation failure. Quality rejection of
one candidate does not become a provider failure and does not cancel a useful draft.

## Critical journeys

| ID | Starting state | Action | Expected terminal evidence |
|---|---|---|---|
| CJ-01 | One coherent paragraph | Generate | One proportional lesson; zero or more defensible questions; no padding |
| CJ-02 | Multi-section policy PDF | Generate repeatedly | Section ownership preserved; required topics covered or explicitly reviewed |
| CJ-03 | Primary/supporting-sheet XLSX | Generate repeatedly | Primary entity/column ownership preserved; no cross-entity distractors |
| CJ-04 | Candidate contains unrelated true options | Validate/repair | Irrelevant options removed/replaced; identity/evidence unchanged |
| CJ-05 | Candidate cannot be repaired safely | Complete assessment | Candidate omitted; targeted coverage decision; saved draft remains inspectable |
| CJ-06 | Provider unavailable | Generate | Existing provider failure semantics and safe draft/fallback behavior remain unchanged |

## Module map

```text
evidence source/lesson plan
  -> AXIS-CONTRACT-V1
  -> ASSESSMENT-CONTRACT-V1
  -> candidate author adapter
  -> ASSESSMENT-COMPLETION-V1
  -> existing publishability/application seam
```

## Module index

| Module ID | Responsibility | Active mini-spec | Data owner | Writer |
|---|---|---|---|---|
| AXIS-CONTRACT | Source-owned assessed axis, key and evidence identity | `modules/AXIS_CONTRACT_V1.md` | Ephemeral assessment contract | Assigned after CQ-03 |
| ASSESSMENT-COMPLETION | Validation, bounded repair/omission, coverage outcome | `modules/ASSESSMENT_COMPLETION_V1.md` | Ephemeral completion result/diagnostics | Assigned after CQ-03 |

## Interface contracts

| Contract ID | Producer | Consumer | Version | Compatibility rule |
|---|---|---|---|---|
| ASSESSMENT-CONTRACT | AXIS-CONTRACT | Candidate adapter and ASSESSMENT-COMPLETION | V1 | Additive reason/diagnostic fields only; identity/key immutable |

## Existing-module impact matrix

| Existing module | Impact class | Planned change | Must remain unchanged | Regression check |
|---|---|---|---|---|
| `evidence_engine.assessment_axes` | Invariant | Strengthen source-owned axis/key contract | Existing safe axes and short exact values remain valid | `test_assessment_axes.py` |
| `evidence_engine.semantic_assessment` | Invariant | Restrict model to candidate distractors and bounded identity-preserving repair | Existing parser/provider failure classification | semantic assessment focused tests |
| `evidence_engine.assessment_coverage` | Interface | Report exact uncovered assessable contracts | Existing topic diagnostics remain readable | coverage tests |
| `evidence_engine.application` | Consumer | Compose accepted module interfaces | Source conversion, lesson generation, progress and cancellation | application/pipeline contract tests |
| Generation UI | None unless outcome contract requires compatible copy | No planned edit before backend contract proves need | Existing progress and saved-draft navigation | focused frontend tests if touched |
| Providers/routing | None | No configuration change | Existing chain, timeout, usage and tenant-owned models | provider contract regressions |
| Persistence/DB | None | No schema or ownership change planned | Tenant isolation, draft storage and idempotency | existing application/pipeline tests |

An unlisted module is forbidden scope until a versioned impact addendum is accepted.

## Data and migration plan

No database migration is planned. New contracts/results are process-local dataclasses
or typed objects. Existing course/quiz persistence remains owned by the application
seam. Any need for durable fields stops the epic for an ownership/migration addendum.

## Security and privacy invariants

- Tenant and persistence ownership remain unchanged.
- Prompts, logs, diagnostics and artifacts never contain secrets or hidden reasoning.
- Local replay uses approved local/synthetic source files; no customer production writes.
- TypeSafe receives only the explicitly approved development artifact contract.
- Provider configuration and credentials are read through canonical process-local paths.

## Verification plan

| Level | Scope | Command or evidence | Required result |
|---|---|---|---|
| Focused | Axis/completion policy | Named pytest files from accepted mini-specs | RED then PASS |
| Contract | Producer-consumer seam | Application seam tests using real typed contracts | PASS |
| Neighbor | Existing V2 behavior | Evidence application/pipeline/provider tests | PASS |
| Integration | Frozen replay corpus | Offline and authorized real-adapter replay | Thresholds satisfied; no cherry-picking |
| Release | Exact candidate | Full risk-based CI and release contract gate | PASS |
| Production | Exact revision and flow | Synthetic methodologist PDF/XLSX smoke | PASS and cleanup |

## Agent allocation

| Agent | Read scope | Write scope | Forbidden scope | Completion packet |
|---|---|---|---|---|
| Luna baseline classifier | Named errors/replays/tests | None | Edits/network/providers | Five-field handoff with fixture pointers |
| Luna source oracle | Named local inputs/source adapters | None | Provider calls/edits | Verified candidate oracle with citations |
| Terra axis writer | Accepted exact paths | Accepted exact paths | Shared application/contracts/docs | RED/GREEN tests and changed paths |
| Terra completion writer | Accepted exact paths | Accepted exact paths | Shared application/contracts/docs | RED/GREEN tests and changed paths |
| Luna replay/reviewer | Candidate/replay artifacts | Explicit isolated artifact path only | Application edits/deploy | Metrics/findings; root verifies |

## Rollout and stop conditions

No release occurs until two accepted repeats per required source class or a stricter
accepted corpus rule passes. Stop on unplanned module impact, ambiguous source oracle,
wrong production seam, provider/billing boundary, test weakening, overlapping writer,
or inability to reproduce the exact defect. Rollback is the prior exact production
revision; no migration rollback is expected.

## Definition of Ready

- [x] CQ-01 and CQ-02 independently complete.
- [x] Root verifies every oracle item against exact source.
- [x] Mini-specs and contract are Accepted.
- [x] Disjoint write scopes and RED tests are named.
- [x] Expected post-change Graphify map is recorded.

## Definition of Done

- [x] Module/contract/neighbor tests pass.
- [x] Critical journeys pass with accepted repeatability.
- [ ] Exact candidate passes CI and DEV human journey.
- [ ] Exact production revision and bounded user flow are read back.
- [ ] Synthetic artifacts are cleaned and residual risks are explicit.
