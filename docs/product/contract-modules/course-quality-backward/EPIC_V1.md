# EPIC: обратная проверка качества курса (V1)

| Field | Value |
|---|---|
| Status | Accepted for local synthetic verification |
| Root owner | Codex root: interfaces, integration, review |
| Product owner / Approved by | Владелец Kamilya LMS, подтверждение четырёх интерфейсов 2026-09-23 |
| Module owner | Codex root for source mapping; other modules read-only until an impact addendum |
| Reviewer | Codex root through independent corpus oracle and existing regressions |
| Template | V2; initial V1 contract; Supersedes: none |
| Change control | Root proposes a versioned addendum for a new invariant; owner approves material product/release changes; root may cancel with cleanup. |

## Outcome and exclusions

Короткий источник с одной проверяемой темой даёт не более одного урока, а вспомогательный каталог не раздувает курс. Вопросы проверяются по отдельным смысловым блокам; неприменимые вопросы не добираются ради квоты. Исключены production, клиентские файлы, DB writes и изменения UX. Отдельно владелец разрешил до 8 ограниченных вызовов существующего DeepSeek-аккаунта на синтетике, максимум $2 без смены тарифа; предел вызовов исчерпан.

## States and critical journey

`synthetic source -> parsed sections -> source-owned plan -> lesson -> question/omission -> independent verdict`.
Критический путь `AI-COURSE-01` остаётся обязательным перед выпуском; локальная база не заменяет его.

## Directed module map and interfaces

`DirectSourceCorpus -> build_evidence_source -> EvidenceCourseEngine.generate_from_document -> generate_evidence_course -> generate_block_assessment`.

| ID | Producer interface | Consumer | Contract |
|---|---|---|---|
| SRC-01 | `build_evidence_source(corpus) -> SourceDocument` | EvidenceCourseEngine | A sole meaningful narrative section remains primary; reference-only sheets remain supporting when a primary sheet exists. |
| PLAN-01 | `generate_from_document(document) -> EvidenceCourseResult` | Course realization | Lesson count follows independent source topics, no quota padding. |
| LES-01 | `generate_evidence_course(corpus, intent, clients) -> EvidenceGenerationOutput` | Assessment | Lesson claims are traceable to admitted primary facts. |
| QUIZ-01 | `generate_block_assessment(lessons, facts, client) -> BlockAssessmentResult` | Saved draft | Questions are source-owned, distinct, and may be omitted rather than fabricated. |

## Impact matrix and negative space

| Module | Impact | Allowed change | Unchanged behavior |
|---|---|---|---|
| `document_passport.py` | Invariant | Refine reference-sheet classification for small catalogs | Primary teaching sheets stay primary. |
| `evidence_engine/application.py` | Invariant | Preserve a sole title-matching narrative section | Multi-section title/preamble remains supporting. |
| `evidence_engine/engine.py` | None initially | Tests only | Existing allocation and provenance unchanged. |
| `evidence_engine/semantic_assessment.py` | None initially | Tests only | Existing question review and no-padding behavior unchanged. |
| Routes, DB, queues, auth, legacy pipeline | None | No edits | Existing contracts unchanged. |

## Data, privacy, rollback, verification

Fixtures are synthetic, repository-owned, immutable golden inputs; no migrations or tenant state. Focused tests cover the four seams and neighboring regressions. Release requires full project risk gate and runtime readback, not authorized by this epic. Rollback of local candidate is dropping its unmerged branch after review; no destructive action is implied. Stop on an unlisted module, further provider spending, or a failing critical journey. Definition of done for this local phase: source/plan tests pass, independent question/lesson probes report exact failures, and no unsupported quality claim is made.
