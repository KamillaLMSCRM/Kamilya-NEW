# Первый этап: узкий A и подготовка C

Status: Narrow A implemented and locally verified 2026-11-05; C0 provenance
inventory recorded. Local candidate only: no push, deployment, feature-flag
activation, database/provider mutation or formal release approval.
Owner: requesting product owner; integration/acceptance: root.

Independent root correction packet2026-11-05: discrete journal/catalogue filter
changes now push history (typing still replaces); module-title edits participate
in workspaceDirty navigation/readiness/publish guards. Full first100 catalogue
pages do not provide complete course totals: dashboard shows `—`, list/selector
limits are disclosed, job counters explicitly cover loaded jobs. Explicit job
recovery cannot overwrite newer start/retry/reset. Role-boundary and all touched
surface axe checks are recorded separately in NARROW_A_REVIEW_NOTES.md and ledger.
These closures supersede the earlier A3/A4 deferrals, not the external release gates.

## Результат для методолога

На существующем `/dashboard` сначала видны ситуации, требующие действия.
Пользователь открывает конкретное задание/курс/назначение, понимает причину
и следующий шаг. Объектное меню и canonical routes сохраняются. Согласование
доступно из курса, а не превращается в новый глобальный раздел конфигурации.
Подготовка C показывает readonly связь источник → урок → вопрос; не создаёт
нового решения об одобрении.

## Scope и порядок работ

| ID / порядок | Что меняем при будущей реализации | Зависимость / условие | Критерий приёмки |
|---|---|---|---|
| A0 | Зафиксировать текущие сценарии, DTO и целевые deep links | Exact candidate SHA; существующие API и registry, без provider/DB mutation | Для каждого типа задачи указан source, ID, status, href, active role; неизвестные поля явно помечены, не додуманы |
| A1 после A0 | Переставить «Требует внимания» выше сводных процентов; дать заголовок/подсказку следующего действия | Существующая dashboard model | DOM и visual order совпадают; клавиатура идёт в том же порядке; нулевые данные отличимы от недоступных |
| A2 после A0 | Кликабельные job rows и контент-метрики с точными фильтрами | Подтверждённый экран восстановления job и поддержка query; существующие course filters | Попадание в нужный объект, не в пустой мастер; метрика открывает заявленный срез. При отсутствии target показывается честное объяснение, новая route/API не изобретается |
| A3 после A0 | Вход к слабым вопросам с выбором курса до перехода либо с переданным course_id | LearningActionCenter focus/course contract | Пользователь не попадает в тупик; course сохраняется в URL; back возвращает фильтры; no-course предлагает выбор, а не ложные результаты |
| A4 после A0 | Уточнить существующие contextual approval links в редакторе; вход в приглашения из staff | Существующие routes/capabilities; проверить разные active roles | Approval сохраняет courseId; dirty form guard блокирует потерю текста; invitations доступен методологу; student/admin не получают новые learning mutations |
| A5 параллельно после A0 | Адресная a11y/i18n: dashboard, затронутые переходы, tabs документов, move controls редактора; candidate states/copy | Существующие RU/KK/EN ключи и locale formatter; определения loading/empty/error | Области нажатия/spacing проходят 2.5.8; tabs имеют корректный keyboard/panel contract либо являются фильтрами с aria-pressed; candidates: загрузка, пусто, ошибка, список различимы; нет сырых enum/фиксированного ru-RU |
| C0 после A0 | Inventory provenance: persisted refs, source revision, lesson/question version, validation status | Read-only DTO/schema review; никаких новых полей без контракта | Таблица available/missing/unknown, различие current vs historical source; нельзя приписывать review новой версии |
| C1 после C0 | Readonly prototype source/lesson/question, состояния missing/stale | Только synthetic fixtures | Виден текст вопроса, варианты и правильный ответ, версия и основание; «нет данных» не выглядит проверенным; никаких accept/apply/publish |
| A6 после A1–A5 | Сценарная приёмка кандидата приложения | Реализация отдельно согласована; собранный неизменённый кандидат | Пять journeys ниже + tests/typecheck/lint/build и независимый review; prototype evidence не засчитывается вместо app evidence |

## A0 — verified data/route map (2026-11-05)

Source inspection was performed on candidate HEAD `739cc5fd` in
`learning-visual-prod-20261102`. CodeGraph preflight returned `NOT_READY`
(checkout-local runtime missing), so this map comes from bounded `rg` and direct
source/DTO reads. It records only contracts that exist in this checkout.

| Action | Current source | Identity | State owner | Destination / query | Context preservation | Authorization | Availability | Verdict |
|---|---|---|---|---|---|---|---|---|
| Failed/interrupted generation | `GET /v1/ai/jobs` → `AIJobResponse` (`id`, `status`, `job_type`, `course_id`, `updated_at`, `errors`); `GET /v1/ai/jobs/{id}`; resume/cancel endpoints; dashboard `loadMethodologistDashboard` already reads jobs | job `id`; `course_id` may be `null` | `AIJob.status` = `pending`, `running`, `completed`, `failed`, `cancelled`, `interrupted`; `stage`/`message`/`errors` | `/ai/generate?job_id=<id>`; frontend-only `job_id` query handling added; page fetches the job and shows progress/failure context without starting a new job | No `return_to` on the generate route; localStorage active-job context remains for new visits; explicit `job_id` takes precedence for display and is removed when a new generation starts; no dirty-form guard on this page | `require_ai_job_access` = `methodologist`, `superadmin`; dashboard itself is methodologist-only | Job list failure → `jobsAvailable=false`, `—` and content-unavailable notice; detail 404 → documents fallback with honest notice; polling/loading/error states already exist | Implement with existing API + frontend query support; no backend change |
| Course awaiting review | Editor course read (`id`, `review_status`, `ai_generated`, blueprint marker); approval page `listApprovalCourses`/requests | `course.id`; approval request/attempt IDs on the approval page | `Course.review_status` = `pending`, `approved`, `needs_changes`; approval request statuses owned by approval service | `/admin/course-approvals?courseId=<uuid>`; page reads `courseId` and selects the course | Editor `handleGuardedLink` protects lesson text for the toolbar link; the duplicate readiness-nav link now uses the same guard; browser back returns to the editor | Editor: methodologist authoring; approval page: `admin` may configure the policy and read requests/reviews, `methodologist` may request/review | Editor load error is distinct; approval page has loading/error/empty/read-only states | Implement the existing entry, guard the duplicate link; do not change approval semantics |
| Overdue learning | Dashboard `TrainingAttentionItem`; training-log list/summary APIs; `parseTrainingLogBrowserQuery` | `enrollment_id`, `course_id`, `issue_type` | Training status `assigned`/`in_progress`/`completed`/`overdue`; assessment `failed`/`exhausted`; issue types `overdue`/`failed_required_quiz`/`stalled`/`not_started` | `/training-log?enrollment_id=<uuid>&course_id=<uuid>&return_to=/dashboard`; assignment operations `/assignments?course_id=<uuid>&enrollment_id=<uuid>` | URL carries object IDs and supported filters; `return_to=/dashboard` supported; back/reload restore the same query | `view_training_reports` for the journal (methodologist/admin); action-center mutations remain methodologist-only | Missing summary → `—`; list loading/error/empty/filtered-empty/truncated states exist; export controls require loaded rows | Existing contract; keep links as-is |
| Weak questions | `GET /v1/admin/learning-actions?course_id=<uuid>` returns `weak_questions`; focus query parser supports `action_focus=weak_questions` | `course_id` required for question results; `question_key`, `quiz_id`, `content_release_id` | Weak-question count/active actions owned by learning-actions payload | `/training-log?course_id=<uuid>&action_focus=weak_questions#learning-action-center` | `course_id` and `action_focus` are URL-backed; catalogue selection must update the same query | Methodologist only (`LearningActionCenter` and training-log route) | No course → no question list, currently only an instruction; catalogue has loading/error/partial states | Implement an in-place course selector using the existing `/v1/courses` catalogue; no new API |
| Content metrics | `GET /v1/courses` supports exact `status=draft|published|archived` and `per_page` up to 100; default excludes archived; dashboard reads the first 100 courses and marks counts as truncated when the page is full | none; catalogue filter | `Course.status` = `draft`, `published`, `archived` | `/courses?status=published` and `/courses?status=draft`; all-courses `/courses`; URL filter is frontend-only | URL filter initializes from and synchronizes with the query, survives reload/back and is resettable; the catalogue shows a first-100 notice when truncated | `manage_content` for the catalogue; dashboard is methodologist-only | API failure → `—` plus content-unavailable notice; catalogue has loading/error/empty/filtered-empty states | Implement course metric links and URL filter; job metrics stay non-links because `/ai/generate` has no status filter |
| Staff invitations | Route registry `/invitations` capability `manage_learners`; canonical invitations page; legacy `/admin/invitations` prefix | none | Invitation status/delivery status owned by invitations module | `/invitations` | No query contract needed; back returns to staff | Methodologist (`manage_learners`); admin lacks this capability, and staff page is methodologist-only | Invitations page has loading/error/empty states | Implement a contextual staff-page link; no new capability |
| Journal evidence | Training-log evidence export controls (`downloadIndividualEvidence`, `downloadGroupEvidence`, CSV) with the same filter query | `enrollment_id`, `course_id`; evidence event ID per row | `evidence_state` = `forming`/`ready`/`incomplete`/`revoked`/`legal_hold`; signed-copy statuses | Same `/training-log?...` object/filter context; export is an action on loaded rows | Export uses the existing filter query; URL filters survive reload/back | `view_training_reports`; export permissions unchanged | No rows → export disabled; loading/error/partial states exist | Existing contract; no change |

A0 exit notes:

- Every link above has a receiving route that reads the stated query. The two
  frontend-only additions are `job_id` restoration on `/ai/generate` and `status`
  initialization/synchronization on `/courses`; neither needs a backend change.
- Job rows must not claim a course title the API does not return. `AIJobResponse`
  has no `course_title`, so the honest fallback is the existing
  “course generation”/“failed generation” label.
- The dashboard must keep unavailable data distinct from zero; no new totals are
  derived from the truncated visible list. Course counts and the weak-question
  selector explicitly mark the first-100 page when it is full.
- The content metrics “active generations” and “generations with issues” stay
  non-links until a supported destination filter exists.

## C0 — provenance inventory (read-only, verified 2026-11-05)

This inventory answers what the application can show without inventing a new
review decision. It is not a new persistence contract.

| Item | Availability | Verified source / gap |
|---|---|---|
| Persisted lesson source references | Available | `Lesson.source_references` is persisted; module responses expose module-level `source_references`; the course preview endpoint exposes lesson-level references; the release snapshot persists them |
| Source document revision / snapshot identity | Partially available | `Document.version` and `Document.content_sha256` exist; chunk metadata uses `document:<sha256>` as `source_revision`; the release snapshot has `snapshot_sha256` and `release_version`, but lesson references carry `doc_id`/`chunk_id` rather than a document version field |
| Lesson version identity | Missing as an explicit version | `Lesson` has `created_at`/`updated_at` and a persisted `source_validation_status`, but no lesson version number; the release snapshot is the historical evidence |
| Question version identity | Missing as an explicit version | `Question` has no `updated_at` or version; quiz attempts carry `content_release_id`; the release snapshot pins question content, choices, and order |
| Existing source-validation states | Available | `source_validation_status` values include `not_applicable`, `verified`, `needs_review`; approval of a course sets remaining `needs_review` lessons to `verified` |
| Available source fragments / locators | Available in preview/release | References contain `chunk_id`, `doc_id`, `doc_name`, `headings`, `query`, and optional `distance`; full lesson text is available through lesson endpoints |
| Access after the generation wizard closes | Partial | The preview and release snapshot retain lesson source references and validation; the backend reviewer-safe snapshot also retains them; the ordinary `LessonResponse` omits `source_references` and `source_validation_status`, so the editor's lesson read does not expose them directly; the current frontend `projectReviewSnapshot` strips them before rendering the reviewer snapshot |
| Current source vs historical evidence | Distinguishable only where a release exists | The release snapshot is immutable and carries `snapshot_sha256`/`release_version`; a current document revision can differ from the revision used at generation; the backend reviewer projection keeps provenance, but the current frontend reviewer DTO drops it, so the rendered approval view does not show source validation |

C0 consequences:

- A source being current is not proof that it supports the answer; C must show
  `available`, `missing`, or `unknown`, not infer “verified”.
- A historical approval must not appear to approve edited content. The release
  snapshot is the historical boundary; current lesson edits need their own
  validation state.
- No question-level accept/return, mandatory outline, new provenance field, or
  migration is introduced by this packet.

A2/A3 — dependency gates. Если API не поддерживает нужный object link/filter,
не расширять backend внутри A: оставить доступную ручную навигацию с точной
подсказкой, записать gap и отдельно оценить контракт. Новые task totals не
вычисляются из усечённого списка. Серверные totals отсутствуют → `—`/«нет данных».
Очередь на первом этапе — представление существующих данных, не новый backend.

## Точные implementation seams (кандидаты, не полный заранее заданный diff)

- `apps/web/src/features/dashboard/{MethodologistDashboard,api,model}.ts*`:
  hierarchy, существующие данные и links; не дублировать статусную логику.
- `apps/web/src/features/learning-actions/LearningActionCenter.tsx` и
  `app/admin/training-log/query.ts`: существующие focus/filter ссылки.
- `apps/web/src/app/courses/[id]/edit/page.tsx`: текущие approval links,
  dirty guard и hit targets; не менять release/approval semantics.
- `apps/web/src/app/admin/staff/page.tsx`: contextual invitations link;
  structure-v3 flag сохраняется.
- `apps/web/src/app/documents/page.tsx`, `app/candidate-assessments/page.tsx`,
  locale files и соответствующие существующие tests: A5.
- `routeRegistry.ts`, Layout/Sidebar/CommandPalette остаются policy owners;
  consumer changes требуют matrix tests, а не копирования capability logic.

Перед implementation: CodeGraph search → bounded callers/callees выбранного
символа; проверить свежесть. В audit checkout runtime missing; это source
fallback для текущего document/prototype packet, не основание пропускать
навигационный preflight следующего writer.

## Явные не-цели

- Нет entity search, новых notifications/digests, новых агрегатов, saved views,
  bulk publish, вопросного банка и новых типов вопросов.
- Нет новых глобальных пунктов для всех скрытых routes; surveys/announcements
  остаются отдельным backlog, пока не определена пользовательская задача.
- Нет default-on workbench/structure-v3, mandatory outline, формального решения
  на уровне вопроса, перестройки IA и объединения assignment engines.
- Нет новых provenance persistence/API/migration; gaps — выход подготовки C.
- Нет новых ролей, объединения active-role capabilities, tenant/RLS обходов,
  изменений истории, OTP/retention/approval, production/deploy.

## Приёмка приложения: пять сценариев

1. **Проблемная генерация:** найти job → открыть правильный job/status/recovery
   screen → понять безопасное следующее действие. Навигация не запускает AI
   повторно и не создаёт второй job.
2. **Проверка курса:** открыть конкретный курс → найти существующее согласование
   → сохранить courseId. Несохранённый текст защищён cancel/save/discard flow;
   старое решение не маркирует изменённую версию как проверенную.
3. **Просрочка:** открыть конкретное назначение/фильтр → увидеть причину и
   происхождение → выполнить только существующее разрешённое действие.
   Presentation packet не вводит mutation.
4. **Доказательства:** перейти из очереди в правильный journal context и найти
   существующий export. Содержимое/снимок/права экспорта остаются прежними.
5. **Возврат:** deep link/reload/back сохраняют объект/поддерживаемые URL-фильтры;
   не теряются правки, а session expiry не превращается в пустой успешный список.

Матрица: populated/loading/confirmed empty/filtered empty/error/partial
unavailable; methodologist/admin/student/superadmin; смена active role;
foreign tenant/resource negative через канонический isolated test contour.
Изменение frontend guard не подменяет проверку backend/RLS.

Browser: 390/768/1270/1440; RU/KK/EN; light/dark, reduced motion; клавиатура,
видимый и не перекрытый focus, scale/zoom, длинные строки, без page overflow.
axe по затронутому пути + ручной assistive-tech smoke, без заявления полного
WCAG conformance. Проверить возврат фокуса и отсутствие keyboard traps.

Focused behavioral tests по A1–A5; role/query/dirty-state regression; web
typecheck/lint/production build один раз после freeze. Full regression по риску
перед app release; evidence в существующем TEST_RUN_LEDGER.md.

## Прототип и его пределы

`prototypes/methodologist-narrow-a-20261105/index.html` — автономный локальный
RU HTML с synthetic данными. Демонстрирует queue/filter/detail, состояния данных,
контекстное согласование и readonly C. Он не обращается к API, не проверяет
auth/RLS, не сохраняет бизнес-решения и не доказывает доступность live features.
`verify.mjs` проверяет standalone ограничения и JS; browser results записываются
отдельно. Прототип не заменяет существующие app routes и не включается в build.

## Зависимости, решения и выпуск

| Gate | Что требуется | Если не выполнено |
|---|---|---|
| Data/route map | A0 exact contract и правильные IDs/query | Отложить соответствующий link, дать честный fallback; не придумывать API |
| Provenance | C0 snapshot/revision доступность | В C показать missing/unknown; отдельный API scope |
| Current baseline | Зафиксировать SHA кандидата и целевую среду | Не считать ветку аудита текущим production |
| User validation | Одинаковые synthetic tasks до/после, новичок + опытный методолог | Эффект остаётся гипотезой |
| App implementation | Локальный Narrow A реализован; владелец разрешил independent review и исправления | Незакрытые проверки отражать в review/ledger; не считать prototype app evidence |
| Release | Exact candidate checks, authority и runtime readback | Никакого push/deploy из этого пакета |

Срок определяется после A0; прежние оценки недель не обязательство. Первый
пилот 5–8 человек — поиск проблем, не доказательство ≥90%. Фиксировать время,
успех без подсказки, ошибки и полноту проверки источников; не ускорять процесс
пропуском проверки. Новую телеметрию не добавлять. Откат presentation-only
дельты не должен затрагивать историю/данные. C mutations требуют отдельного rollback.

## Ownership и review

Root: audit, этот план, интеграция, ledger и итоговый scope review.
Prototype writer: только `index.html`/`verify.mjs`. Два независимых коллеги:
критик — scope/evidence/semantics; дизайнер — задачи/иерархия/responsive/a11y.
Они не принимают собственную реализацию. Findings и закрытие — в ledger;
пользовательские замеры не подменяются агентским review.
