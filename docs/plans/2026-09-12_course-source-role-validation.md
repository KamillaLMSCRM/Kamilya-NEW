# Course source role validation repair

Status: released and independently accepted in KZ production as version `0.5.4`
Date: 2026-09-12
Baseline: `origin/master` at `a507e17b22b170f23c143a2a77182becb273636c`
Root owner: Codex root orchestrator
Product owner / approver: workspace owner, instruction `делай`, 2026-09-12

## Observable outcome

An ordinary methodologist can generate a grounded draft from a complex workbook
without optional guidance. A supporting worksheet may enrich lessons that remain
grounded in primary material, while a standalone lesson whose subject is only a
supporting catalog remains rejected.

## Current evidence and uncertainty

- SOURCE-DERIVED: `run_direct_architect` is the caller-facing seam for structure
  creation and validation.
- SOURCE-DERIVED: `_validate_structure_sources` currently rejects a structure-wide
  named reference to a supporting worksheet and catalog-like lesson-title terms.
- SOURCE-DERIVED: a no-guidance tabular plan can be built and validated without an
  LLM architect call.
- NOT VERIFIED: the production job that emitted
  `direct_source_supporting_section_promoted` failed because of a model response.
- NOT VERIFIED: the same job failed because of a false-positive validator result.
- GRAPH GAP: this clean worktree has no `graphify-out/graph.json`; source and tests
  are used for bounded confirmation, and this gap is not treated as evidence that
  no dependency exists.

## Ranked falsifiable hypotheses

1. The structure-wide named-section check rejects valid primary-grounded enrichment.
   Prediction: a plan whose lesson cites primary headings but describes examples
   from a supporting sheet fails with `direct_source_supporting_section_promoted`.
2. The catalog-title keyword check rejects legitimate primary material whose actual
   instructional subject is a catalog or assortment. Prediction: a primary-only
   workbook with a legitimate catalog title is rejected despite no supporting
   section being promoted.
3. The reported error is correct and the source plan genuinely makes the supporting
   sheet a standalone topic. Prediction: a minimized valid-enrichment fixture passes
   while the captured rejected structure still violates the invariant.
4. The deterministic no-guidance plan, not the LLM repair loop, emits the rejected
   structure. Prediction: the failing fixture records zero LLM calls.

## Module and interface

Module: direct-source course architecture and source-role validation.

Interface under test: `run_direct_architect(llm, corpus, ...) -> CourseStructure` or
a stable `DirectSourceError` code. Internal matching helpers are implementation,
not the test seam.

Responsibility: produce and validate a course structure grounded in selected source
documents and the current document passport.

Non-responsibilities: document parsing, embedding/provider routing, lesson prose,
assessment generation, persistence, quotas, publication, deployment, and tenant
authorization.

Data ownership: stateless in this repair; the module consumes the immutable corpus
and returns a structure. It does not change DB state.

## Invariants

- Every lesson cites selected document IDs and at least one required primary source
  heading when passport confidence is medium/high.
- Supporting material may provide examples or attributes inside a primary-grounded
  lesson when the source relationship is explicit.
- A lesson whose instructional subject is only a supporting catalog is rejected.
- A worksheet name, quotation mark, or generic word such as catalog is not by itself
  proof that the supporting worksheet became the instructional subject.
- Blank optional guidance does not block generation when the source has teachable
  primary content.
- Existing document selection, lesson limits, unsupported business-relationship
  checks, cancellation, checkpoint, tenant, provider, and publication behavior stay
  unchanged.

## Impact matrix

| Existing module or journey | Impact | Required evidence |
| --- | --- | --- |
| `direct_source` architecture | Invariant implementation | red/green public-seam tests |
| document passport | Consumer only | existing passport tests stay green |
| source topic map | None expected | no changed dependency; existing focused tests |
| lesson writer and quality | None expected | negative-space focused tests |
| assessment generation | None expected | no files or interfaces changed |
| `AI-COURSE-01` | Observable generation admission | required journey contract test set before release |
| DB, RLS, quotas, provider routing | None | no files/config/schema/network changes |

## Work and gates

1. Create a deterministic public-seam regression that is red on the exact valid
   enrichment behavior. Preserve a real standalone-supporting-topic negative.
2. Minimize the fixture and confirm which hypothesis it proves; do not infer the
   production cause from the shared error code.
3. Apply the smallest implementation change behind the existing interface.
4. Run the new test, all direct-source/passport tests, then the AI course critical
   journey command from its machine contract.
5. Independently review requirements, correctness, standards, and complexity.
6. Update `ERRORS.md` only after cause, fix, and verification are confirmed; add a
   user-visible `[Unreleased]` changelog item if the behavior changes.
7. Update Graphify after code changes only if the canonical repository index is
   available and safe to update. A missing graph is reported, not silently invented.

## Stop conditions

- The behavior requires changing document-passport ownership, persistence, API
  schemas, provider routing, or another unlisted module.
- A correct public-seam regression cannot reproduce the false-positive behavior.
- Fixing the case requires weakening primary grounding or accepting a standalone
  supporting-catalog course.
- Existing unrelated changes appear in this clean worktree.
- A required critical-journey test would need to be skipped or weakened.

## Release boundary and rollback

The initial plan produced a verified local candidate and did not itself authorize
production work. The owner subsequently approved the exact `0.5.4` release. The
deployed repair remains stateless and required no database migration. Rollback is
the retained previous immutable image and release-plane configuration; no data
rollback is expected.

## Verification result

- RED: a valid primary-grounded lesson that named a supporting worksheet only in
  its explanatory description failed with
  `direct_source_supporting_section_promoted` before the repair.
- GREEN: the public-seam regression passes in one architect call, while existing
  standalone-supporting and missing-primary-heading negatives remain green.
- Changed-module direct-source/passport suite: 28 passed.
- Complete API unit suite: 1407 passed with five existing deprecation warnings.
- Remaining database-free AI-COURSE-01 tests: 5 passed.
- Ruff check and format check: passed for every changed Python file.
- Targeted mypy reached the repository baseline and reported 96 pre-existing
  errors in imported modules; no new error was reported in the changed passport
  policy or validator block.
- Isolated Supabase DEV application gate
  `HBR-DEV-APP-20260912T054348Z`: READY; disposable schema removed; public
  revision `0158` and shared metadata unchanged.
- Local, network-free aggregate check of the complete owner-provided workbook:
  644,776 converted characters, 926 chunks, confidence high, eight teachable
  units; the compact learning sheet remained primary and the much larger balanced
  reference sheet remained supporting.
- Graphify remains unavailable in this clean worktree because the canonical graph
  artifact is absent. No graph-derived completeness claim is made.

## Production acceptance result

- Release/tag SHA: `b322fa9c212bdbb8912e0b60f2d77d26bccab4fe` / `v0.5.4`.
- CI `34676746090` and protected production workflow `34678758147`: passed.
- Immutable production image:
  `ghcr.io/kamillalmscrm/kamilya-api@sha256:56bd1b48b4ef104195b095b0c11bf640dd47ec8eb356abdfe39afc2098ebacbd`.
- Public and private health: version `0.5.4`, exact release SHA,
  `kz-production`.
- API, worker-ai, worker-documents and worker-ops: running the same exact image,
  zero restarts and zero bounded fatal-pattern matches in the first 15 minutes.
- CT125: unchanged revision `0158`; disposable restore drill passed and cleanup
  was independently confirmed.
- Deployed-code synthetic smoke: primary/supporting classification passed; an
  invalid catalog-driven objective triggered repair and the corrected
  primary-grounded structure was accepted. No provider call or database write.
- Operational watchdog: exact release/image reconciled, one-shot passed, timer
  active; prior watchdog configuration and previous application image retained
  for rollback.
- Final boundary: the known source-role false positive is closed. Methodologist
  review remains required because source-role validation is not a guarantee of
  perfect lesson wording or assessment quality for every arbitrary workbook.
