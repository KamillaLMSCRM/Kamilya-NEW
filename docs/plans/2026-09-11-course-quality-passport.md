# Course quality and document passport plan

Status: slices 1-7 and 9 implemented and locally verified on
`feat/course-quality-passport-20260911`; DEV human-path re-acceptance is pending.
Production is unchanged until every mandatory gate below passes.

Local gate evidence: API unit suite `1275 passed`; web suite `578 passed` in
`111` files; focused generation UI `14 passed`; Next.js `15.5.23` production
build passed; Python quality baseline passed at `ruff=1066`, `mypy=2339` with
no new violations; `git diff --check` passed.

## Current acceptance ledger

| Slice | State | Current evidence |
| --- | --- | --- |
| 1. Workbook structure | accepted locally | real XLSX-to-chunks test preserves two worksheet identities; bounded row/cell/output guards pass |
| 2. Document passport | accepted locally | primary/supporting/unknown roles, hostile-name escaping and capacity tests pass |
| 3. Adaptive size | accepted locally | supporting-row growth does not increase lesson count; legacy fallback remains covered |
| 4. Optional course intent | accepted locally | empty value is valid; provided value reaches the architect and resume path; RU/KK/EN UI passes |
| 5. Passport-led architecture | accepted locally | every high/medium-confidence spreadsheet lesson must cite a primary worksheet; low-confidence classification remains advisory; semantic results retain primary evidence |
| 6. Question quality | accepted locally | both reported patterns and expanded RU/EN variants are rejected before persistence |
| 7. Lesson quality | accepted locally | one bounded rewrite, fail-closed second failure, and checkpoint policy-version tests pass |
| 8. Human path | re-test required | first exact-SHA DEV run proved upload, indexing, passport, generation and cleanup, but correctly remained NO-GO after content review found repeated facts across lessons |
| 9. Course-wide assessment diversity | accepted locally | normalized source-evidence plus correct-answer keys are carried across generated and restored lessons; batch and focused recovery reject repeats |

## Outcome

Large or structurally complex sources must produce a useful editable course even
when the methodologist gives no extra instructions.  Optional intent may refine
the result, but it must never be required for generation.  A technically valid
job is not accepted when its lessons or questions are pedagogically unusable.

## Test seams

Tests exercise five stable interfaces: document conversion, `DocumentPassport`,
`CourseStructureRecommendation`, lesson quality admission, and
`validate_question_set`.  LLM responses are replaced only at the external model
seam.  Production databases, providers and customer documents are not fixtures.

## Vertical slices and acceptance

### 1. Preserve workbook structure

- Convert XLSX locally after the existing OOXML safety preflight.
- Emit a stable heading for every visible worksheet and retain row boundaries.
- Keep blank sheets out of the learning source without renumbering other sheets.

Acceptance:

- A synthetic workbook with `Collections` and `Catalog` exposes both names in
  converted Markdown and metadata.
- The catalog cannot inherit the collections heading.
- Existing TXT, Markdown, CSV, DOCX and PDF conversion tests remain green.

### 2. Build an automatic document passport

- Classify source sections as `primary`, `supporting`, or `unknown` from bounded,
  deterministic structural signals.
- Record section size, distinct rows, repeated-row share, reference-list signals,
  confidence, warnings, and an estimated count of teachable units.
- If evidence is ambiguous, keep generation possible and report low confidence;
  never silently discard a section.

Acceptance:

- In the Plus-shaped synthetic fixture, the compact collections sheet is primary
  and the much larger SKU catalog is supporting.
- Increasing only supporting catalog rows does not inflate teachable capacity.
- A one-sheet ordinary document remains primary and produces a usable passport.
- Passport rendering contains roles and aggregate counts, never omitted sources.

### 3. Recommend course size from meaning, not raw chunks

- Prefer passport teachable units over raw chunk count.
- Retain current format caps and explicit manual module override.
- Estimate total duration as the sum of bounded lesson-duration ranges.

Acceptance:

- The Plus-shaped fixture does not become a 31-lesson course because of 932
  catalog chunks.
- Small sources are not padded to 8-14 lessons.
- Brief, standard and detailed profiles remain monotonic and capped.
- Existing callers without a passport preserve backward compatibility.

### 4. Let the methodologist refine, without making input mandatory

- Add optional `course_intent` to the generation request.
- Show the automatic interpretation before generation and allow a short correction.
- Pass the correction to the architect as instruction, never as factual source.

Acceptance:

- Empty intent still queues generation.
- A provided intent is bounded, stored with job parameters, restored on resume,
  and visible in the architect request.
- Source text remains the only factual authority.
- RU, KK and EN UI labels and request-shape tests pass.

### 5. Make the passport authoritative for course architecture

- Include the passport and source-role rules in the direct-source architect input.
- Require every high/medium-confidence primary section to be covered by at least
  one lesson; keep low-confidence classification advisory so generation remains possible.
- Supporting sections may provide examples and evidence but cannot dominate lesson
  allocation solely through row count.

Acceptance:

- Architect prompt identifies primary and supporting sections explicitly.
- A returned structure omitting a primary section is rejected and gets one bounded
  correction attempt.
- No selected document is omitted and existing source provenance remains intact.

### 6. Reject pedagogically broken questions

- Block meta-prompts such as "What is this lesson about?".
- Block question/answer equality and explanation/question restatement.
- Reject generic or source-unrelated distractors without banning legitimate
  source-backed options that differ by one meaningful number or term.
- Preserve source grounding, language and exactly-one-answer contracts.

Acceptance:

- Both bad examples reported by Plus fail deterministically.
- Valid concrete scenario questions continue to pass.
- Generation retries from immutable lesson evidence and fails closed after its
  bounded budget; bad questions are never persisted as successful output.

### 7. Enforce lesson quality before assessments

- Make deterministic source grounding and filler checks authoritative; keep the
  existing model reviewer as additional advisory evidence.
- Retry one rejected lesson from the same immutable evidence with actionable
  feedback.
- If the retry still fails, stop automatic completion with a stable safe error;
  do not proceed to quiz generation or course persistence.

Acceptance:

- Generic introduction/outro filler and source-poor lessons are rejected.
- One corrected lesson replaces only its own position and checkpoint.
- A second failure stops before assessment and save.
- Resume never restores a checkpoint that predates the quality-policy version.

### 8. Full synthetic human-path acceptance

- Upload a generated two-sheet XLSX through the normal document interface.
- Observe passport, accept defaults, generate, open the draft, inspect every lesson
  and question, then clean up only the synthetic objects.

Acceptance:

- No production customer fixture, PII or external-provider secret is used.
- Course covers the primary collections and uses catalog entries only as examples.
- Zero meta questions, question/answer equality, tautological explanations,
  source-unrelated distractors, duplicate prompts, or failed lesson gates.
- Every lesson has source references; every quiz remains `needs_review` until a
  methodologist approves it.
- Exact SHA, CI, image, migration, API, worker and browser readback are recorded
  before any production release is called complete.

The DEV gate requires two independent generations from a fresh upload with an
empty optional course intent. Both runs must pass the deterministic report and
bounded human review; one successful stochastic response is not release proof.

### 9. Prevent the same fact from being tested in several lessons

- Carry normalized `(authoritative source excerpt, correct answer)` identities
  through the entire course assessment pass.
- Seed the identity set from restored checkpoints before generating missing
  assessments, so resume cannot reintroduce an already tested fact.
- Tell both batch and focused recovery prompts which relevant facts were already
  assessed, while keeping the prompt bounded to evidence available to the current
  lesson.
- Keep distinct questions about different facts from the same source excerpt
  valid; reject only the same evidence-and-answer pair.

Acceptance:

- A repeated fact from an earlier lesson is rejected and omitted during bounded
  recovery.
- A later lesson with different evidence remains a single provider call and
  preserves progress reporting.
- Existing completed checkpoints contribute their facts before resumed work.
- The full API unit suite and two independent DEV human-path runs pass with zero
  repeated fact identities and zero repeated question prompts.

## Release decision

Do not roll back session and resumability fixes.  Ship this work as a focused
quality release only after slices 1-7 are green locally/DEV and slice 8 passes in
the approved synthetic environment.  Rebuild the Plus course after release; do
not publish the existing low-quality draft.
