# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

### Changed

### Fixed

### Security

## [0.11.0] - 2026-09-24

### Added

- Add a methodologist action center that turns current learner issues and
  privacy-safe weak-question signals into owned, dated actions with durable
  baseline and outcome snapshots.
- Add explicit observed, manual and cancelled closure paths with append-only
  event history and explanations for manual outcomes or cancellation.

### Changed

- Restrict course question analytics to the current enrollment occurrence so
  predecessor attempts remain historical evidence without changing the active
  cohort.
- Keep multiple action types available for one issue while preventing duplicate
  open actions of the same type.

### Fixed

- Distinguish an attempted quiz with no passing attempt from a quiz that has
  already been passed when classifying learner attention signals.
- Preserve an empty department scope as an empty analytics cohort and visibly
  warn when a bounded action-center result is partial.
- Keep the canonical API pytest wrapper from splitting a single selector into
  individual characters.

### Security

- Enforce tenant ownership for action targets, owners, creators and event actors
  with FORCE RLS, restricted runtime grants and cross-tenant negative checks.

## [0.10.2] - 2026-09-23

### Added

- Add a synthetic four-seam course-quality corpus and bounded local probe for checking document conversion, source mapping, lessons and questions without tenant data or database writes.

### Changed

- Bind lessons and questions more closely to the source's semantic blocks and labelled spreadsheet facts; keep assessment length proportional to independently testable material.
- Make Evidence V2 the only executable course-generation engine; retire queued
  jobs created for older engines instead of silently replaying them.
- Apply the requested lesson ceiling to Evidence V2 without padding small
  sources or dropping admitted source facts.
- Group repeated worksheet attributes under one learner-facing heading and
  prefer distinct tabular attributes when selecting bounded quiz questions.

### Fixed

- Keep a sole title-matching narrative section as teachable material, and classify a small named nomenclature sheet as supporting when a stronger learning sheet is present.
- Prevent unlabelled or mismatched workbook values in lessons, duplicate short rules, unsupported lesson metadata, off-topic answer choices and misleading question premises.
- Keep the DEV course-quality acceptance fixture pinned to the committed expanded workbook and derive collection focus terms from its current primary-sheet layout.
- Drop repeated worksheet questions with the same attribute and correct answer
  instead of regenerating or padding the quiz.
- Validate DEV course generation from the exact Evidence V2 state instead of
  obsolete architect/writer path counters, and avoid treating a one-question
  quiz as vulnerable to a fixed-position answering strategy.
- Add a fail-closed local API pytest runner that always uses the canonical
  project environment and API working directory, never ambient Poetry.

### Security

## [0.10.1] - 2026-09-22

### Added

- Show clearer learning-cycle statuses and contextual help so a methodologist
  can distinguish recurring rules, corrective assignments and current learner
  outcomes without knowing the internal data model.
- Show real employee and course limits in the superadmin tenant view instead of
  placeholder denominators.

### Changed

- Restore an interrupted AI-generation job only for the signed-in user who
  started it, and clear a stale completed result when a new generation starts.
- Display complete organization-unit breadcrumbs in staff selectors, including
  nested units with the same local name.

### Fixed

- Reject generated multiple-choice distractors that belong to a different
  scenario than the question and stop padding a quiz merely to reach a target
  question count.
- Restore the superadmin identity atomically when leaving tenant preview and
  prevent the tenant profile route from exposing a misleading impersonated
  profile during the transition.
- Deduplicate organization units by their full hierarchy path instead of their
  leaf name, so legitimate same-named units in different branches remain
  selectable.
- Keep AI-generation progress and retry state consistent after reload, account
  switching and a new run.

### Security

- Scope resumable AI jobs to the authenticated user as well as the tenant.
- Fail closed on the tenant profile endpoint while a superadmin preview token is
  active; no new database migration, secret, provider or billing change is
  required.

## [0.10.0] - 2026-09-22

### Added

- Let a methodologist explicitly assign the same course again with a required
  reason while preserving the learner's previous completion and quiz history.
- Add current/history switching to the training journal and expose failed,
  exhausted-attempt, repeated, cancelled-history and superseded-history counts
  on the main methodologist dashboard.

### Changed

- Treat every manual repeat as a new enrollment occurrence bound to the current
  published course release. Attempt limits start again only for that new
  occurrence.
- Keep operational assignment lists and statistics on the current occurrence;
  retained predecessors appear only in the explicit history view.
- Bind lesson progress, quiz availability, SCORM activity and certificates to
  the new occurrence while preserving legacy one-time progress in place.
- Reissue the predecessor's delivery mode for the new occurrence: durable email
  notification or a fresh protected-link secret, with equivalent relative
  access-window durations.

### Fixed

- Prevent cancelled, superseded or completed predecessor rows from inflating
  current training totals after a repeat assignment.
- Prevent a repeated course from inheriting or overwriting lesson progress from
  the previous occurrence.
- Scope SCORM activity to the exact enrollment occurrence in the training log.
- Keep learning-path progress scoped to its path enrollment after centralizing
  occurrence selection.

### Security

- Validate predecessor, learner, course and methodologist ownership in both the
  API transaction and a tenant-aware database trigger under FORCE RLS.
- Reject rule-owned and stale historical assignments from the manual repeat
  workflow.

## [0.9.2] - 2026-09-22

### Added

- Let methodologists and superadmins answer draft quiz questions in an explicit
  preview route without creating learner attempts, progress or completion data.
- Show selected and correct choices plus the authoring explanation after a
  non-persistent preview submission.

### Changed

- Load the complete generated lesson before editing instead of treating the
  shortened course-preview excerpt as editable source text.
- Keep a generated course proportional to meaningful source material and reject
  lessons whose only purpose is a quiz, test or learner acknowledgement.

### Fixed

- Reject quiz previews whose questions have no valid answer key instead of
  accepting an empty selection as a correct answer.
- Keep privileged quiz previews free of learner timers, access-window checks and
  course-completion actions.
- Keep answer keys and answer-review code out of the learner quiz route.

### Security

- Privileged quiz preview remains tenant-scoped and restricted to authoring roles. It uses
  the same scoring rules as learner submission but performs no evidence writes.
- No database migration, secret, billing, DNS, storage or provider-route changes.

## [0.9.1] - 2026-09-22

### Fixed

- Protect an unsaved lesson draft when a methodologist leaves the course editor
  through global tenant navigation, including the persistent sidebar.

### Security

- No database migration, secret, billing, DNS, storage or tenant-isolation
  boundary changes.

## [0.9.0] - 2026-09-22

### Added

- Add a full-page course authoring workspace with a persistent lesson outline,
  readable Markdown preview and a learner-view shortcut.
- Add a dedicated learning-cycle operations screen for recurring course and
  program rules, latest-period status, reminders and corrective assignments.
- Show the effective assignment deadline and certificate validity in the
  training journal and CSV export.

### Changed

- Load all available published courses and active learners in learning-cycle
  selectors instead of silently truncating them at the first API page.
- Keep immutable recurring-cycle deadline reporting separate from a one-time
  assignment deadline.

### Fixed

- Protect unsaved lesson edits when leaving through the course title,
  approvals, another lesson or learner preview.
- Select the latest issued certificate deterministically when a certificate
  was reissued for the same enrollment.

### Security

- All new reporting joins remain tenant-scoped and read-only. Database
  migrations, new secrets, billing changes and provider changes are not
  required.

## [0.8.2] - 2026-09-21

### Fixed

- Apply an explicit `lang` parameter when the public demo-role page is opened
  directly, not only after visiting another localized page first.
- Preserve the selected language on the demo-role page links back to sign-in
  and forward to tenant registration.

### Security

- No database migration, secret, billing, DNS, storage or tenant-isolation
  boundary changes.

## [0.8.1] - 2026-09-21

### Fixed

- Keep the selected language on every exit from the public learning example,
  including registration, demo workspace, sign-in and the Kamilya logo link.
- Synchronize the public example language with the global accessibility copy so
  the skip-to-content link is shown in English on the English route.

### Security

- No database migration, secret, billing, DNS, storage or tenant-isolation
  boundary changes.

## [0.8.0] - 2026-09-21

### Added

- Add English as a supported language across the public landing pages and the
  primary tenant, learner, authentication, demo and superadmin workflows.
- Preserve the selected language through login, registration, invitations,
  public access links and campaign-to-trial transitions.

### Changed

- Keep advertising attribution parameters when a visitor moves from the
  landing page to tenant registration or the demo cabinet.
- Present generated course content in a wide editor with a localized,
  learner-facing Markdown preview.
- Localize the current staff hierarchy, position qualification, course
  assignment, assessment and AI-generation workflows without removing their
  production behavior.

### Fixed

- Make the public learner demo resilient when no prepared learner account is
  available, while preserving tenant isolation and synthetic-only demo data.
- Keep direct-source course generation usable when an embedding provider is
  unavailable and report the selected compatibility mode to the methodologist.
- Preserve recurring-reminder controls and organization-hierarchy behavior
  during the localization merge.

### Security

- No new secret, billing, DNS, storage or tenant-isolation boundary is
  introduced. Database migrations are not required.

## [0.7.7] - 2026-09-19

### Fixed

- Describe the source-based lesson count as an approximate planning guideline,
  not as a hard maximum that the authoritative full-source analysis must obey.

## [0.7.6] - 2026-09-19

### Changed

- Limit generated assessment density to at most three retained questions per
  learner-visible lesson, selected fairly across its semantic source blocks.
- Treat questions that still fail the bounded quality-review cycle as explicit
  audited omissions instead of padding the test or blocking an otherwise safe
  course.

### Fixed

- Reject sentence-shaped distractors when the source-owned answer is a concise
  categorical value, and normalize bare numeric answer choices so formatting
  cannot reveal the correct option.
- Keep lightweight upload admission estimates advisory in the production-shaped
  acceptance runner; the worker-owned source passport remains authoritative.
- Report derived source axes separately from axes actually sent for assessment
  generation, so progress and usage evidence are not inflated.

### Security

## [0.7.5] - 2026-09-19

### Changed

- Bind every generated test item to one server-owned source axis and preserve an
  explicit retained, omitted, unassessable or uncovered outcome for every
  assessable source claim.
- Treat assessment volume as a consequence of useful source material: unsafe,
  redundant and low-value questions are omitted without filling a numeric quota.

### Fixed

- Reject answer options copied from a different source function, a different
  clause of the same compound fact or an unrelated attribute, even when each
  option is independently true in the source.
- Exclude OCR unreadability markers, unfinished answer keys and internal
  placeholder prompts from learner-visible courses and tests.
- Require an explicit methodologist-review result when the assessment audit is
  incomplete or a source topic remains uncovered.

## [0.7.4] - 2026-09-19

### Fixed

- Preserve executable Git modes for the production-equivalent Docling preflight
  and capture helpers so the repository shell-policy gate can execute them.

## [0.7.3] - 2026-09-19

### Added

- Add development-only semantic assessment and objective-alignment evaluators
  for replaying generated courses without sending tenant documents to TypeSafe.

### Changed

- Generate course tests from coherent source blocks, retaining conditions and
  exceptions instead of using unrelated source statements as answer options.
- Adapt lesson and test volume to available information without a minimum quota.
- Derive safe binary checks from explicit source rules and bind every generated
  question to one assessed source axis before accepting model-written options.

### Fixed

- Review every generated answer option for relevance and ambiguity, repair a
  rejected question once within its original topic, and omit invalid questions.
- Preserve a course as an accessible draft when no valid test questions remain;
  do not report successful completion or offer to resume that saved review outcome.
- Reject dependent sentence fragments, cross-topic distractors, unsupported
  exclusions and semantically duplicated questions without padding a quota.
- Keep valid categorical alternatives when a broad model review incorrectly
  collapses distinct styles, materials, colours or mechanisms into one error.
- Require the production-equivalent Docling route for live local PDF acceptance
  instead of silently substituting a different converter.

### Security

## [0.7.2] - 2026-09-18

### Changed

- Build narrative courses in source order with section-preserving lesson groups
  bounded by both evidence count and source-word volume, so large regulations
  remain editable without padding small sources to a fixed lesson quota.
- Use supporting catalogue worksheets to enrich the primary curriculum without
  letting their row count inflate the number of lessons.

### Fixed

- Reject implausible or invalid deterministic course plans before embedding or
  content-provider calls instead of spending provider capacity on a draft that
  cannot pass final validation.
- Preserve authoritative numbered headings while keeping sentence-like numbered
  list items inside their real source section.
- Remove low-value identifier and dimension recall questions, answer-revealing
  subjects, repeated attribute-answer pairs, and overlapping answer options
  without generating artificial replacements.
- Keep the input reservation for Evidence V2 large enough for the accepted
  content-derived course plan while retaining bounded provider requests.

## [0.7.1] - 2026-09-17

### Fixed

- Build the organization-unit response before committing create and update
  requests, preserving the transaction-local tenant RLS context and preventing
  a false HTTP 500 after the database write has already succeeded.
- Add route-level regression coverage for create and update readback ordering,
  closing the gap between migration/service tests and the production HTTP path.

## [0.7.0] - 2026-09-17

### Added

- Add organization structures of arbitrary practical depth with explicit unit
  types for organizations, branches, management units, divisions, departments,
  sectors, teams and other tenant-defined levels.
- Add an explicit central-office marker, recursive structure search and
  breadcrumbs, and a server-validated move preview that reports affected units,
  positions and employees before a subtree is moved.
- Add a generic hierarchy import contract while preserving the existing
  branch/department spreadsheet adapter.

### Changed

- Keep an employee's required position independent from their optional
  organization-unit placement, so one position profile can be used in several
  branches or by an employee without a department.
- Resolve training rules, learning-program audiences, qualification inheritance,
  AI audience suggestions, training-log filters and evidence paths through the
  complete active organization subtree.
- Replace branch/department-specific structure rendering with one recursive tree
  that supports creation, editing, movement and archival at every level.

### Fixed

- Reject direct database moves that would keep the moved root within the depth
  limit while pushing one of its existing descendants below the limit.
- Keep explicit empty employee placement from being silently restored through a
  legacy position-to-department hint.

### Security

- Enforce tenant ownership, cycle prevention, maximum depth, one active root
  central office, restricted runtime grants, RLS and FORCE RLS for the expanded
  organization hierarchy and employee placement.

## [0.6.3] - 2026-09-17

### Fixed

- Show all existing positions immediately in the manual employee modal instead
  of hiding them until a department is selected. Selecting a department-linked
  position fills its department automatically, while positions and newly
  created employees may remain without a department.
- Stop creating an empty department record when a manual employee is assigned
  to an existing or new department-free position.

## [0.6.2] - 2026-09-17

### Fixed

- Allow a tenant administrator to create a new department and its required new
  position directly while adding an employee. The position field remains
  available for the new-department path, and the employee, department and
  position are submitted together through the existing atomic staff endpoint.

## [0.6.1] - 2026-09-16

### Fixed

- Ensure employees can download a complete printable course-confirmation form
  for training completions recorded before printable form snapshots were
  introduced. The learner PDF uses the tenant's current template only when the
  immutable historical event has no saved template; newer completions remain
  pinned to their completion-time template.

## [0.6.0] - 2026-09-16

### Added

- Allow a learner to download a course-level confirmation form, return a signed
  PDF/JPEG/PNG copy, and see its review state without sending the document
  outside Kamilya LMS.
- Allow a methodologist to attach a copy received through another channel,
  inspect it, accept it or request a replacement with a reason.
- Add tenant-level settings and a real PDF preview for the printable course
  completion form, with the effective form settings snapshotted at completion.
- Include accepted signed copies and their hashes in the private evidence ZIP.

### Changed

- Record lesson progress automatically when the learner moves forward, after a
  required quiz is passed, and when the final course action is completed.
- Use one assignment deadline across course lessons and required tests instead
  of asking the learner to confirm each lesson manually.
- Keep the server-side all-lessons gate while presenting one final **Complete
  course** action to the learner.

### Fixed

- Keep migration 0160 compatible with both the previous application's
  `received` scan status and the new `uploaded_pending_review` status so an
  application rollback remains operational.

### Security

- Make returned-copy reviews append-only and tenant-scoped with forced RLS,
  ownership validation, bounded file types and size, magic-byte validation,
  content hashes and impersonation denial.
- Exclude signed copies from public evidence shares; only private authorized
  evidence packages can contain an accepted returned copy.

## [0.5.56] - 2026-09-16

### Fixed

- Preserve ordinary numbered sections from plain-text documents when the source
  has no Markdown heading metadata, instead of collapsing the whole document
  into one lesson.
- Build an adaptive number of lessons from the actual volume and section
  structure without padding small sources to a fixed quota.
- Split prose into independently traceable facts so response times and similar
  values can produce source-grounded questions with unambiguous alternatives.
- Remove repeated questions that assess the same normalized value elsewhere in
  the course, and add a section question only when two safe source distractors
  exist.
- Exercise the active Evidence V2 production seam with the exact plain-text
  regression fixture, production chunking and empty methodologist guidance.

## [0.5.55] - 2026-09-16

### Fixed

- Apply the anti-collapse lesson floor in automatic sizing when a prose source
  has enough distinct, non-repetitive teachable material; genuinely small or
  highly repetitive sources remain eligible for a single lesson.
- Validate course-structure actions against ordinary prose source chunks when
  no worksheet headings exist, preventing grounded plans from being rejected
  because the permitted-text set was accidentally empty.
- Run bounded focused question recovery when a failed batch used any valid
  evidence ID and at least three evidence fragments are available, instead of
  requiring the malformed batch itself to cover three different fragments.

## [0.5.54] - 2026-09-16

### Fixed

- Keep a confidently classified source with several independent topics from
  collapsing into one catch-all lesson, while preserving source-derived upper
  limits and avoiding artificial lesson padding.
- Recover a minimum useful set of three distinct, evidence-bound questions
  when a model's first broad assessment is rejected, using bounded one-fact
  retries; retain an empty assessment when safe recovery is not possible.

## [0.5.53] - 2026-09-16

### Fixed

- Reject source-meta questions such as “what does the lesson material state”
  before a generated test can be saved; invalid questions are removed without
  padding the test to a quota.
- Retry lesson realization when provider output leaks internal question-writing
  instructions that are absent from the cited source facts.
- Keep the learner in the assignment session after the final quiz by returning
  to the course through client-side navigation instead of a full page reload.
- Require an explicit approved database URL for database-backed local tests;
  unit-only runs no longer attempt to connect to an invented localhost database.

## [0.5.52] - 2026-09-15

### Fixed

- Reject and neutralize marketplace comparisons that insert a short noun phrase
  between `compact` and `from a marketplace`, including the exact wording found
  during the production lesson-content acceptance of 0.5.51.
- Keep ordinary factual statements about marketplace publication unchanged.

## [0.5.51] - 2026-09-15

### Fixed

- Apply ambiguous-answer and learner-language checks to the active evidence-first
  V2 generation path before its single persistence boundary.
- Drop ambiguous source-owned questions without quota padding and retain an empty
  lesson assessment when no safe question remains.
- Reject model-authored sales-style phrases, neutralize the same known phrases
  when a provider outage requires a source-only fallback, and run a final
  publishability check over every learner-visible field.
- Version persisted V2 lesson and assessment quality metadata independently from
  the generation-engine identifier.

## [0.5.50] - 2026-09-15

### Fixed

- Drop a generated question when an incorrect option repeats the same attribute
  answer as the keyed option with different descriptive qualifiers.
- Keep unprofessional sales phrasing such as mixed-language `look`,
  “not toy-sized”, and “not from a marketplace” out of learner-visible lessons
  and answer options.
- Revalidate restored lesson and assessment checkpoints against the updated
  quality policies before they can be reused.

## [0.5.49] - 2026-09-15

### Added

- Generate a complete editable draft course and grounded tests from large or
  structurally complex source documents through the evidence-first V2 engine.
- Record exact lesson-stage progress while the course is being generated.
- Show the active embedding provider and explicit failover attempt beside exact
  indexing/generation progress.

### Changed

- Use the evidence available in the source to determine course scope instead of
  padding the draft to a fixed lesson or question count.
- Use the managed multilingual Voyage V4 embedding family first, with compatible
  model and private Qwen fallbacks; course generation remains available when
  semantic measurement is temporarily degraded.

### Fixed

- Batch lesson-search embeddings and keep document/query vectors in the same
  verified semantic space, preventing provider rate-limit storms and invalid
  cross-model similarity comparisons.
- Reject incomplete, generic, duplicate or unsupported course results before the
  existing transactional save instead of reporting a partially generated draft.
- Retry idempotent quota and AI-budget cleanup for already-cancelled generation
  jobs after transient failures.
- Mark deterministic source-only fallback lessons as `needs_review` and render
  source-controlled Markdown markers as inert text.

## [0.5.48] - 2026-09-14

### Fixed

- Remove Markdown table delimiters from lesson previews even when the API
  truncates a table row before its closing delimiter.

## [0.5.47] - 2026-09-14

### Fixed

- Render lesson summaries as readable preview text: remove Markdown editing
  markers, avoid repeating the lesson title, and flatten table rows without
  changing the editable lesson source.

## [0.5.46] - 2026-09-14

### Fixed

- Allow the normal source-reuse confirmation request immediately after the
  preliminary `409` response without returning `429` from the same user action.
- Keep direct-source quiz questions within the current authored lesson topic;
  grounded facts from neighboring source sections are deleted without quota
  replacement.

## [0.5.45] - 2026-09-14

### Changed

- Build one lesson per named collection when the primary worksheet is a
  characteristic-by-collection comparison matrix, without forcing a larger
  lesson count from a supporting catalogue.
- Show exact completed and total lesson counts during generation and preserve
  the final saved count after completion.

### Fixed

- Keep similarly named collection columns such as `Чикаго Нео` and
  `Чикаго Стрит` separate throughout lesson generation and assessment.
- Prevent a supporting worksheet title from invalidating a legitimate course
  title assembled from primary collection names.
- Reject questions that assess another collection's attribute or turn a
  compatibility relation into an inclusion claim; invalid questions are
  deleted without quota replacement.
- Preserve enough complete peer-row evidence for useful distractors while
  binding each question and correct answer to the lesson's named collection.
- Make a failed final assessment audit a typed resumable interruption with
  completed lesson checkpoints and a bounded diagnostic reason.
- Clear an expired in-memory tenant context after a forced refresh fails, so the
  interface returns to normal authentication instead of retaining stale access.

## [0.5.44] - 2026-09-14

### Fixed

- Keep article, collection and numerical properties bound to the same source row
  when generating lessons from structured catalogues.
- Surface conflicting source values for the same identified item instead of
  silently selecting one; the draft asks the methodologist to verify the original.
- Independently compare numerical question options by period, unit, calculation
  base and conditions, and remove ambiguous questions without generating quota
  replacements.
- Treat question counts as evidence-sized ceilings for every document size. A
  lesson may retain fewer or no questions when the source cannot support distinct
  useful checks.
- Evaluate test coverage across the entire course and report exact missing learning
  objectives separately for lesson content and assessments.

## [0.5.43] - 2026-09-14

### Fixed

- Independently solve generated questions against their original sources without
  exposing the answer key; remove ambiguous answers and course-wide repeated facts.
- Attempt uncovered learning objectives once without rebuilding lessons or padding
  counts. Retain named coverage-review advisories and pause recoverably if final
  assessment review cannot return a valid result.
- Keep independently valid questions from prose sources without retrying solely
  to fill a requested count. Preserve lessons with no surviving questions and
  explicitly list them as requiring a test before publication.
- Recognize equivalent Russian selection wording in the requested course goal
  without weakening source, worksheet or factual-grounding checks.
- Use the grounded lesson writer for an audience- or goal-specific course instead
  of replacing composite lessons with incomplete reference cards from a table.
- Include scanned-percentage handling instructions only when the selected source
  actually contains the corresponding uncertainty marker.

## [0.5.42] - 2026-09-14

### Fixed

- Recalculate course size from the primary learning material after reading the
  source, so a large supporting catalogue does not dictate extra lessons.
- Repair unambiguous worksheet references without making unrelated catalogue
  lessons appear grounded in a primary worksheet.
- Remove repeated or explicitly contradictory assessment questions without
  generating replacements solely to meet a question count.
- Preserve complete evidence sentences and reject unsupported numerical claims
  and visibly incomplete formula explanations in generated lessons.
- Show omitted topics and source-reading warnings on the saved draft. Label exact
  progress counts with their current stage rather than implying overall progress.
- Cross-check percentages in scanned PDFs locally. Values not confirmed by the
  page check remain explicitly uncertain and require review against the original;
  digital documents and office-format text retain their normal conversion route.

## [0.5.41] - 2026-09-14

### Fixed

- Pause a course-generation job when every configured generation provider is
  temporarily unavailable instead of terminally discarding its recovery path.
- Preserve completed lesson checkpoints and let the methodologist continue the
  same logical job from the first missing lesson without another quota charge.
- Keep the existing finite provider retry/failover budget; continuation remains
  an explicit user action and never loops indefinitely.

## [0.5.40] - 2026-09-14

### Fixed

- Remove only a source-unsupported recommendation or relationship fragment
  from an otherwise grounded lesson, then rerun the complete deterministic
  lesson-quality gate before accepting the remainder.
- Keep weak or empty remainders fail-closed and preserve existing bounded model
  repair attempts, course usefulness threshold, source grounding and checkpoint
  semantics.

## [0.5.39] - 2026-09-14

### Fixed

- Deterministically compact an overlong model-written source-map summary within
  its existing character/content budget instead of failing the whole course.
- Preserve every parsed topic anchor while keeping oversized JSON responses and
  topic arrays fail-closed under the existing hard size budgets.

## [0.5.38] - 2026-09-14

### Fixed

- Remove the arbitrary per-batch topic-count ceiling from source mapping;
  detailed regulatory and catalog sources are now bounded by the existing
  response, content, serialized-JSON, token and final-overview budgets.
- Invalidate prior source-map checkpoints after the protocol change so resumed
  jobs cannot mix responses produced under different validation contracts.

## [0.5.37] - 2026-09-14

### Fixed

- Retry a transient DeepSeek connection failure on the same provider before
  failing over, so one interrupted concurrent source-map batch no longer
  aborts an otherwise healthy course-generation job.
- Keep the existing finite provider retry budget and fallback order; permanent
  failures still terminate without an unbounded retry loop.

## [0.5.36] - 2026-09-14

### Fixed

- Compact the final course structure to the lessons actually accepted from a
  source before matching generated assessments and saving the draft.
- Preserve original plan coordinates only for durable checkpoint recovery;
  omitted lessons no longer remain in the separate structure used by the
  persistence layer.

## [0.5.35] - 2026-09-14

### Fixed

- Preserve each accepted lesson's original plan identity after weaker planned
  lessons are omitted, so review and question generation checkpoint the lesson
  that is actually being processed instead of a compacted neighbour.
- Persist quality-rejected lessons as terminal omissions with sanitized reason
  codes; resumed jobs skip them without inventing filler or requiring review and
  assessment checkpoints for content that will not be saved.
- Keep completed assessments mapped through the same original-to-compacted
  identity when a generation resumes after interruption.

### Security

- Retain tenant-scoped RLS/FORCE RLS and owner-guarded leases for terminal
  omissions; the new database state does not relax runtime table privileges.

## [0.5.34] - 2026-09-14

### Fixed

- Recalculate the source-excerpt allowance when a deterministic lesson-quality
  check asks the model for a corrected version, so the correction instructions
  and grounded source remain inside the same strict provider prompt limit.
- Preserve document identity, headings and source references on every retry;
  oversized or otherwise unrepresentable metadata still fails before a
  provider call.

## [0.5.33] - 2026-09-14

### Fixed

- Accept up to 24 distinct navigation topics from one large source-map batch,
  instead of failing a grounded course when the model returns 17 to 24 concise
  topics within every response and architect-overview budget.
- Keep source coverage server-owned and continue to reject empty topic lists,
  more than 24 topics, overlong topics and over-budget serialized output.

## [0.5.32] - 2026-09-14

### Fixed

- Keep a single large scanned-document excerpt within the lesson-writer prompt
  budget by using an exact, source-grounded prefix instead of rejecting the
  whole course before the first lesson.
- Preserve document identity, headings and source references for the bounded
  excerpt while continuing to reject unrepresentable course metadata and
  multi-document requests that cannot include every source without truncation.
- Validate production release correlation IDs and rollback identity formats
  before starting the immutable API image build.

## [0.5.31] - 2026-09-14

### Changed

- Treat an architect's requested lesson count as a quality ceiling: after three
  failed grounded rewrites, omit that lesson and continue the remaining course
  instead of padding the count or failing all useful work.
- Require an adaptive useful core before saving: at least half of the planned
  lessons, capped at five and never below one, must still pass every grounding
  and quality rule.

### Fixed

- Report the number of accepted lessons to the review and assessment stages so
  progress and question generation follow the course that is actually saved.

## [0.5.30] - 2026-09-14

### Fixed

- Do not treat the Markdown heading that exactly repeats an already validated
  lesson title as a new unsupported factual relationship.
- Keep lesson grounding strict by excluding that heading from source-anchor,
  minimum-content and repetition measurements; the lesson body must still pass
  every quality rule.
- Continue to reject any other invented causal, prescriptive or sales-oriented
  heading before a course or its questions can be saved.

## [0.5.29] - 2026-09-13

### Fixed

- Keep the document-compatibility and course-submission requests bounded by
  using persisted source metadata instead of converting a large original a
  second time before its background generation job can be queued.
- Continue to verify, convert and inspect the immutable original inside the
  generation worker, preserving source-grounding and fail-closed behavior.

## [0.5.28] - 2026-09-13

### Fixed

- Convert legacy binary Word `.doc` sources with a request-isolated LibreOffice
  user profile, instead of failing before conversion under the non-root service
  account.
- Ensure the lesson editor's 1400-pixel desktop width overrides the shared
  dialog's narrow default, while retaining the responsive mobile layout.

## [0.5.27] - 2026-09-13

### Added

- Show a live, safely rendered lesson preview beside the source editor, including
  headings, lists and tables without visible Markdown control characters.

### Changed

- Expand the lesson editor to use the available desktop workspace while keeping
  a responsive single-column layout on smaller screens.

### Fixed

- Restore OCR for scanned PDF sources by supplying Docling's headless OpenCV
  runtime and a writable persistent model cache.
- Keep the Docling service and the document worker on the same protected API key
  so conversion requests fail closed without breaking authorized indexing.

## [0.5.26] - 2026-09-13

### Fixed

- Apply the structured-source drop-without-padding policy to flattened Excel
  evidence written as `field — value`, not only to Markdown table rows.
- Prevent the assessment stage from making five provider retries and failing a
  whole course when the remaining invalid questions came from flattened rows.

### Changed

- Treat requested lesson and question counts as ceilings for structured source
  material. Invalid or duplicate questions are removed without regeneration;
  useful surviving questions and lessons remain intact.

## [0.5.25] - 2026-09-13

### Changed

- Treat every deterministically invalid question from a structured source as
  removable after the first parseable provider response. Keep only independently
  valid questions and never regenerate replacements to satisfy a target count.

### Fixed

- Prevent a structured-source course from failing after repeated assessment
  quality retries when the model cannot produce enough valid questions. A lesson
  may contain fewer questions or no quiz when its useful source facts are exhausted.

## [0.5.24] - 2026-09-13

### Fixed

- Drop structured-source questions that ask how the source is worded, omit the
  concrete subject of an attribute, or use a deictic collection reference.
- Drop interrogative answer fragments and multi-item answer lists instead of
  presenting them as single-choice answers.
- Recognize inflected Russian collection names as the same source-backed subject
  while excluding sentence-initial question words from named-entity evidence.

## [0.5.23] - 2026-09-13

### Fixed

- Keep a structured-source lesson without a quiz when every generated question
  fails the quality gate, instead of retrying weak questions and failing the
  entire course.
- Restore an intentionally empty assessment checkpoint without calling the model
  again after a worker restart.

## [0.5.22] - 2026-09-13

### Changed

- Treat requested lesson and assessment counts as upper bounds: weak structured-source
  questions are removed without regeneration or quota padding.

### Fixed

- Reject spreadsheet questions that refer only to "the description" or another
  source location without naming the collection or subject being tested.
- Reject questions that reveal the correct answer in their own wording, including
  partial answer leakage in longer Russian phrases.

## [0.5.21] - 2026-09-13

### Fixed

- Drop a repeated structured-source claim even when one correct answer adds a
  useful qualification around the same distinctive phrase. The later question
  is removed without a quota-filling model call.

## [0.5.20] - 2026-09-13

### Changed

- Structured-course assessment counts remain ceilings when two answers express
  the same useful claim across different spreadsheet rows. The first grounded
  question is kept and the paraphrased repeat is dropped without padding.

### Fixed

- Detect conservative cross-row answer overlap such as "one platform for the
  whole apartment" versus "a constructor for the whole apartment" while
  preserving equal wording that belongs to different source subjects.

## [0.5.19] - 2026-09-13

### Changed

- The requested number of assessment questions remains a ceiling across the
  whole generated course. A rejected duplicate or weak question is removed
  without a replacement request made only to restore the nominal count.

### Fixed

- Detect repeated facts across different lessons when one correct answer is a
  concise form of the other with only a short descriptive prefix.
- Reject structured-source questions that refer only to a generic collection,
  item or element without naming the subject being tested.
- Reject low-information answer sets whose options differ at only one position,
  including short three-word spreadsheet-derived variants.
- Preserve structured cell identity when a Markdown table row is split from its
  trailing delimiter during sentence extraction.

## [0.5.18] - 2026-09-13

### Changed

- The requested question count is now a ceiling for structured lessons. Invalid
  duplicates and ambiguous questions are removed without asking the model to pad
  the test back to a nominal size.
- A short source-backed test is accepted when the lesson contains only a small
  number of independent assessable facts.

### Fixed

- Detect two differently worded questions that target the same spreadsheet cell,
  including answers that differ only by a short introductory preposition.
- Reject an incorrect option when it is also supported by the same source cell as
  the marked correct answer.
- Keep opaque compact spreadsheet shorthand out of learner-visible options unless
  the question explicitly asks for a code, model or article.
- Native frontend release preflight now reports invalid or missing CLI parameters
  as bounded usage errors instead of exposing a raw assertion traceback.

## [0.5.17] - 2026-09-13

### Changed

- Production embedding routing now uses three independent private Qwen3 replicas
  before Voyage and Cohere. All replicas share one canonical semantic-space
  identity while retaining route-specific names and API model IDs for failover
  diagnostics.
- A readable uploaded source remains available for direct-source course generation
  when every semantic embedding provider is temporarily unavailable. The document
  is shown as partially ready without claiming that its search index exists.

### Fixed

- Restore the inactive private embedding relay and add independently verified
  gx10-12 and gx10-4 relay paths. The gx10-4 adapter uses its actual unnamespaced
  `Qwen3-Embedding-8B` API model ID instead of the rejected namespaced identifier.
- Document upload and reindex jobs no longer fail the whole source after the Qwen,
  Voyage and Cohere embedding chain is exhausted. They complete with a stable
  `embedding_providers_unavailable` degraded status, zero indexed chunks and an
  explicit source-ready result.
- Unexpected converter, storage and malformed-vector failures remain terminal and
  are not hidden by the provider-outage recovery path.

## [0.5.16] - 2026-09-13

### Added

- The course-generation page shows numeric document-indexing progress, percentage,
  processed and total fragments, and an estimated remaining time while the job is
  active.

### Changed

- Lesson duration now includes both reading time and the expected time for answering
  its generated questions, so the saved course duration reflects the actual learning
  workload instead of a fixed two-minute placeholder.
- Structured primary tables with three real comparison subjects produce three
  source-grounded answer options. The system no longer invents a fourth option just
  to satisfy the generic model prompt.
- Deterministic table assessments no longer wait for the external-model rate-limit
  delay when no provider request was made.

### Fixed

- Preserve the orientation of primary worksheet matrices when the course writer
  renders them as lesson cards. Questions now ask about the collection and its
  attribute, rather than reversing the collection and attribute labels.
- Keep auxiliary catalog worksheets out of the lesson plan when the primary
  collection worksheet contains the authoritative training structure.
- Reject questions that contain their own correct answer, reuse the same atomic
  source fact, or refer to how information appears in a source, table, lesson, or
  section.
- Avoid over-broad duplicate suppression: the same words may remain valid answers
  for genuinely different source facts, while an already-assessed source fact cannot
  be repeated in another lesson.
- Stop terminal document-indexing jobs from being polled indefinitely and refresh the
  document catalog once when indexing completes.

## [0.5.15] - 2026-09-13

### Fixed

- After reviewing a completed AI-generated course, methodologists can start a
  new course from the same page. The action clears only the finished workflow
  and its persisted browser context, then returns to a clean document-selection
  step without signing the user out.
- Generated tests reject questions that describe facts through the source
  container (for example, “how the source material describes ...”) instead of
  asking the learner about the fact itself.
- Restored assessment checkpoints are revalidated against the current lesson
  source and quality contract; invalid saved questions are regenerated.

## [0.5.14] - 2026-09-13

### Changed

- Generated multiple-choice tests distribute correct answers across saved
  positions instead of using one predictable position throughout a quiz.
- On a repeat attempt, learners see multiple-choice options in a different
  order while the stable choice identifiers and grading contract stay intact.
- Multi-module courses generated directly from structured tables use
  source-grounded topic ranges in module titles instead of numbered placeholders.
- Structured-table lessons use peer values from the same primary worksheet to
  build deterministic distractors without promoting auxiliary catalog rows.

### Fixed

- Reject contextless comparison questions, invented named entities in
  distractors, and mechanically repeated answer variants before a generated
  assessment can be saved.
- Keep duplicate-fact detection active even when another distractor-quality
  issue is present, so retries receive the complete corrective feedback.
- Extend the course-quality acceptance gate with blind fixed-position and
  longest-answer baselines plus generic-module-title detection.
- Resolve the canonical workspace credential file from the primary repository
  when protected operations run from a linked release worktree; reject malformed
  or noncanonical Git metadata instead of consulting a neighbouring directory.

## [0.5.13] - 2026-09-12

### Changed

- Large-document indexing sends Qwen embedding requests in conservative
  16-fragment batches and allows up to 30 seconds per request.

### Fixed

- A transient slow Qwen batch is retried in the same embedding space instead
  of discarding an almost completed large-document indexing attempt.
- Full-workbook indexing remains provider-atomic: fallback providers start a
  separate complete attempt and their vectors are never mixed with Qwen.

## [0.5.12] - 2026-09-12

### Changed

- Generated lesson tests now reject mechanically repeated answer frames that
  change only the final word; shared wording must be moved into the question.
- Assessment prompts explicitly require a positive category answer for
  category, collection, line, and type questions.

### Fixed

- Reject duplicate facts that reuse one source excerpt and a lexically
  equivalent correct answer with only introductory wording changed.
- Reject negative non-answers such as "not the Chicago line" when the question
  asks which line or category an item belongs to.

## [0.5.11] - 2026-09-12

### Changed

- Production web and API security policies no longer trust the retired legacy
  LMS/CDN hostnames.
- Deployment documentation now describes the native CT137 frontend and the KZ
  VM126/CT125 backend path instead of the superseded Render/Vercel topology.

### Fixed

- The production frontend release now includes the exact generation progress
  from `63ed5fd8` and long-running document polling from the accepted 0.5.x
  release history, which were not present in the previous CT137 frontend
  deployment (`a507e17b`).

### Security

- Removed the obsolete `lms.kml.kz` and `cdn.lms.kml.kz` origins from active
  Content Security Policy and image-host configuration.
- Production browser connections are restricted to `api.kml.kz`; the isolated
  DEV build derives its own API origin instead of broadening production CSP.

## [0.5.10] - 2026-09-12

### Changed

- The Qwen 3.8 generation fallback now uses the private KZ WireGuard route
  instead of an ASUS LAN address that VM126 could not reach directly.
- Removed the obsolete public legacy-Qwen defaults from application settings.

### Fixed

- The configured second generation provider is now a verified operational
  fallback: model discovery and a real chat completion pass from VM126.

### Security

- Qwen generation and document embeddings no longer require public model
  hostnames.

## [0.5.9] - 2026-09-12

### Changed

- Production document indexing now reaches the dedicated Qwen embedding model
  through the private KZ WireGuard hub instead of a public embedding hostname.
- The provider uses the exact model identifier published by the private vLLM
  endpoint.

### Fixed

- Future exact-image deployments retain the verified private embedding route
  as their default instead of silently reverting to the former public gateway.

## [0.5.8] - 2026-09-12

### Changed

- Reserved source tag; superseded by 0.5.9 before production deployment.

### Fixed

- Release metadata was corrected in 0.5.9 before production deployment.

## [0.5.7] - 2026-09-12

### Fixed

- Restored the production-reachable Qwen embedding gateway as the first
  document-indexing provider. The unverified direct ASUS route is no longer
  selected by default from the production worker.

## [0.5.6] - 2026-09-12

### Added

- Document indexing and course generation now report completed units, total
  units and a measured remaining-time estimate in the tenant interface.

### Changed

- Managed embedding fallbacks use provider-safe larger batches and bounded
  retries, reducing the number and worst-case duration of requests for large
  spreadsheet sources.
- Document status polling respects server backoff and remains available for
  long-running indexing instead of silently stopping after two minutes.

### Fixed

- Provider failover restarts exact progress for the new attempt without
  exposing provider names to tenant users.
- Local quality checks consistently use their active Python environment, and
  migration source tests no longer depend on the shell working directory.

## [0.5.5] - 2026-09-12

### Changed

- Structured lessons now receive a question count proportional to their actual
  source facts, avoiding padded or repetitive tests for compact material.
- Large comparison worksheets can be split across bounded chunks and assembled
  back into one coherent, source-grounded course structure.

### Fixed

- Very wide Excel rows, including unusually long cells or labels, no longer
  exceed the indexing chunk limit or silently lose their table meaning.
- Source-note rows are no longer rendered as lesson topics or learner content.
- Local critical-journey checks no longer attempt to use workstation PostgreSQL;
  database verification is explicitly separated into CI and Supabase DEV paths.

## [0.5.4] - 2026-09-12

### Fixed

- Complex spreadsheet planning now allows supporting catalog facts to enrich a
  lesson grounded in the main learning material, without allowing the catalog to
  become a standalone lesson subject.
- Mixed and large learning worksheets are no longer classified as supporting
  solely because they contain price, identifier or other reference columns.

## [0.5.3] - 2026-09-12

### Added

- Multi-sheet spreadsheet sources now receive a bounded document passport that
  distinguishes the main learning material from supporting reference sheets.
- The course-generation screen explains that an optional course description can
  steer the result, while generation remains available without one.

### Changed

- Automatic course scope now follows the amount and structure of teachable
  source content instead of turning large supporting lists into the curriculum.
- Structured spreadsheet lessons preserve source entities, attributes, and
  relationships while grouping them into a concise, reviewable course.

### Fixed

- Generated tests reject generic, presentation-driven, repeated, or
  unsupported questions and keep answer options grounded in the lesson source.
- Course generation keeps worksheet provenance and lesson-quality policy
  identity across resumable checkpoints.

## [0.5.2] - 2026-09-11

### Fixed

- An already-open browser tab now closes the signed-in session at the absolute
  eight-hour deadline without waiting for the user to make another request.
- Browser sessions issued before this release are revalidated after their
  short-lived access token expires and receive the same proactive deadline.

### Security

- Access-token refresh and role switching preserve the original login time;
  selecting another role cannot extend the browser-session lifetime.
- Role switching now accepts only an active, allowlisted refresh session owned
  by the same user and organization.

## [0.5.1] - 2026-09-11

### Fixed

- A course-generation worker time limit now preserves the job as resumable
  instead of reporting a terminal failure after completed lessons, reviews, or
  tests have already been checkpointed.
- Jobs affected by the previous timeout classification can be continued only
  when their exact timeout marker and valid saved generation checkpoints are
  both present; ordinary failed jobs remain terminal.

## [0.5.0] - 2026-09-11

### Added

- Interrupted course generation can continue from the last saved lesson without
  charging the tenant for a second course-generation attempt.

### Changed

- Course scope and estimated learning duration now adapt to the usable amount of
  source material instead of padding small sources or deriving study time from
  technical document fragments.
- Password-based browser sessions now require a new sign-in after at most eight
  hours, even when a page remains open and background requests continue.

### Fixed

- A structurally invalid first course plan receives one bounded correction
  attempt while module limits, lesson limits, and source-document coverage remain
  strictly enforced.
- Completed lessons, reviews, and tests are checkpointed so a worker interruption
  no longer discards all successful generation work.

### Security

- Refresh-token rotation preserves the original login time and cannot extend a
  browser session beyond the configured absolute lifetime.

## [0.4.4] - 2026-09-10

### Fixed

- Large Excel catalogs now reserve the final course-planning map capacity before
  accepting generated topic labels, preventing valid per-part responses from
  overflowing the complete map and stopping course creation.
- An oversized topic batch receives one bounded shortening attempt while all
  source references and distinct subject areas remain preserved.

## [0.4.3] - 2026-09-10

### Fixed

- Generated quiz answers must use a short exact excerpt from their lesson evidence;
  topic-word overlap no longer admits invented properties or changed numeric values.
- Quiz explanations quote the selected lesson evidence without adding a second
  model-authored factual claim. Existing review and question-quality checks remain.

## [0.4.2] - 2026-09-10

### Fixed

- Course generation from large Excel catalogs processes source topics throughout
  the document and handles long spreadsheet headings when writing lessons.
- Invalid navigation-map formatting receives one bounded retry; already validated
  batches can be reused within that same generation job.
- Generated lesson headings, lists and simple tables are displayed as readable
  content, with source HTML remaining inert text.

## [0.4.1] - 2026-09-10

### Fixed

- Large spreadsheet course sources no longer exhaust the topic-map batch budget because identical source metadata is repeated per fragment. Exact source content, provenance, coverage validation, and existing request limits are preserved.
- An overlong but otherwise valid navigation-map response gets one bounded shortening attempt before failing; source-ID groups, deadlines and output validation remain enforced.

## [0.4.0] - 2026-09-10

### Added

- Organization administrators can configure their own course/test generation and document-indexing providers separately, with encrypted write-only keys and tenant-scoped settings.

### Changed

- Course generation can use verified original source material when a compatible semantic index is unavailable; available semantic excerpts remain bound to the selected source documents.

### Fixed

- Assessment repair includes actionable answer-length feedback, caps recovered questions to the requested count, and rejects repeated questions with the same evidence and normalized correct answer.
- Large-source fallback selects whole excerpts within the request budget while retaining every document requested for the lesson.
- Semantic document search keeps query instructions separate from source material, validates vector-to-fragment ordering, and prevents mixing incompatible embedding spaces during provider fallback.

### Security

## [0.3.1] - 2026-09-09

### Fixed

- Course approval settings now load their saved server state when opening or switching courses, instead of displaying an unchecked default. Failed reads show a retry action rather than an incorrect disabled policy.
- Publication conflicts explain the required approval action in Russian, Kazakh, and English in the course list, editor, and AI-generation result screen. Separate approval remains off by default and is enforced when explicitly enabled.

## [0.3.0] - 2026-09-08

### Added

- Tenant-scoped course approval and review: methodologists can send a course to
  internal or guest reviewers, collect decisions and comments, and retain the
  review context before publication.
- Learning Insights for methodologists: inspect incorrect learner answers from
  immutable attempt evidence, compare first and latest answers, view aggregate
  question statistics, and record a follow-up status without automated actions
  or LLM calls.
- Recurring learning programs with cycle deadlines, overdue visibility, CSV
  reporting, reminder settings and delivery-status history. Global reminder
  delivery remains disabled until a separately accepted rollout.
- A public RU/KK/EN interactive learning example and a methodologist dashboard
  with real training-summary counts and clear starting paths for materials or
  ready course foundations.
- Document provenance showing the tenant-local uploader and creation time, plus
  the existing feature-gated YouTube-caption source flow.

### Changed

- AI-generated assessments require explicit methodologist review before course
  publication and keep concise answers separate from supporting excerpts.
- Public trial registration is passwordless; verified owners return through an
  email code while existing password accounts remain compatible.
- Staff-related navigation is grouped under one expandable section, and the
  public login no longer advertises a separate superadmin entry point.
- Tenant assistant responses are constrained to the tenant learning context and
  do not disclose model, provider, configuration or secret operational details.

### Fixed

- Course-generation cancellation is serialized with course persistence and is
  checked between assessment retries, preventing a cancelled job from leaving
  an unlinked course or reporting unfinished work as complete.
- New generation forms no longer reopen an old failed or cancelled job, and
  valid assessment questions can be recovered across bounded retries.
- Course approval navigation, guest-review credentials, pagination, action
  confirmations and response serialization now preserve the intended reviewer
  and tenant context.
- Browser refresh requests are serialized across tabs, responsive navigation no
  longer shifts the application shell, and learner program navigation remains
  available for active recurring programs.
- Reminder workers own their asynchronous database lifecycle, while recurring
  learning and assignment outboxes remain usable under non-bypass database
  ownership without weakening tenant boundaries.

### Security

- SCORM package intake and progress commits reject unsafe archives, XML entity
  expansion, decompression bombs, invalid fields and oversized cumulative state
  before persistent writes.
- Browser-session mutations enforce trusted origins, Fetch Metadata, secure
  same-site cookies, JSON-only production requests and symmetric token deletion.

## [0.2.0] - 2026-08-31

### Added

- Authenticated question-editor assistant preview endpoint with server-derived
  tenant/actor authority, explicit impersonation rejection, and bounded typed
  error responses.
- Product versioning foundation: `VERSION` file, `CHANGELOG.md`,
  `docs/releases/` documentation, release-note template, deterministic
  version-consistency validation script and focused tests.
- Multi-document course generation with a five-source limit, aggregate source
  budget, topic and language preflight, order-insensitive duplicate admission,
  and explicit mixed-language confirmation.
- Feature-flagged YouTube caption import: validated YouTube URLs are processed
  by a bounded worker, persisted as ordinary documents, deduplicated per
  tenant, and handed to the existing document indexing pipeline.
- Reusable Russian-language guide for introducing product versioning into
  agent-managed projects.

### Changed

- Document library can offer a YouTube source flow with RU, KK, and EN caption
  preference when the backend feature flag is enabled.
- Methodologist navigation now follows the operational sequence from source
  documents and course creation through assignment, employees, and results;
  employee structure and employee groups are adjacent, and the staff menu item
  remains active across structure and import tabs.
- Self-service trial owners now start in the methodologist workspace while
  retaining a separate administrator role for tenant configuration.
- Financial-sector course blueprints are visible only to tenants explicitly
  classified as financial organizations by a platform superadmin.
- Contextual help no longer repeats its purpose block, and retention help now
  reflects the methodologist's read-only policy view instead of suggesting
  unavailable policy mutations.

### Fixed

### Security

[Unreleased]: https://github.com/KamillaLMSCRM/Kamilya-NEW/compare/v0.11.0...HEAD
[0.11.0]: https://github.com/KamillaLMSCRM/Kamilya-NEW/compare/v0.10.2...v0.11.0
[0.10.2]: https://github.com/KamillaLMSCRM/Kamilya-NEW/compare/v0.10.1...v0.10.2
[0.10.1]: https://github.com/KamillaLMSCRM/Kamilya-NEW/compare/v0.10.0...v0.10.1
[0.10.0]: https://github.com/KamillaLMSCRM/Kamilya-NEW/compare/v0.9.2...v0.10.0
[0.9.2]: https://github.com/KamillaLMSCRM/Kamilya-NEW/compare/v0.9.1...v0.9.2
[0.9.1]: https://github.com/KamillaLMSCRM/Kamilya-NEW/compare/v0.9.0...v0.9.1
[0.9.0]: https://github.com/KamillaLMSCRM/Kamilya-NEW/compare/v0.8.2...v0.9.0
[0.8.2]: https://github.com/KamillaLMSCRM/Kamilya-NEW/compare/v0.8.1...v0.8.2
[0.8.1]: https://github.com/KamillaLMSCRM/Kamilya-NEW/compare/v0.8.0...v0.8.1
[0.8.0]: https://github.com/KamillaLMSCRM/Kamilya-NEW/compare/v0.7.7...v0.8.0
[0.7.7]: https://github.com/KamillaLMSCRM/Kamilya-NEW/compare/v0.7.6...v0.7.7
[0.7.6]: https://github.com/KamillaLMSCRM/Kamilya-NEW/compare/v0.7.5...v0.7.6
[0.7.5]: https://github.com/KamillaLMSCRM/Kamilya-NEW/compare/v0.7.4...v0.7.5
[0.7.2]: https://github.com/KamillaLMSCRM/Kamilya-NEW/compare/v0.7.1...v0.7.2
[0.5.56]: https://github.com/KamillaLMSCRM/Kamilya-NEW/compare/v0.5.55...v0.5.56
[0.5.55]: https://github.com/KamillaLMSCRM/Kamilya-NEW/compare/v0.5.54...v0.5.55
[0.5.54]: https://github.com/KamillaLMSCRM/Kamilya-NEW/compare/v0.5.53...v0.5.54
[0.5.53]: https://github.com/KamillaLMSCRM/Kamilya-NEW/compare/v0.5.52...v0.5.53
[0.5.48]: https://github.com/KamillaLMSCRM/Kamilya-NEW/compare/v0.5.47...v0.5.48
[0.5.47]: https://github.com/KamillaLMSCRM/Kamilya-NEW/compare/v0.5.46...v0.5.47
[0.5.46]: https://github.com/KamillaLMSCRM/Kamilya-NEW/compare/v0.5.45...v0.5.46
[0.4.3]: https://github.com/KamillaLMSCRM/Kamilya-NEW/compare/v0.4.2...v0.4.3
[0.4.2]: https://github.com/KamillaLMSCRM/Kamilya-NEW/compare/v0.4.1...v0.4.2
[0.4.1]: https://github.com/KamillaLMSCRM/Kamilya-NEW/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/KamillaLMSCRM/Kamilya-NEW/compare/v0.3.1...v0.4.0
[0.3.1]: https://github.com/KamillaLMSCRM/Kamilya-NEW/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/KamillaLMSCRM/Kamilya-NEW/compare/v0.2.0...v0.3.0
