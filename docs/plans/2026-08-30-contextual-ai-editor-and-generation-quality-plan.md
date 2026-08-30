# Contextual AI editor and generation-quality plan

Status: approved for incremental development in the development contour only.

Date: 2026-08-30

Owner: Kamilya root orchestrator

## 1. Goal

Make course and assessment generation produce reviewable drafts that do not expose the correct answer through length, style, terminology, or implausible distractors. Add a contextual assistant to the methodologist editor so a non-technical HR employee can request precise changes in ordinary language without regenerating unrelated content.

The same workflow must create structured product feedback. Repeated requests such as "make the distractors less obvious" or "add context to question 3" must become measurable evidence for improving prompts, deterministic validators, model routing, and later evaluation or tuning.

## 2. Product decisions

1. AI generation creates a draft, never an automatically trusted course or assessment.
2. The editor assistant works against an explicit selected object: course, module, lesson, quiz, question, answer option, or explanation.
3. The assistant produces a structured patch and preview. It does not silently overwrite content.
4. Applying a patch requires a current base version and an explicit user confirmation.
5. Editing published content creates a new draft version. Existing learners and historical results remain bound to the published version they received.
6. "Regenerate answer options" preserves the question, correct answer, score, and question type by default. The methodologist must explicitly authorize broader changes.
7. Every proposed patch is source-grounded where a source exists and passes deterministic quality checks before it can be applied.
8. A rejected or repeatedly revised suggestion is product feedback, not merely an operational error.
9. Raw customer instructions and source content are tenant data. They must not be emitted to application logs, metrics labels, dataLayer, Ads, or external analytics.
10. Production, CT125, and VM126 remain out of scope until the development implementation and acceptance evidence are approved separately.

## 3. Target user workflow

### 3.1 Question-level editing

The methodologist opens a question. The assistant panel displays the exact context, for example:

`Course > Module > Lesson > Quiz > Question 3`.

The methodologist can enter commands such as:

- Add more context to this question.
- Rewrite the question in simpler Russian.
- Keep the correct answer and generate better distractors.
- Make the alternatives similar in length and detail.
- Turn this into a practical scenario.
- Verify that the correct answer is supported by the source.

The result is shown as a before/after preview with source references, validation warnings, and these actions:

- Apply;
- Revise request;
- Generate another proposal;
- Cancel.

### 3.2 Test-level editing

The assistant can inspect a whole quiz and propose a batch of independent patches for selected questions. Each patch can be accepted or rejected separately. Supported checks include:

- correct answer is systematically the longest;
- two answers can reasonably be considered correct;
- distractors are absurd or unrelated;
- wording is malformed;
- questions are duplicates;
- source evidence is missing;
- correct-answer position or stylistic signature is predictable;
- questions test verbatim recall instead of application.

### 3.3 Lesson and course editing

The same assistant contract later supports localized operations such as simplifying a paragraph, adding a practical example, splitting or merging lessons, removing duplication, adding conclusions, checking unsupported statements, or generating a quiz only for the selected lesson.

## 4. Generation-quality contract

Each generated assessment item must contain structured internal fields before it becomes an editable question:

- learning objective;
- source evidence references;
- atomic correct fact;
- correct answer;
- misconception or error model behind each distractor;
- distractors;
- explanation;
- difficulty and skill level;
- generator, model, prompt, and validator versions.

The generator must not put the explanation inside the correct answer. Distractors must be plausible in the same context but refutable from the selected source.

### 4.1 Deterministic validators

The initial gate must detect at least:

- more than one potentially correct answer;
- correct answer unsupported by the selected source;
- malformed or incomplete question wording;
- duplicate or near-duplicate answers;
- absurd or non-responsive distractors;
- excessive answer-length imbalance;
- terminology or certainty present only in the correct answer;
- predictable correct-answer position;
- excessive lexical overlap between the source and only the correct answer;
- duplicate questions in the same quiz;
- forbidden leakage of explanation into the answer.

Initial configurable heuristics:

- warn when the correct answer is more than 35 percent longer than the median distractor;
- require at least two distractors to be within 25 percent of the correct answer's useful-detail length when the language permits;
- warn when the correct answer is the longest in more than 40 percent of a quiz;
- reject or require explicit override when that share exceeds 50 percent;
- reject a quiz when a deterministic "choose the longest answer" baseline reaches the configured pass score.

These thresholds are initial product hypotheses. They must be versioned and later adjusted from measured outcomes, not changed silently.

## 5. Contextual assistant architecture

Introduce a deep `editor_assistant` module with a narrow public contract. Controllers, model clients, persistence, validation, and UI must not independently implement editing semantics.

Core inputs:

- tenant and actor context;
- target entity type and stable target identifier;
- selected field or scope;
- current base version;
- user instruction;
- immutable current-content snapshot;
- permitted source references;
- operation constraints such as `preserve_correct_answer`;
- locale.

Core output:

- request identifier;
- normalized intent category;
- structured field-level patch;
- human-readable summary;
- source references;
- validation report;
- model and generator provenance;
- applicability status.

The preview operation has no content mutation. Apply is a separate command that verifies tenant, authorization, request ownership, patch status, and the unchanged base version. Apply is idempotent and uses optimistic concurrency. A stale preview must be rejected and regenerated against the current version.

## 6. Request and feedback logging

### 6.1 Why logging is required

The product needs to answer:

- which generated elements methodologists most often ask to change;
- which generator, prompt, model, source type, language, and question type cause the most rework;
- whether users accept, reject, regenerate, or manually rewrite assistant proposals;
- whether accepted changes survive until publication;
- which deterministic warnings predict later manual correction;
- whether a generator release actually reduces rework.

### 6.2 Event model

Use a durable tenant-scoped request record plus append-only lifecycle events.

Request fields:

- opaque request ID;
- tenant ID and actor ID;
- target entity type and ID;
- parent generation trace ID when available;
- normalized intent category;
- selected scope and operation constraints;
- base content version;
- locale;
- source type summary;
- generator, prompt, model, and validator versions;
- created and expiry timestamps.

Lifecycle events:

- `requested`;
- `preview_started`;
- `preview_ready`;
- `preview_failed`;
- `regenerated`;
- `applied`;
- `rejected`;
- `manually_edited_after_apply`;
- `published`;
- `superseded`;
- `expired`.

Normalized intent categories initially include:

- `rewrite_wording`;
- `add_context`;
- `simplify_language`;
- `change_difficulty`;
- `make_scenario_based`;
- `regenerate_distractors`;
- `balance_answer_length`;
- `fix_multiple_correct_answers`;
- `fix_source_grounding`;
- `fix_grammar`;
- `remove_duplication`;
- `add_or_rewrite_explanation`;
- `split_or_merge_content`;
- `other`.

Quality issue labels initially include:

- `correct_answer_length_signal`;
- `correct_answer_style_signal`;
- `implausible_distractors`;
- `multiple_plausible_correct_answers`;
- `unsupported_correct_answer`;
- `malformed_question`;
- `duplicate_question`;
- `rote_recall_only`;
- `language_or_translation_problem`;
- `explanation_leaked_into_answer`;
- `other`.

### 6.3 Raw instruction handling

The normalized taxonomy and outcome events are the primary analytics data. Raw instruction text may contain personal or confidential customer data and therefore must:

- remain tenant-scoped;
- never appear in ordinary application logs or metrics labels;
- never be sent to marketing analytics;
- use the same access controls as course content;
- have an explicit retention period;
- be redacted or excluded from cross-tenant product analytics;
- be unavailable to unrelated tenants and ordinary learners;
- be deletable under the applicable retention process without destroying aggregate counters.

Cross-tenant product analytics must use only normalized categories, versions, counts, durations, validation labels, and outcome states. Any future use of raw instructions for an evaluation corpus requires a separately reviewed de-identification and governance process.

### 6.4 Feedback signals

The system must distinguish:

- proposal applied unchanged;
- proposal regenerated before application;
- proposal rejected;
- proposal applied and then manually edited;
- proposal remained in the version that was published;
- the same target required another request of the same category;
- the whole generated course required substantial rework.

A short optional rejection reason can be offered through simple choices, not a mandatory questionnaire:

- did not follow the request;
- introduced unsupported information;
- wording became worse;
- answer remained obvious;
- changed too much;
- other.

## 7. Metrics and improvement loop

Initial product metrics:

- AI edit requests per generated course;
- AI edit requests per 100 generated questions;
- share of generated questions manually or AI-reworked before publication;
- request distribution by normalized intent and quality label;
- proposal acceptance, regeneration, rejection, and post-apply manual-edit rates;
- repeated-request rate for the same target and intent;
- publication survival rate of applied patches;
- rework rate by model, prompt version, generator version, source type, locale, and question type;
- time from generation to publish-ready state;
- longest-answer baseline score and other heuristic-baseline scores;
- validator warning precision against later user corrections.

Improvement cycle:

1. Observe normalized feedback and validation outcomes.
2. Reproduce the frequent failure with synthetic, non-customer regression fixtures.
3. Improve deterministic validation, prompt structure, or model routing.
4. Run an offline evaluation against the fixed corpus.
5. Release a versioned generator change to development.
6. Compare rework metrics by generator version.
7. Promote only after quality and regression gates pass.

Do not automatically tune prompts or model weights from raw production requests. Human review, de-identification, a fixed evaluation corpus, and versioned release gates are mandatory. Fine-tuning is a later option, not the first response to feedback.

## 8. Security, tenancy, and audit invariants

- Every request, preview, patch, and event is tenant-scoped.
- The server derives tenant and actor from the authenticated context, never from a trusted client field.
- Authorization is checked during both preview and apply.
- Learners cannot invoke methodologist editing operations.
- A patch cannot target an entity outside the request tenant.
- Raw prompts, source fragments, answer text, email, phone, names, and tenant payloads are forbidden in technical logs and metrics labels.
- Model-provider calls use the existing approved routing and data-handling boundary.
- The administrative audit records who requested and who applied the change, but does not duplicate raw customer content.
- Published-version changes remain attributable and reversible.

## 9. Incremental implementation sequence

Only one step is assigned at a time. The root orchestrator reviews the diff and evidence before issuing the next step.

### Step 1. Telemetry contract and persistence foundation

Implement the tenant-scoped AI editor request and append-only lifecycle event model, normalized enums, repository/service boundary, migration, and focused tests. Do not call a model and do not add UI yet. Prove tenant isolation, idempotent lifecycle recording, valid status transitions, and that raw instruction text cannot enter analytics payloads or ordinary logs.

Acceptance:

- one canonical service owns creation and lifecycle transitions;
- server-derived tenant and actor contract is explicit;
- analytics projection contains only approved normalized fields;
- request/event retention fields exist;
- migrations are reversible and preserve existing data;
- focused unit/integration tests cover the contract;
- no deployment, push, version bump, or production mutation.

Local implementation status (2026-08-30): **COMPLETE / NOT DEPLOYED**.
Root-owned verification passed Ruff, the safe-wrapper contract (`3 passed`),
Alembic `0135 -> 0134 -> 0135` with one head at `0135`, and all Step 1
database-backed telemetry tests (`47 passed`) on a disposable local PostgreSQL
18 database. The disposable database was removed by the wrapper. Request-creation
retry idempotency remains intentionally assigned to Step 2; no dev, CT125, VM126,
or production mutation was performed.

### Step 2. Structured edit command and patch contract

Add target selection, operation constraints, base-version snapshot, structured patch schemas, preview lifecycle, and optimistic-concurrency semantics. Use a deterministic fake provider in tests; no production model routing yet.

Acceptance:

- preview cannot mutate content;
- stale base version is rejected;
- patch scope cannot escape the selected entity;
- retry is idempotent;
- published content cannot be overwritten in place.

Local implementation status (2026-08-30): **DOMAIN CONTRACT COMPLETE / NOT
WIRED OR DEPLOYED**. The pure contract defines selected targets, immutable base
snapshots, typed operations, source/provenance/validation payloads, preview-only
semantics, full apply preflight, published-content draft routing, and separate
atomic request/preview idempotency storage interfaces. Preview claims include
owner tokens plus pending/completed/failure recovery semantics so concurrent
retries cannot execute the provider twice. Root-owned verification passed Ruff,
all Step 2 pure tests (`19 passed`), and the full Step 1 PostgreSQL 18 regression
(`47 passed`) after an Alembic roundtrip. A durable transactional store, API/UI
wiring, real provider routing, and actual patch application remain intentionally
unimplemented and must be added under later integration gates. No dev or
production mutation was performed.

### Step 3. Question-level validator

Implement deterministic assessment checks, normalized issue labels, and configurable versioned thresholds. Add synthetic regression cases matching the observed failure patterns without copying customer content.

Acceptance:

- detects length and style leakage;
- detects malformed, duplicate, unsupported, and multiply-correct items where deterministic evidence permits;
- runs heuristic baselines including choose-longest;
- returns field-specific, methodologist-readable findings;
- validator version is persisted with results.

Local implementation status (2026-08-30): **VALIDATOR CONTRACT COMPLETE / NOT
WIRED OR DEPLOYED**. The pure versioned validator now covers bounded structural
checks, duplicate detection, answer-length/style leakage, choose-longest
diagnostics, explanation leakage, conservative rote-recall detection, and
explicit-evidence-only source, multiple-answer, distractor, and language signals.
Findings use closed codes, field paths, blocking severity, and fixed Russian
methodologist messages. Quiz-level statistical warnings are sample-gated, ties
are excluded from prediction accuracy, and malformed structure cannot be disabled.
Root-owned verification passed Ruff, all Step 2 and Step 3 pure tests (`40
passed`), and the full Step 1 PostgreSQL 18 regression (`47 passed`) with Alembic
head `0135`. Durable result persistence, API/generation integration, and real
source-evidence production remain intentionally unimplemented. No dev or
production mutation was performed.

### Step 4. Question assistant backend preview

Connect the structured command contract to the approved model router for single-question preview. Support wording, added context, distractor regeneration, answer balancing, difficulty, scenario conversion, explanation, and source verification.

Acceptance:

- model receives the minimum required tenant-scoped context;
- `preserve_correct_answer` is enforced server-side;
- output must parse as a structured patch;
- validation failure prevents applicability;
- provider/model/prompt provenance is recorded;
- fallback behavior follows the approved model chain and never silently weakens validation.

Local implementation status (2026-08-30): **BACKEND PREVIEW CONTRACT COMPLETE / NOT WIRED / NOT DEPLOYED**.

The single-question adapter now sends only bounded selected context, the exact
bounded methodologist instruction, current correct-answer identity, and bounded
source evidence to the approved resilient model chain. Accepted output is parsed
fail-closed, mapped to the canonical Step 2 paths (`question.text`,
`question.answer_options`, `question.explanation`), checked against scope and
protected fields, validated by the Step 3 validator, and returned as a
preview-only patch with accepted provider/model provenance. Blocking parser,
scope, evidence, correct-answer, or validator failures may advance to the next
approved provider with identical gates; warnings do not trigger fallback.
Existing full-generation paths are not connected to this adapter.

Root-owned verification passed Ruff, the combined Step 2-4 pure suite (`87
passed`), and the disposable PostgreSQL 18 Step 1 regression (`47 passed`) with
Alembic head `0135`. No API endpoint, UI integration, real provider call,
content application, dev deployment, or production mutation was performed.

Durable preview foundation status (2026-08-30): **CLAIM REPOSITORY COMPLETE /
NO API / NOT DEPLOYED**.

Alembic `0136` adds the tenant-scoped durable preview claim/result record with
forced RLS, same-tenant request linkage, bounded object results, closed failure
codes, token-digest ownership, and column-level runtime grants that cannot insert
a terminal result or update immutable identity fields. The async repository now
implements atomic claim/read/complete/fail/reclaim semantics, collision handling,
canonical completed readback, explicit failed reclaim, stale-token rejection,
and single-owner concurrency without process-local locks. Root-owned disposable
PostgreSQL 18 verification finished with Alembic head `0136`, runtime catalog
assertions, Ruff, eight static/model tests, and the full safe wrapper (`76 passed`).
There is still no HTTP contract, tenant-scoped question/evidence resolver,
service orchestration, draft-only apply endpoint, frontend panel, dev release,
or production release.

### Step 5. Question editor UI

Add the contextual assistant panel, selected-target indicator, quick actions, free-form instruction, before/after preview, source evidence, warnings, apply, regenerate, reject, and cancel.

Acceptance:

- ordinary HR wording is sufficient;
- the exact target is always visible;
- outside click does not lose an unsaved request or close a destructive modal;
- no change occurs before Apply;
- keyboard and mobile behavior are usable;
- success is read back from persisted state.

### Step 6. Apply, undo, and versioning

Apply validated patches through the canonical course/quiz versioning boundary. Add undo through a new revision, not history mutation. Ensure published learners and results remain bound to their original content version.

Acceptance:

- optimistic lock and idempotency are enforced;
- published content produces a draft revision;
- historical attempts are unchanged;
- before/after and actor audit are available;
- undo restores content through an attributable revision.

### Step 7. Quiz-level analysis and batch proposals

Analyze a quiz, list independently applicable findings, and allow selected batch remediation. Do not apply an all-or-nothing opaque rewrite.

Acceptance:

- findings are traceable to question IDs;
- methodologist can accept or reject each patch;
- duplicate and heuristic patterns are evaluated across the quiz;
- request and outcome metrics remain per patch and per batch.

### Step 8. Initial generation pipeline integration

Move the same structured quality contract into initial course/test generation. Generation must run validators and repair or reject weak assessment items before the draft is shown.

Acceptance:

- generation and editing use the same validator contract;
- no prompt-only bypass exists;
- draft displays unresolved warnings;
- publish gate handles blocking findings;
- old and new generator versions can be compared.

### Step 9. Lesson and course assistant

Extend structured operations to selected lesson blocks, lessons, modules, and course structure while preserving source grounding and version boundaries.

### Step 10. Product analytics dashboard

Add aggregate rework and acceptance metrics for authorized product administrators. Tenant administrators can see their own audit and usage; cross-tenant views use only normalized de-identified aggregates.

Acceptance:

- filters by period, entity type, intent, issue, source type, locale, generator/model/prompt/validator version, and outcome;
- no raw prompt or customer content in cross-tenant analytics;
- metrics definitions are documented and reproducible;
- low-volume cohorts are protected from accidental disclosure.

### Step 11. Evaluation and tuning gate

Create a versioned synthetic/de-identified evaluation corpus from confirmed recurring patterns, establish baseline scores, and define the approval path for prompt changes, model routing, or a future fine-tune.

## 10. Testing strategy

Unit tests:

- normalized intent and issue taxonomy;
- lifecycle transition state machine;
- analytics projection allowlist;
- patch scope and optimistic locking;
- validator heuristics;
- version binding.

Integration tests:

- tenant isolation and role authorization;
- request to preview to apply lifecycle;
- idempotent retries;
- stale-preview rejection;
- published-content draft creation;
- audit and feedback event persistence;
- raw instruction exclusion from logs and analytics projection.

Frontend tests:

- selected target visibility;
- no mutation before Apply;
- preview diff;
- validation warnings;
- reject/regenerate/apply flows;
- unsaved-state protection;
- accessibility and responsive layout.

Development E2E:

- generate a synthetic course and quiz;
- detect a deliberately length-biased quiz;
- request improved distractors;
- preview and apply one patch;
- reject another patch;
- publish a new draft version;
- verify prior learner history is unchanged;
- verify normalized metrics and audit readback without raw content leakage.

## 11. Release gates

For every step:

- root review of exact files and behavior;
- focused tests appropriate to the step;
- no unrelated worktree changes;
- no secrets or raw customer content in fixtures or evidence;
- `[Unreleased]` changelog entry only when behavior becomes user-visible;
- no version bump, commit, push, deploy, or production mutation by the implementation agent;
- development deployment and acceptance require a separate root release packet;
- CT125, VM126, and production require a separate owner approval after development acceptance.

## 12. Rollback

Each step must remain independently reversible. Schema additions are additive until the feature is accepted. UI is feature-gated until the backend contract is stable. Generator-quality gates remain versioned so a faulty threshold can be rolled back without rewriting historical results or deleting feedback evidence.
