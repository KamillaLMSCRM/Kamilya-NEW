# Course generation live UX remediation

Status: local implementation and representative-source acceptance complete;
DEV and exact-SHA release gates pending

Baseline: production exact SHA `e231e5fa97e4c0223b0d2e75845d2c2b2d31c7f9`

## Objective

Remove the confirmed lesson-content truncation risk, make privileged course preview
fully usable without learner evidence writes, and improve generated lesson and quiz
quality without padding a course to arbitrary lesson or question counts.

## Confirmed test seams

1. `EditableLesson`: opening an editor by lesson id loads full content; preview
   excerpts can never be persisted as lesson content.
2. `QuizScoring`: the same scoring rules support a persistent learner submission
   and a non-persistent privileged preview submission.
3. `CourseDraftQuality`: generated lessons remain traceable to meaningful source
   material and reject learner-visible meta/instruction leakage.
4. `AssessmentQuality`: invalid or duplicate questions are removed; recovery never
   invents questions merely to reach an arbitrary count.

Tests must exercise observable behavior at these seams, not internal call order.

## Ownership

| Owner | Writable scope | Forbidden |
| --- | --- | --- |
| Backend worker | `apps/api/app/modules/courses`, `apps/api/app/modules/quizzes`, `apps/api/app/modules/ai`, focused API tests | frontend, docs, Git, deployment, external systems |
| Frontend worker | `apps/web/src/app/ai/generate`, `apps/web/src/app/courses`, focused web tests and translations required by those screens | backend, docs, Git, deployment, external systems |
| Root | integration, shared contracts, canonical docs, final tests, Git and release packet | unreviewed production mutation |

## Vertical slices

### Slice 1: safe lesson editing

- Add a failing web test proving that a preview excerpt is not used as editable
  content.
- Load the full lesson before displaying an editable form.
- Keep excerpts read-only and make the distinction explicit in the response/client
  types.
- Add conflict protection using the existing lesson update contract if available;
  otherwise record it as a separate compatible slice rather than inventing a
  migration.

Acceptance: a long lesson survives open/cancel and open/save unchanged byte for
byte; a literal truncation ellipsis is never persisted.

### Slice 2: privileged quiz preview

- Add a failing API contract test proving that privileged preview returns a score
  while creating no learner attempt, progress, enrollment, certificate or training
  evidence.
- Extract one scoring module used by both preview and learner submission.
- Add a tenant-scoped privileged preview interface.
- Add a separate authoring-only preview route. Show the methodologist selected
  and correct choices and explanations after scoring, while keeping answer keys
  and review-mode code entirely out of the learner route.

Acceptance: a methodologist can traverse a draft, submit all answers, inspect the
selected and correct choices, retry, and return to the course without learner
state mutations. A learner cannot open the authoring preview or receive answer
keys through the learner screen.

### Slice 3: lesson and assessment quality

- Extend the existing writer and shared question-validation modules rather than
  adding parallel validators.
- Reject meta lessons/questions and heading-content contradictions with bounded
  reason codes.
- Base question capacity on independent source evidence; keep fewer valid questions
  when source capacity is low.
- Preserve source traceability and fail closed when no acceptable content remains.

Acceptance: the small synthetic source has no meta lesson, no contradictory
heading/body pair and no unrelated distractor; removing a bad question does not
trigger count padding.

### Slice 4: UX and help

- Correct loading/empty states and generation-result actions.
- Make edit/preview modes explicit and improve editor width/Markdown rendering.
- Remove hard-coded language from touched screens and update RU/KK/EN strings.
- Make help route-and-mode specific.

## Verification ladder

1. Focused red-green tests per slice.
2. Backend and frontend contract suites.
3. Graphify update and affected-path review.
4. Local deterministic replay fixtures.
5. Production-equivalent local generation with the small text, Lombard PDF and
   Plus Excel sources; TypeSafe remains development-only evaluation.
6. Supabase DEV/test-contour integration and browser acceptance in the synthetic
   tenant.
7. Test Runner exact-SHA packet.
8. Release Runner exact-SHA packet only after all prior gates pass.

## Stop conditions

- No production deployment from a dirty or unreviewed checkout.
- No claim of completion from HTTP 200, unit tests or an agent handoff alone.
- Any cross-tenant access, lesson-content corruption or preview evidence write is a
  release blocker.

## Local acceptance evidence

- TDD regressions cover full-lesson editing, privileged non-persistent scoring,
  invalid answer-key rejection and assessment-only lesson removal.
- API suite: `3055 passed`, `489 skipped`; web suite: `121` files and `656`
  tests passed. Frontend typecheck, zero-warning lint and production build passed.
- The production frontend build contains a dedicated dynamic
  `/courses/quiz/[quizId]/preview` route. Its focused role/privacy/navigation
  tests pass, while the learner route remains aggregate-result only.
- Plus Excel: `publishable=true`, 3 lessons, 8 accepted questions, source-topic
  coverage 3/3, no provider or deterministic fallback.
- Lombard PDF: converted through the active VM126 production Docling route,
  `publishable=true`, 15 lessons, 29 accepted questions, source-topic coverage
  13/13, no provider or deterministic fallback.
- Root manually reviewed every retained answer set in both representative runs.
  Rejected candidates were deleted or boundedly repaired; no quota padding was
  used.
