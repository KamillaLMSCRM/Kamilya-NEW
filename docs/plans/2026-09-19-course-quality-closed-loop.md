# Course quality closed-loop epic

## Scope and truth

- Owner: Codex root orchestrator (Astra); product owner: Kamilya owner.
- Repository and baseline: `Kamilya-NEW=19e55a95a6ead014976168dcbebd7ad20c91f328`
  (`v0.7.4`, tracked files clean at epic start).
- Working branch: `feature/course-quality-closed-loop-20260919`.
- Environment scope: isolated local worktree, existing DEV/test contour, existing
  production adapters for realistic conversion/model checks, then DEV and production
  only after their named gates.
- Last updated: 2026-09-19 Asia/Qyzylorda.
- Exclusions: no provider billing/tier/key changes; no tenant-owned model contract
  redesign; no customer document writes; no production debugging loop; no quota
  padding; no TypeSafe dependency in client runtime.

| Claim area | Canonical source | Freshness / limitation |
|---|---|---|
| Product | `PROJECT.md` | Current checkout at baseline SHA |
| Current system | `docs/PROJECT-CONTEXT.md` | Runtime/provider facts require fresh readback |
| Production | `docs/PRODUCTION_READINESS.md` | Release evidence must bind exact candidate SHA |
| Recurrence prevention | `ERRORS.md` AI-QUALITY-027 | Current NO-GO and source-bound constraints |
| Architecture navigation | `graphify-out/graph.json` | Built 2026-09-19; GRAPH-DERIVED only |

## Ownership

| Scope or operation | Owner | Writer | Reviewer | Overlap rule |
|---|---|---|---|---|
| Epic contracts, shared models, application integration | Root | Root | Independent reviewer | Root-only shared scope |
| Baseline defect classification | Root | None (read-only Luna worker) | Root | No mutations |
| Source coverage oracle | Root | None (read-only Luna worker) | Root | No mutations |
| Axis/key contract implementation | Root | One bounded Terra worker | Root + independent reviewer | Exact disjoint paths |
| Completion/repair implementation | Root | One bounded Terra worker | Root + independent reviewer | Exact disjoint paths |
| Replay fixtures/evaluation | Root | One bounded Luna worker | Root | Synthetic or approved local inputs only |
| Git, DEV, release, production | Root | Root / canonical runners only | Root | Never delegated to leaf workers |
| `AGENTS.md`, `ERRORS.md`, canonical readiness/handoff | Root | Root | Root | Leaf workers read-only |

## Dependency graph

```text
CQ-00 -> (CQ-01 || CQ-02) -> CQ-03 -> (CQ-04 || CQ-05) -> CQ-06
CQ-06 -> (CQ-07 || CQ-08) -> CQ-09 -> CQ-10 -> CQ-11 -> CQ-12
```

The two parallel bars are execution waves. No more than two leaf agents run at
once. Root performs meaningful non-overlapping critical-path work while a wave runs.

## Nodes

### CQ-00 — Establish reproducible baseline and contracts

- Status: `COMPLETE`
- Scope: repository governance, current V2 seams, Graphify map, frozen acceptance.
- Owner/Writer: root.
- Dependencies: none.
- Exit gate: exact baseline and worktree recorded; relevant errors read; graph queried;
  draft epic, module contracts and journeys exist; no application code changed.
- Evidence: `GIT-DERIVED` baseline above; `GRAPH-DERIVED` current symbols; runtime
  claims `NOT VERIFIED`.
- Approval gate: `OWNER-CONFIRMED` request to execute the agreed plan on 2026-09-19.
- Cleanup: preserve pre-existing `.codex/tmp`; remove only new temporary artifacts.

### CQ-01 — Classify frozen baseline failures

- Status: `COMPLETE`
- Scope: existing replay artifacts/tests and AI-QUALITY-027 only.
- Owner: root; Writer: none; Worker: read-only Luna/medium.
- Dependencies: CQ-00.
- Exit gate: machine-readable defect classes, exact fixture pointers, observed
  reproducibility, and gaps; no architecture proposal or mutation.
- Evidence: worker handoff plus root source/replay confirmation.
- Approval gate: not required.

### CQ-02 — Build an independent source-coverage oracle

- Status: `COMPLETE`
- Scope: approved local PDF/XLSX fixtures and source contracts; no provider calls.
- Owner: root; Writer: none; Worker: synthetic evaluator Luna/medium.
- Dependencies: CQ-00.
- Exit gate: expected semantic blocks/objectives, assessable/unassessable reasons,
  exact source citations, and negative-space cases for replay.
- Evidence: artifact is candidate evidence until root verifies every oracle item.
- Approval gate: not required.

### CQ-03 — Accept V1 module contracts

- Status: `COMPLETE`
- Owner/Writer: root.
- Dependencies: CQ-01, CQ-02.
- Exit gate: every expected behavior is checked against source; module interfaces,
  impact matrix, write scopes and tests are Accepted; no unresolved ownership conflict.
- Approval gate: root may accept within the owner-approved objective; material scope
  change returns to product owner.

### CQ-04 — Implement server-owned assessment axis and key

- Status: `COMPLETE`
- Owner: root; Writer: one bounded Terra/medium worker.
- Dependencies: CQ-03.
- Write scope: exact paths named by accepted AXIS-CONTRACT mini-spec.
- Exit gate: RED/GREEN interface tests prove immutable source-owned axis, keyed answer,
  evidence identity and safe unassessable result; no model-selected correct answer.
- Cleanup: no provider calls or persistent replay output.

### CQ-05 — Implement bounded completion, repair and coverage loop

- Status: `COMPLETE`
- Owner: root; Writer: one bounded Terra/medium worker.
- Dependencies: CQ-03.
- Write scope: exact paths named by accepted ASSESSMENT-COMPLETION mini-spec.
- Exit gate: invalid options/questions are deterministically repaired or omitted;
  one bounded targeted model repair and one replacement attempt are enforced;
  coverage is re-audited; no quota padding; explicit review outcome remains.
- Cleanup: no provider/runtime mutation.

### CQ-06 — Integrate at the active application seam

- Status: `COMPLETE`
- Owner/Writer: root.
- Dependencies: CQ-04, CQ-05.
- Exit gate: `generate_evidence_course` consumes the accepted interfaces; application
  and pipeline contract tests pass; legacy and V2 paths are not accidentally mixed.

### CQ-07 — Replay PDF, XLSX and synthetic edge corpus

- Status: `COMPLETE`
- Owner: root; Worker: synthetic evaluator Luna/medium.
- Dependencies: CQ-06.
- Exit gate: repeated local replays use production conversion/model adapters where
  authorized; timings and provider counters are preserved; no favorable-run selection;
  no customer or production writes.

### CQ-08 — Independent semantic and TypeSafe evaluation

- Status: `COMPLETE`
- Owner: root; Worker: independent Luna/medium reviewer.
- Dependencies: CQ-06.
- Exit gate: all retained questions and lessons reviewed for grounding, relevance,
  answer-key validity, distractor plausibility, ambiguity, duplication and coverage;
  TypeSafe remains DEV-only report-only; root checks every severe finding against source.

### CQ-09 — Candidate verification and graph comparison

- Status: `COMPLETE`
- Owner/Writer: root.
- Dependencies: CQ-07, CQ-08.
- Exit gate: focused, contract, neighboring and full risk-based suites pass; Graphify
  updated once and compared with the module map; exact candidate SHA created and read back.

### CQ-10 — DEV human-path acceptance

- Status: `NOT_STARTED`
- Owner: root; canonical Test Runner may execute the packet.
- Dependencies: CQ-09.
- Exit gate: one realistic PDF and one complete XLSX run through the methodologist path;
  progress/timings/artifacts inspected; synthetic state cleaned; no unresolved P0/P1.
- Approval gate: existing DEV authority only; no paid/billing change.

### CQ-11 — Exact-SHA production release and readback

- Status: `NOT_STARTED`
- Owner: root; canonical Release Runner is the only delegated deploy worker.
- Dependencies: CQ-10.
- Exit gate: exact immutable revision deployed; API/worker/frontend identity read back;
  bounded synthetic flow passes; rollback remains available.
- Approval gate: current request authorizes the agreed release sequence; any changed
  target, billing, destructive action or customer mutation requires a new exact gate.

### CQ-12 — Measure process cost and close the epic

- Status: `NOT_STARTED`
- Owner/Writer: root.
- Dependencies: CQ-11.
- Exit gate: manual CodeBurn then Caveman portrait records root/children, model mix,
  calls, tokens, context, correction rounds and result quality; durable facts moved to
  canonical sources; temporary graph removed only after all completion gates pass.

## Decisions and approvals

| ID | Decision or exact approved mutation | Evidence | Owner | State |
|---|---|---|---|---|
| DEC-01 | Execute the full proposed quality closed-loop plan | `OWNER-CONFIRMED` 2026-09-19 | Product owner | USED |
| DEC-02 | TypeSafe is development-only and never a client runtime dependency | `OWNER-CONFIRMED` prior product decision | Product owner | ACTIVE |
| DEC-03 | Bad questions may be deleted; quotas must not be padded | `OWNER-CONFIRMED` prior product decision | Product owner | ACTIVE |
| DEC-04 | Use at most two concurrent leaf workers in this epic | Project contract | Root | ACTIVE |

## Completion gate

- [ ] Required nodes satisfy their exit gates.
- [ ] No overlapping writer or unreviewed external mutation remains.
- [ ] Cleanup and residual-state audit pass.
- [ ] Exact production revision and user-visible flow are independently confirmed.
- [ ] Durable facts move to canonical documentation.
- [ ] Temporary task graph is removed after transfer.
