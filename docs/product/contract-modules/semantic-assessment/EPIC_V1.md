# Semantic block assessment V1

Status: Accepted for implementation, not release GO.
Approved by: product owner, 2026-09-18, “исправляй. не забывай использовать дешевых агентов”.
Root owner: Codex. Block owner: Kant. Outcome owner: Mill. Assessment owner: root.
Independent reviewer: separate read-only worker after integration.
Change control: root records interface changes here as a versioned addendum;
scope/billing/production expansion requires owner authorization.

## Observable outcome and directed map

An autonomous course tests the meaning of its source blocks, not unrelated true
sentences. Source -> coherent blocks -> lesson plan -> generated candidates ->
independent option review -> bounded repair/drop -> persisted draft/outcome.

### Blocks V1

Responsibility: retain rule/conditions/exceptions and meaningful section boundaries.
Interface: `split_narrative_blocks(str) -> list[str]`; current SourceFact carries
one narrative block. Excel groups retain section+subject identity.
Stateless, no external calls, no ownership/migration change. No lesson padding,
no silent truncation. Independent sections cannot merge merely because short.
Read scope: V2 source/plan. Write: source_blocks.py, narrative engine plan/tests.
Errors: oversized block remains intact, downstream bound yields explicit omission.
Verification: paragraph exception, intro/list, decimals, tiny independent sections,
single paragraph -> single lesson, fact coverage. Not responsible for assessment.

### Assessment V1

Responsibility: source-block-owned candidates and one meaningful correct answer.
Interface: async `generate_block_assessment` consumes realized lessons, source
facts and existing tenant-resolved generation client; returns questions + audit.
Stateless. Root owns module/models/application adapters and tests. No database,
new provider, new settings or TypeSafe dependency. Existing provider timeout and
fallback policy applies; cancellation/progress checked between bounded calls.
Each candidate cites exact source quotes and IDs in the same block. False answers
may be counterfactual application errors, never required to be true source facts.
Independent reviewer sees no author answer key and checks every option for
same-question relevance, plausible error, and truth under supplied evidence.
One repair per rejected candidate, then review again or drop. No minimum quota.
Malformed/failed review never admits unreviewed questions; lessons are preserved.
Upper bound: three candidates per block group, not a requested quantity.
Contexts exceeding safe bounds are omitted with a typed reason, never truncated.
Verification: exact unrelated distractors, single nonnumeric rule, exceptions,
bad/partial review JSON, all-invalid, provider failure, repair bound, no padding,
active application seam and synthetic real-provider/TypeSafe DEV-only review.

### Outcome V1

Responsibility: saved V2 draft with zero questions is not reported completed.
Existing pipeline owns persistence/tenant context; retain course_id and counters.
No schema/API/role change; use compatible terminal state, no retry duplicates.
Read: pipeline/status consumers. Write: pipeline.py and outcome unit tests.
Verification: zero/nonzero questions, preserved draft, no-user path, retry guard,
legacy unchanged. No automatic regeneration of existing courses.

## Shared boundaries and acceptance

No frontend, auth, tenant/RLS, assignments, mail, billing or model routing changes.
Only V2 generation behavior changes; old courses are not mutated. No production
in this implementation loop. Stop for missing source context, cross-tenant data,
unsupported state consumer, or any unplanned dependency. Root review before resume.
Ready: interfaces fixed and exact defect reproducible. Done: focused + seam +
neighbor tests, real bounded synthetic evaluation, independent review; release
additionally needs full candidate gates and exact runtime smoke. Rollback is prior
immutable backend image; no migration. Logs contain IDs/counts/reasons, not secrets
or raw provider output. Development reports use synthetic data only.

## Accepted interface addendum V1.1 — retained draft UI (2026-09-18)

Root-approved implementation consequence of Outcome V1: existing interrupted-job
UI otherwise offers resume for a saved terminal review outcome. Extend the write
scope ONLY to `apps/web/src/app/ai/generate/page.tsx`, its page regression test,
and two corresponding labels in the existing ru/en/kk locale dictionaries.
When status is interrupted, errors contain `assessment_no_valid_questions`, and
course_id exists, show "Тесты требуют проверки" and "Открыть сохранённый черновик"
to the existing course edit route. Other interrupted/completed states unchanged.
No new API/schema, role, auth, routing or provider contract. This supersedes only
the no-frontend exclusion above. Any release must now include the tested web delta;
no backend-only release claim. Frontend tests/typecheck/lint are separate from a
production build and browser acceptance, which are not covered by local unit QA.

## Candidate addendum V1.2 — logical constraints and coverage audit

Local implementation only; acceptance remains NO_GO after repeated provider tests.
After general review, a separate blind check classifies cited rules and every
option as entailed/contradicted/undetermined. Its response is schema-checked;
unknown, partial or invented constraints cannot establish an acceptable question.
The same configured generation client and existing timeout/cancellation apply.
This adds one call per block with accepted candidates and potentially one after
the existing bounded repair; latency and provider failures are acceptance inputs.
No new provider or runtime TypeSafe dependency.

A narrow Russian guard rejects the reproduced required-answer/optional-exclusion
mistake even when the model endorses it. It is not a general semantic proof.
Audit additionally returns `questions_per_lesson` and `unassessed_lesson_ids`;
these expose missing coverage but do not enforce a question quota or independently
declare a course complete. Important assessable topics missing from a run fail
manual release acceptance. Automatic coverage policy still needs completion.

The local PDF OCR replay is explicitly labeled non-production conversion. Never
accept OCR-damaged source facts as proof of production generator behavior.

## Approved bounded iteration V1.3 — owner "делай", 2026-09-18

One-question repair is server-bound to the rejected question. The provider need
not reproduce repair_of; a changed identity must not move the result to another
question. Preserve tested knowledge and primary topic fact, permit additional
exact citations in the same source block, never cross-block evidence. Return a
specific repair reason. At most one repair per rejected candidate; accepted
questions are unchanged. No new model stage or provider routing change.

Assessment coverage is course-wide, source-scope-aware, not one quiz per lesson.
Expose explicit block outcomes (accepted, successfully no assessable questions,
rejected, unavailable) with IDs/counts. A substantive topic that produced
candidates but loses all of them, or whose generation failed, requires review
unless already tested by grounded evidence elsewhere in the same source scope.
A successfully empty introductory block is not a forced question quota.
This is a conservative missing-topic gate, not proof that every atomic fact is
tested. Root reviews learning objectives and source content in acceptance.

Root owns coverage/application/pipeline integration and current UI-compatible
saved-draft status, worker owns semantic repair and its tests. No new frontend
screens. Existing saved-draft action must continue to work; any incompatible
consumer requires an explicit contract update rather than a hidden new error.
No DB changes, publication or deployment in this iteration. Fresh original-PDF
conversion or verified saved converter output is required; local corrupt OCR
cannot substitute. Two isolated assessments per source precede full local runs.

## Approved local continuation V1.4 — owner "продолжай", 2026-09-18

Normalize production-converter source artifacts before lesson planning; exact
image-only markers/verified TOC are not instructional facts. Preserve domain
rules, limits and list-introduction context; no customer-specific content rules.
The general reviewer sees only each question's retained cited facts, not a
neighboring question's support. Require explicit practical-function and distinct
misconception judgments. The existing second blind constraint call independently
vetoes unrealistic wrong answers and duplicate misconceptions; no new model stage.
All negative checks remain bounded single-question repair/drop with topic audit.
Opt-in syntax recovery may make at most one same-provider correction per
validated call for JSONDecodeError, never for semantic rejection or transport
failure. Reuse the unchanged parser and transport limits; default callers retain
legacy behavior. Record this extra attempt, never claim zero additional latency.
No production, DB, provider routing/configuration, or frontend change in V1.4.

V1.4 integration: persist explanations as the exact deduplicated source quotes
validated by the parser, not the author's supplementary prose. This prevents
unsupported explanatory additions and author option-order references without
another model call. Source quotation is not itself proof that the question or
distractors are pedagogically sound. Preserve independent option-quality and
coverage gates. Constraint enum strings remain strict English values; explicitly
specify their allowed literals in the prompt rather than silently mapping an
unknown semantic category into an allowed one.

Navigation suppression requires an explicit contents marker, a sequential prefix
and corroboration with later body heading words. Number-only OCR duplicate TOC
labels are not content; numbered substantive prose that does not match body
headings must survive. Trim overlap navigation only at a verified body Markdown
heading. Ambiguous OCR order/wording is retained, not guessed or corrected by
customer-specific substitutions.
