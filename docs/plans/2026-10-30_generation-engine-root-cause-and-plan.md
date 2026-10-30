# Generation Engine Root-Cause Dissection & Concrete Improvement Plan (2026-10-30)

## 1. Branch & Worktree Baseline

- **Worktree**: `C:\Kamilya New\Kamilya-NEW\.worktrees\generation-quality-audit-20261030`
- **Branch**: `fix/generation-quality-audit-20261030`
- **Base Commit**: `5dd36ad0901a17afba37ea21269f8c44ba316d11` (`Restore validated lesson realizations without repeated inference`, parent `0f073bbe6ae6d8593dae7373ca891db87c8fce9d`)
- **Carried Uncommitted Delta**:
  - `apps/api/app/modules/ai/evidence_engine/application.py` (`_propagate_ordinary_table_spans` across adjacent chunk overlaps)
  - `apps/api/tests/unit/test_markdown_table_source_benchmark.py`
  - `scripts/dev/generation_quality_api.py`, `scripts/dev/run_generation_quality.py`, `scripts/tests/test_generation_quality_api.py`
- **Primary Checkout Guard**: `LINKED_WORKTREE_OK` (`write_allowed: true`). Primary checkout `C:\Kamilya New\Kamilya-NEW` and sibling worktrees (`cabinet-release-20261018`, `realization-resume-0f073`, `dev-fence-release-20261030`) remain untouched.

---

## 2. Executive Diagnosis: Why Lesson & Quiz Generation Produces Low Yield / Zero Accepted Questions

The generation pipeline in `apps/api/app/modules/ai/` is built around a multi-stage fail-closed architecture:
1. **Ingestion & Fact Extraction** (`evidence_engine/application.py`)
2. **Source Assessment Planning & Critic** (`source_assessment_plan.py`)
3. **Lesson Writing, Surface Review & Language Review** (`evidence_engine/provider_engine.py`, `lesson_surface_review.py`, `learner_language.py`)
4. **Final Teaching Eligibility & Custody Registry** (`final_teaching_eligibility.py`)
5. **Question Authoring, Blind Language Review, Semantic Review & Counterexample Audit** (`lesson_cycle.py`, `assessment_preservation.py`, `conditional_connective.py`, `worker_lesson_cycle.py`)

In the latest evaluation run (`standards-native-r1` on `стандарты26.docx`, 34 physical `gpt-6-luna` calls, $0.2566 spent), **2 of 4 lessons completed with 0/10 accepted questions**, and Lesson 3 failed on call 33 (`outcome_unknown` after 97.6s / 13,205 output tokens).

Forensic inspection of `response-0000.json`..`response-0032.json` and the deterministic validators reveals that the low quality / zero question yield is **not** random LLM hallucination; it is caused by **5 concrete structural collisions** between the LLM prompts/rewrites and the deterministic post-validators:

### Bottleneck 1 — Deterministic `final_teaching_not_proven` Kills Valid Questions When Lesson Blocks Normalize Russian Connectives or Critic Quotes Omit Leading `Если`
- **Evidence**: Lesson 2 (`lesson-91ac6a7a0c98dcf4`, `response-0027.json`). The semantic reviewer (`REVIEW`) marked `T1`, `T2`, `T3`, and `T4` as **100% preserved** across all components, teaching proofs, and options (`supported` = index 0, `contradicted` = index 1, `applied = true`, `lesson_answerable = true`). Yet `lesson_cycle.py:7815-7824` rejected all four with `lesson_assessment_review:final_teaching_not_proven` and added `T1..T4` to `terminal_critic_target_ids` (preventing Round 2 repair!).
- **Exact Code Root Causes**:
  1. **`T2:T1` & `T3:T1` (`native_coverage_unproved` in `conditional_connective.py:93-167`)**:
     - Source governing binding (`T2:T1`): `"в случае если микрокредит не согласован АУП РД."` (at the end of the source sentence, with a trailing period `.`).
     - Lesson block (`Tc26bd22c272d`): `"Если микрокредит не согласован АУП РД, эксперт-оценщикам категорически запрещается..."` (moved to the front of the sentence, no trailing period).
     - `component_preservation_issue` (`assessment_preservation.py:3547`) rejects `"в случае если"` -> `"Если"` with `missing_material_token` on token `"случае"`.
     - `conditional_connective_receipt` (`conditional_connective.py:150`) was designed specifically to allow `"в случае если C"` -> `"если C"`, **but** line 160 checks `source.canonical_tail != learner.canonical_tail` without stripping terminal clause punctuation (`.`, `,`, `;`, `:`) or trailing correlative `, то` (`В случае если C, то` in `T3:T1`). Because `"микрокредит не согласован АУП РД." != "микрокредит не согласован АУП РД"`, `conditional_connective_receipt` returns `None`!
  2. **`T1:T1` & `T3:T1` (`teaching_evidence_unproved` in `final_teaching_eligibility.py:1353-1384`)**:
     - Lesson block `T581ef8238e28` begins with `"Если общая сумма микрокредитов..."`.
     - In `response-0027.json`, the critic quoted `teaching_quotes: {"T581ef8238e28": "общая сумма микрокредитов..."}` — omitting the leading word `"Если"` from the quote span even though `"Если "` immediately precedes the quote in block `T581ef8238e28`.
     - `_native_requirement_issue` (`final_teaching_eligibility.py:1356`) checks `component_preservation_issue(alternative.text, quote.text)`, which fails with `missing_protected_operator` (`*Если`, token 0). And because `source_Context` also changed colloquial `"и на одном филиале"` to grammatical `"в одном филиале"`, `T1` was terminally dropped.
  3. **`T4:T2` (`native_coverage_unproved` on parenthetical expansion & verbal-noun compression)**:
     - Source governing binding (`T4:T2`): `"за осуществление неверной оценки (нарушение внутренних инструкций...) залогового имущества..., причинившей Работодателю прямой действительный ущерб"`.
     - Lesson block `T3fcbfd72e456` rewrote `"за осуществление неверной оценки"` as `"за неверную оценку"` (dropping the empty verbal noun `"осуществление"`) and extracted the 40-word parenthetical list into clean bullet points (`К указанной оценке относятся случаи: • ...`).
     - `component_preservation_issue` rejected it on token index 1 (`missing_material_token`: `"осуществление"`) and word-order displacement of the parenthetical list.

### Bottleneck 2 — Source-Verbatim Typography & Inflection Deadlock (`learner_language.py` vs Source Fidelity)
- **Evidence**:
  - **Lesson 1 (`lesson-8f29851764543c36`, `response-0009`..`0013`)**:
    - In Round 1 (`response-0009`..`0011`), all 4 questions failed `application_not_proven` because the author wrote `"Заявка поступила из РД г. Усть-Каменогорск..."` without stating `"I категория"` / `"II категория"` in the visible stem (leaving the category only in governing metadata).
    - In Round 2 (`response-0012`), the author fixed the stem to include `"в карточке указана I категория"`, and included the verbatim source table phrase `"для РД г. Усть-Каменогорск, г. Павлодар..."`.
    - Then the blind language reviewer (`response-0013`, `learner_language.py`) rejected all 4 questions (`grammatical: false`) because in standard Russian, toponyms after `"из РД г. Усть-Каменогорск"` / `"для РД г. Усть-Каменогорск"` should be inflected (`г. Усть-Каменогорска`), even though the source table literally uses nominative (`для РД г. Усть-Каменогорск, г. Павлодар...`).
  - **Lesson 2 (`fact-5966896619838659`, Rule 5, `response-0020`..`0026`)**:
    - Source text literally says: `"За неисполнение, ненадлежащее исполнение настоящих Стандартов эксперт-оценщиком, АУП РД, предусмотрена дисциплинарная ответственность... согласно “Положении о категориях нарушений...”"`.
    - When preserved verbatim, `learner_language.py` rejects `"согласно «Положении...»"` (`government: false`, requires dative `"Положению"`).
    - When repaired to `"Положению"` (`response-0021`), `lesson_surface_review.py` (`response-0022`) and `learner_language.py` (`response-0024`) reject `"эксперт-оценщиком, АУП РД"` (`grammatical: false, relation_coherent: false`) because two instrumental nouns are joined by an asyndetic comma instead of `"и"`.
    - Because surface review rejected block `B7-162e46230fff`, `provider_engine.py` fell back to raw source text `"### Правило 5\n\n5. За неисполнение..."` and **excluded `B7` from the `final_teaching` custody catalog**. As a result, question `T6` automatically failed `final_teaching_not_proven` (`teaching_proofs: missing`).

### Bottleneck 3 — Cross-Block Teaching Context Split within a Single Source Fact (`T5:T2` Missing Contract Scope)
- **Evidence**: `fact-2b01a3bcac4f8588` is a single compound sentence governed by `"Согласно договора о полной коллективной (солидарной) материальной ответственности сотрудников"`, establishing both joint liability (`T4`) and the duty of care (`T5`: `"а также обязаны бережно относиться..."`).
- The lesson writer (`response-0018`) split `fact-2b01a3bcac4f8588` into two Markdown sections: `### Солидарная ответственность` (`T3fcbfd72e456`) and `### Бережное отношение к имуществу` (`Ta12661caa261`), placing `"Согласно договору..."` only in the first block and leaving `depends_on_block_ids = ()` on the second block.
- Both `REVIEW` (`response-0027`) and `COUNTEREXAMPLE` (`response-0031`) rejected `T5` because `Ta12661caa261` alone does not state the contract scope `T5:T2` (`"The contract scope appears with the liability discussion, while the separately taught care duty is not linked to that condition"`).

### Bottleneck 4 — Ingestion Chunk Overlap Leaks Table Tails into Narrative Facts (Partially Fixed in R4)
- **Evidence**: In `standards-native-r1`, `fact-dc428898f6a85596` under Heading 2 (`Порядок согласования...`) began with the trailing 220 characters of Table 1's last row (`. Петропавловск, г. Актобе... Семей |`).
- This caused the lesson writer (`response-0018`, `response-0021`) to invent a meaningless block `### Города и обозначения`, which failed `lesson_surface_review` (`readable: false, ocr_clean: false`) and wasted a full repair round.
- The uncommitted `_propagate_ordinary_table_spans` change in `apps/api/app/modules/ai/evidence_engine/application.py` resolves this for adjacent overlapping chunks and is already carried into this branch.

### Bottleneck 5 — Oversized Single-Call Source Plan Extraction (`outcome_unknown` Timeout on Lesson 3)
- **Evidence**: Call 33 (`response-0032.json`) attempted to extract the `source_assessment_plan` for Lesson 3 (`fact-8481ca1fe25dd52f`, dense multi-condition Lombard appraisal rules), generating 13,205 tokens (5,882 reasoning + 7,323 content) over **97.6 seconds** before failing with `outcome_unknown`.
- When a single fact or lesson slice contains many dense normative clauses, a monolithic `source_assessment_plan` call with `max_completion_tokens=32768` approaches the 90–100s HTTP/provider timeout window and risks losing the entire call cost on `outcome_unknown`.

---

## 3. Concrete Phased Plan of Code Fixes

### Phase 1: Fix Deterministic Teaching Eligibility & Conditional Connective Custody (Unblocks `T1`, `T2`, `T3`, `T4`)
- **Files**:
  - `apps/api/app/modules/ai/conditional_connective.py`
  - `apps/api/app/modules/ai/final_teaching_eligibility.py`
  - `apps/api/app/modules/ai/assessment_preservation.py`
- **Changes**:
  1. **Clause-Boundary Punctuation & Correlative `, то` in `conditional_connective.py`**:
     - Update `_SOURCE_SHAPE` and `_LEARNER_SHAPE` / `_parse()` so bounded clause-boundary punctuation (leading `*` bullet markers, trailing `.`, `,`, `;`, `:`, and trailing correlative `, то` in `"В случае если C, то"`) is recorded in receipt offsets and normalized before comparing `source.canonical_tail == learner.canonical_tail`.
     - Preserve fail-closed raw SHA256 addressing (`source_tail_start`, `source_tail_end`, `receipt_sha256`) and reject nested conditionals (`_NESTED_IF`).
  2. **Block-Envelope Connective Fallback in `final_teaching_eligibility.py` (`_native_requirement_issue`)**:
     - When the critic's `teaching_quote` is an exact substring of the cited `SupportedTeachingBlockRef.body` that omits only the immediately preceding conditional connector (`"Если "` / `"В случае если "`) already present in that same `entry.body`, bind the proof to the block-anchored envelope (`[connector + quote]`) rather than failing with `missing_protected_operator` (`teaching_evidence_unproved`).
  3. **Lesson Writer & Surface Review Preservation Guidance (`provider_engine.py`)**:
     - Instruct the lesson writer and surface repair prompts to preserve source governing verbal nouns (`за осуществление неверной оценки`) and locative prepositions (`и на одном филиале` or exact parenthetical governing phrases) verbatim when restating normative conditions, rather than dropping `"осуществление"` or rewriting parentheticals into detached sentences that break `component_preservation_issue`.

### Phase 2: Resolve Source-Verbatim Typography & Inflection Collisions (Unblocks Lesson 1 `T1..T4` & Lesson 2 `B7`/`T6`)
- **Files**:
  - `apps/api/app/modules/ai/learner_language.py`
  - `apps/api/app/modules/ai/lesson_surface_review.py`
  - `apps/api/app/modules/ai/lesson_cycle.py`
- **Changes**:
  1. **Source-Verbatim Span Custody in `learner_language.py` & `lesson_surface_review.py`**:
     - Pass verified verbatim source spans (such as quoted document titles `«Положении о категориях нарушений...»`, tabular regional nominative lists `для РД г. Усть-Каменогорск, г. Павлодар`, and source actor enumerations `эксперт-оценщиком, АУП РД`) in the language-review payload as `source_verbatim_spans`.
     - Update `LEARNER_LANGUAGE_PROMPT` (`learner_language.py:55-97`) and surface language review (`lesson_surface_review.py`) so the blind language critic does **not** set `grammatical: false` or `government: false` solely due to an exact source-verbatim official title quote or tabular regional designation (`РД г. <Топоним в им. п.>`), OR allow bounded grammatical inflection of quoted document titles (`«Положению...»`) and `и`-coordination (`эксперт-оценщиком и АУП РД`) in `assessment_preservation.py` (`allow_nominal_spelling=True` / morphological match already equates `Положении` and `Положению` via `_morph()`!).
  2. **Prevent Surface Review Refusal from Silently Orphaning `final_teaching` Custody**:
     - In `provider_engine.py` / `lesson_surface_review.py`, when a single block (like `B7`) fails surface polish only on source-verbatim syntax (`эксперт-оценщиком, АУП РД`), do not drop the block from `teaching_catalogs` when falling back to the grounded source text if all source tokens and facts are intact.

### Phase 3: Cross-Block Governing Scope Propagation within Shared Source Facts (Unblocks `T5`)
- **Files**:
  - `apps/api/app/modules/ai/evidence_engine/provider_engine.py`
  - `apps/api/app/modules/ai/final_teaching_eligibility.py`
  - `apps/api/app/modules/ai/lesson_cycle.py`
- **Changes**:
  1. **Shared-Fact Sibling Block Dependency or Explicit Governing Restatement**:
     - When `provider_engine.py` splits a single `SourceFact` (`fact-2b01a3bcac4f8588`) into multiple consecutive `GroundedBlock` subheadings (`T3fcbfd72e456` and `Ta12661caa261`), either:
       - Automatically populate `dependency_refs` (`depends_on_block_ids`) across consecutive blocks derived from the same `fact_id` so the critic and `final_teaching_eligibility.py` see the complete fact teaching unit (`T3fcbfd72e456` + `Ta12661caa261`), **and**
       - Instruct the lesson writer that every split sub-block teaching an independent obligation (`а также обязаны бережно относиться...`) must retain its governing scope (`Согласно договору о полной коллективной (солидарной) материальной ответственности сотрудников`).

### Phase 4: Explicit Governing Category Premise in Scenario Authoring (Prevents Round-1 `application_not_proven` Waste)
- **Files**:
  - `apps/api/app/modules/ai/lesson_cycle.py`
- **Changes**:
  - In `lesson_cycle.py` (`AUTHOR` prompt / target wire projection), when a target has a `governing_bindings` or `context` qualifier (such as `"I категория"` / `"II категория"` from a table header row), explicitly surface it in `required_scenario_premises` so Round 1 `AUTHOR` includes the category in the visible learner stem (`text` / `learner_premise`) on the first pass instead of wasting Round 1 on `application_not_proven`.

### Phase 5: Freeze R4 Table-Overlap Fix & Bound Long Source-Plan Extraction Calls
- **Files**:
  - `apps/api/app/modules/ai/evidence_engine/application.py`
  - `apps/api/app/modules/ai/source_assessment_plan.py`
- **Changes**:
  1. Keep `_propagate_ordinary_table_spans` in `evidence_engine/application.py` (tested in `test_markdown_table_source_benchmark.py`).
  2. In `source_assessment_plan.py`, partition or cap per-call fact batches when total fact character length or table density exceeds safe single-call reasoning bounds so calls do not hit the ~95s `outcome_unknown` timeout seen on `response-0032.json`.

---

## 4. Concrete Verification Plan (4 Sequential Gates)

### Gate 1 — Zero-Call Deterministic Replay Suite (Cost: $0.00)
Build a deterministic pytest replay suite (`apps/api/tests/unit/test_standards_native_r1_replay.py`) using the sanitized shapes from `standards-native-r1` (`response-0009`..`response-0031`):
1. Verify `conditional_connective_receipt` admits:
   - `"в случае если микрокредит не согласован АУП РД."` -> `"Если микрокредит не согласован АУП РД"` (`T2:T1`)
   - `"В случае если на момент согласования микрокредит погашен и залоговое имущество возвращено заёмщику, то"` -> `"Если на момент согласования микрокредит погашен и залоговое имущество возвращено заёмщику"` (`T3:T1`)
   - Negative control: still rejects altered nouns, dropped negations (`не`), or nested `если`.
2. Verify `bind_final_teaching_role` (`final_teaching_eligibility.py`) admits `T1`, `T2`, `T3`, `T4` from Lesson 2 (`response-0027.json`) and `T5` once sibling fact block dependency is linked.
3. Verify `learner_language.py` / `lesson_surface_review.py` admits source-verbatim tabular city headers (`для РД г. Усть-Каменогорск`) and Rule 5 (`fact-5966896619838659`) without breaking negative controls (actual ungrammatical LLM hallucinations remain rejected).

### Gate 2 — Canonical API Unit Suites & Python Quality Baseline (Cost: $0.00)
Run inside `C:\Kamilya New\Kamilya-NEW\.worktrees\generation-quality-audit-20261030`:
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/dev/run_api_pytest.ps1 `
  apps/api/tests/unit/test_markdown_table_source_benchmark.py `
  apps/api/tests/unit/test_final_teaching_eligibility.py `
  apps/api/tests/unit/test_learner_language_critic.py `
  apps/api/tests/unit/test_lesson_cycle.py `
  apps/api/tests/unit/test_worker_lesson_cycle.py `
  scripts/tests/test_generation_quality_api.py -q

powershell -NoProfile -ExecutionPolicy Bypass -File scripts/dev/run_python_quality_baseline.ps1
```
**Pass criterion**: 100% tests pass; Ruff + Mypy = 0 errors across all 775 files.

### Gate 3 — Isolated Supabase DEV PostgreSQL & RLS Gate (Cost: $0.00)
Run the canonical Supabase DEV contour test (`realization-postgres-gate`, never local Docker PostgreSQL) to verify checkpoint persistence, RLS isolation, and `lesson-realization` reuse across worker restarts.

### Gate 4 — Bounded Local Model Acceptance Run (`standards-native-r2`, Budget Cap <= $2.00)
Only after Gates 1–3 are 100% green and with explicit owner go-ahead for the bounded local run:
1. Run `scripts/dev/run_generation_quality.py` on `стандарты26.docx` (`standards-native-r2`, cap `$2.00`) and verify:
   - `fact-dc428898f6a85596` contains zero leaked table-tail text (`Петропавловск... Семей |`).
   - Lesson 1 (`lesson-8f29851764543c36`) and Lesson 2 (`lesson-91ac6a7a0c98dcf4`) retain accepted questions (`ready_for_methodologist` or high target retention instead of `0/4` and `0/6`).
   - Lesson 3 completes source planning without `outcome_unknown`.
2. Re-evaluate against the 3-document Lombard benchmark (`67` target families / `16` fail-closed ambiguities) before promoting to `origin/master` and `kamilya-api-dev`.

---

## 5. Alignment with the 8 Architectural Principles (`P1`–`P8`)

1. **P1 — Plan learning before answer formats (`prepare_source_plan` / `audit_first` before `question_format`)**:
   - `WorkerLessonAssessor.prepare_source_plan` (`apps/api/app/modules/ai/worker_lesson_cycle.py`) builds the audited `source_learning_contract` (`audit_first=True`) before lesson authoring and before any question format (`question_format`) is realized.
   - `build_source_assessment_plan` (`apps/api/app/modules/ai/source_assessment_plan.py`) now also bounds primary-fact batches by total character volume (`_plan_primary_groups`, `<= 2200` chars and `<= 4` facts per batch) so dense multi-condition lessons never time out during pre-author source planning.
2. **P2 — Pass small documents as a whole with their structure**:
   - `select_assessment_context` (`apps/api/app/modules/ai/context_projection.py`) uses `mode="full"` for documents within `MAX_RAW_SOURCE_CHARS` (24,000 chars) / `MAX_RENDERED_SOURCE_CHARS` (32,000 chars), and `_propagate_ordinary_table_spans` (`apps/api/app/modules/ai/evidence_engine/application.py`) prevents adjacent chunk overlaps from leaking table tails into narrative headings.
3. **P3 — Allow natural explanations and workplace scenarios while separating fictional case premises from source assertions**:
   - `conditional_connective.py` and `final_teaching_eligibility.py` (`_expand_block_conditional_quote`, `_unpacked_parenthetical_condition_match`) allow natural Russian conditional connectors (`В случае если ... , то` -> `Если ...`) and structured bullet unpacking of parenthetical conditions in lesson explanations while keeping source propositions strictly verified.
   - `lesson_cycle.py` (`AUTHOR`) requires explicit category/tier qualifiers (`I категория`, `II категория`) in Round-1 scenario stems while separating workplace situation premises (`learner_premise`) from source-attributed claims.
4. **P4 — Verify the final "lesson — test" pair jointly**:
   - `assess_with_teaching` (`apps/api/app/modules/ai/worker_lesson_cycle.py`) and `bind_final_teaching_role` (`apps/api/app/modules/ai/final_teaching_eligibility.py`) jointly verify every candidate question against the final `FinalTeachingCatalog` of the rendered lesson.
5. **P5 — Route critiques/remarks to the stage capable of fixing them**:
   - `lesson_surface_grammar.py` (`_normalize_soglasno_dative`, `preposition_soglasno_dative_government`) and `component_surface_comparison.py` deterministically normalize `согласно + предложный/родительный падеж` (`согласно «Положении...»` -> `согласно «Положению...»`, `Согласно договора...` -> `Согласно договору...`) before critic review/repair.
   - `_surface_second_repair_actionable` (`apps/api/app/modules/ai/evidence_engine/application.py`) now allows a second targeted repair round when `language_target_feedback` provides a fresh `problem_quote`, even when `surface_review` simultaneously flagged presentation axes (`grammatical`, `readable`).
6. **P6 — Remove destructive semantic deduplication heuristics on normative text**:
   - `provider_engine.py` (`_GROUNDING_STOPWORDS`, `_normative_operators`, `_redundancy_tokens`, `_is_covered_sentence`) no longer treats normative operators (`не`, `без`, `до`, `более`, `только`, `или`, `not`, `only`) as stopwords and never deduplicates sentences whose normative operators or numbers (`op:*`, `num:*`) differ.
7. **P7 — Single canonical quality path across local runs, DEV, and production**:
   - `generate_evidence_course` + `WorkerLessonAssessor(learner_language_gate=True)` is used identically across local quality runs (`scripts/dev/run_generation_quality.py`), DEV, and production worker execution.
8. **P8 — Count actual dispatches, token usage, and wall time across the entire job**:
   - `llm_client.py` (`_LLMResponse`, `ValidatedLLMResult`), `worker_lesson_cycle.py` (`_MeasuredClient`, `WorkerLessonAssessor`), `application.py` (`generate_evidence_course`, `to_generation_artifacts`), `scripts/dev/generation_quality_api.py`, and `scripts/dev/run_generation_quality.py` propagate and aggregate `prompt_tokens`, `completion_tokens`, `chat_attempt_count`, `logical_model_calls`, and stage `timings` end-to-end.
