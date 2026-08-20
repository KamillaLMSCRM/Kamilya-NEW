# Production-приёмка нового tenant по всем рабочим поверхностям

**Дата:** 2026-08-20

**Контур:** `app.kml.kz` + `api.kml.kz`, KZ production

**Тип данных:** только синтетические данные с явным test-prefix
**Результат:** одна сквозная карта `PASS | FAIL | BLOCKED | NOT_APPLICABLE` с наблюдаемой задержкой каждого шага

## 1. Цель и границы

Создать отдельный удаляемый production tenant и доказательно проверить, что новый клиент может пройти путь:

```text
superadmin -> tenant/admin -> methodologist -> структура/сотрудники
-> документы -> индексация -> AI-курс/тест -> review/publish
-> программа/группа/правило/назначение -> employee access
-> курс/тест -> результат/сертификат/evidence -> журнал/экспорт
```

Проверяются отдельно все видимые пункты меню `admin`, `methodologist` и `student`, а также обязательные контекстные и public-маршруты. Проверка не использует реальные данные ломбарда, не изменяет tenant `too-lombard-sandyk` и не выдаёт локальные тесты за production evidence.

Не входят без отдельного product gate: юридическая аттестация/допуск, SCORM 2004, автоматический billing, массовая нагрузка и реальная отправка кандидатам/сотрудникам клиента.

## 2. Стоп-условия до создания tenant

1. Зафиксированы deployed revisions frontend, API и workers.
2. `alembic current == alembic heads`; runtime role `lms_app` видит только свой tenant context.
3. API, worker queues, Valkey, storage, converter, backup freshness и свободный диск находятся в рабочем состоянии.
4. Production содержит требуемый adaptive staff-import contract и миграции структуры; фактический head сверяется с текущим repository head перед каждым прогоном. В завершённом прогоне оба значения равны `0119`.
5. Для выпуска используется только точный проверенный commit; dirty worktree не разворачивается.

Если любой пункт не выполнен, соответствующая строка матрицы получает `BLOCKED`, после чего сначала закрывается release gate.

## 3. Тестовые данные и безопасность

- Tenant: уникальные название/slug с префиксом `codex-e2e-20260820-` и `is_demo=true`, если production contract это допускает.
- Пользователи: отдельные синтетические admin, methodologist и два student; никаких данных Sandyk.
- Email-доставка используется только через заранее подтверждённый тестовый mailbox. Если он не подтверждён, проверяется персональная ссылка/PIN без внешней отправки, а email delivery отмечается `BLOCKED`, не имитируется.
- Документы: небольшой DOCX или PDF с уникальным test-marker; XLS/XLSX/CSV штатки генерируются без персональных данных.
- AI: один короткий grounded-курс с ограниченным объёмом; не более одной активной генерации, без нагрузочного/платного массового прогона.
- Каждая созданная сущность записывается в cleanup manifest. Удаление tenant выполняется только штатным guarded synthetic cleanup либо точечной одобренной процедурой; до удаления собирается residual audit.
- Секреты, OTP, PIN, tokens и пароли не попадают в план, логи, Git или итоговый отчёт.

## 4. Метрика и единая матрица

Для каждого теста фиксируются:

| Поле | Содержание |
|---|---|
| ID | стабильный идентификатор теста |
| Surface | меню/route/API |
| Role | active working role |
| Preconditions | точное исходное состояние |
| Action | одно наблюдаемое действие |
| Expected | продуктовый результат |
| Actual | HTTP/UI/DB/worker evidence без секретов/PII |
| Client latency | время ответа HTTP/UI |
| Async latency | upload->ready, queue->draft, invite->delivery и т.п. |
| Cleanup | созданные ID и способ удаления |
| Result | `PASS`, `FAIL`, `BLOCKED`, `NOT_APPLICABLE` |
| Defect | ссылка на исправление и повторный прогон |

Для синхронных действий измеряется wall time. Для polling-flow отдельно сохраняются `accepted_at`, `started_at`, `completed_at`, queue wait и processing time, если API их предоставляет. Один прогон не называется p95; это `observed latency`. p50/p95 рассчитываются только для безопасной серии из минимум 5 одинаковых неплатных read-only/коротких операций.

### 4.1. Текущий production snapshot

На 2026-08-20 используется disposable tenant `e75b516a-d732-483c-a1cb-3d5445ecc570`; tenant Ломбард Сандык не изменялся. API и три worker работают на exact SHA/image `8904b62`, Docling — на независимом образе `f314aa3` (`2.106.0`, `healthy`), PostgreSQL — `0119 (head)`, внешний `/health` отвечает `200`. Все три Celery worker отвечают `pong`; Valkey healthy. Disposable tenant временно переведён в `pro/active` только для ограниченной AI-приёмки и пока сохранён для повторных проверок.

| ID | Проверенная поверхность | Наблюдаемый результат | Latency / async | Result | Примечание |
|---|---|---|---|---|---|
| REL-02 | API/proxy health | `200`, API и три worker на `8904b62` | recreate/start около 16 s | PASS | Exact Git archive; dirty worktree не разворачивался |
| REL-03 | workers/Docling | AI/documents/ops: 3/3 `pong`; Docling `f314aa3` healthy | worker ping 12.1 s | PASS | Celery root-warning остаётся hardening backlog, не функциональный отказ |
| REL-04 | PostgreSQL/Alembic | `0119 (head)` | migration + current 6.0 s | PASS | `0119` восстанавливает token-scoped public kiosk lookup под FORCE RLS |
| TEN-01 | synthetic tenant | tenant создан и изолирован | — | PASS | Cleanup отложен до конца всей матрицы |
| TEN-02/03 | admin/methodologist login | обе реальные tenant-учётные записи аутентифицируются | < 1 s | PASS | Impersonation не используется для immutable evidence |
| MET-05 | DOCX upload/catalog/download/duplicate | индекс `ready`, 3/3 chunks, байты и SHA совпадают, duplicate `409` | catalog 76 ms; download 57 ms; duplicate 64 ms | PASS | Docling 2.106.0 подтверждён реальным DOCX |
| MET-02 | AI generation runtime | job `808117d3-9ce6-4dca-919a-3a33cf99c97f`: draft `d4cbd14a-799f-42f0-8b3d-27157308451d`, 1 module, 3 lessons, 15 questions | 185.8 s | PASS | Production provider `cyankiwi/Qwen3.6-35B-A3B-AWQ-4bit` |
| MET-02-Q | grounded quality | 15/15 вопросов привязаны к server-owned evidence; meta/off-source count 0; ответы очищены от Markdown и не обрываются на `:` | audit после job | PASS | Evidence-bank ID, structured JSON schema, server-owned correct answer/explanation |
| MET-03/04 | review/publish/quizzes/release | publish до review `409`; после review `200`; release создан | review 43 ms; publish 62 ms | PASS | 4 quiz, по 5 вопросов, pass 80, attempts 2 |
| MET-06 | learning path create/publish/assign | real methodologist: assign cohort `201`, 2 assignments, enrollments materialized | assign 90 ms; list 40 ms | PASS | Impersonation writer корректно отклонён tenant trigger |
| MET-06-IDEM | repeat completed path assignment | before 2 / completed 1; repeat: added 0, skipped 2; after 2 / completed 1 | 116/66/53 ms | PASS | Completed state/enrollment сохранены, дублей нет |
| MET-07 | cohort create/update/membership | 2 synthetic members; cohort без path assignment не создал enrollment | — | PASS | Cohort подтверждён как reusable audience, не назначение |
| MET-08 | initial adaptive staff import | 2 branches, 3 departments, 5 positions/staff | readback 34–43 ms | PASS | Вложенность branch → department сохранена |
| MET-09 | incremental import | добавлены ещё 5 branches; итого 7/8/10/10, старые IDs сохранены | readback 35–61 ms | PASS | Дублей нет |
| MET-10 | legacy XLS import | итог 7 branches, 8 departments, 14 positions/staff | readback 33–58 ms | PASS | Старый секционный формат поддержан |
| MET-16/STU-06 | personal link/PIN | issue `200`, wrong PIN `401`, exchange `200`, exact enrollment | 403/73/82 ms | PASS | Окно 30 минут; raw secret не сохранён в evidence |
| STU-01/02 | dashboard/course/structure | только точный course/enrollment, 2 modules/4 lessons | 38–59 ms | PASS | Cross-enrollment leakage не обнаружен |
| STU-03 | 4 quiz attempts | все завершены, итоговый best score 100 | — | PASS | 4 knowledge-check evidence events |
| STU-04 | certificate | own detail/download/public verify `200`, public valid | 38–87 ms | PASS | PDF 45,016 bytes |
| STU-05 | learner learning path | published path виден; 1/1 required completed, progress 100, current course null | 106 ms | PASS | Completed learner state отображается корректно |
| STU-08 | learner evidence PDF | own detail/export `200` | — | PASS | PDF 46,713 bytes, internal answer/audit data исключены |
| MET-17 | training log/evidence/signed scan | completed, progress 100, best 100, scan ledger `received` | training log 66 ms | PASS | Реальный methodologist; full export до step-up ожидаемо `409` |
| SEC-POST-01 | mutation after completion | progress/quiz/complete и AI-chat отклонены `409` | — | PASS | `assignment_enrollment_not_active` до LLM/write |
| SEC-POST-02 | impersonated immutable write | signed-scan POST отклонён `403` | — | PASS | `impersonation_cannot_append_evidence` |
| MET-19-SURVEY | survey exact enrollment | create/list/submit `201`, submitted readback true, duplicate `409` | < 1 s | PASS | Response привязан к точному enrollment; legacy NULL не учитывается assignment bearer |
| ADM-01 | admin dashboard/stats/trial usage | все три route `200`; nullable kiosk email безопасно нормализуется | 151/52/40 ms | PASS | Исправление dashboard уже в production |
| ADM-02 | team lifecycle/RBAC | list `200`; synthetic methodologist create `201`, detail `200`, deactivate `204`, soft-deleted detail `200`; admin `include_students=true` ожидаемо `403` | 37–102 ms | PASS | Синтетическая учётная запись деактивирована |
| ADM-03 | kiosk lifecycle | create `201`; public valid; identify `200` с 1 курсом и коротким JWT; success log 1; delete `204`; затем invalid `kiosk_not_found` | 31–65 ms | PASS | Найден и исправлен FORCE-RLS defect, commit `8904b62`; raw token/JWT не сохранялись |
| ADM-05 | integrations read-only | `200`, пусто, секреты не раскрываются | около 122 ms | PASS | Внешняя отправка не выполнялась |
| ADM-06 | certificate settings/preview | settings `200`; неперсистентный PDF preview `200`, 45,343 bytes | 46/158 ms | PASS | Production-настройки не изменялись |
| ADM-07 | methodologist negative RBAC | dashboard/kiosk/integrations/certificate settings отклонены `403` | — | PASS | Admin-only граница подтверждена |
| ADM-EXPORT | users/courses/quiz-results CSV | все три `200`; 2,456 / 1,668 / 555 bytes | 36–45 ms | PASS | Файлы не передавались наружу |
| MET-13 | процедуры подтверждения | маршруты и guards присутствуют; реальная юридическая аттестация не создавалась | — | NOT_APPLICABLE | Отдельный product/legal gate по плану приёмки |
| MET-14 | сроки хранения результатов | retention timer enabled/active; destructive purge не запускался | — | PASS | Безопасный контроль без удаления production evidence |
| MET-15 | оценка кандидатов | create/activate, protected link/PIN, consent, attempt, deterministic result, manager result/CSV, cleanup | production E2E | PASS | Кандидат изолирован от employee/staff объектов |
| MET-02-QWEN | Qwen3.8-27B-NVFP4 direct pool | руководство применено к контракту, но VM126 и workstation не достигают `10.66.66.30:8002`; gateway не принимает model ID | — | BLOCKED | Не включён; production продолжает проверенный Qwen3.6 route |

Итог обязательного pilot-flow: `PASS`. Остаточные ограничения не маскируются: Qwen3.8 direct route пока `BLOCKED`; реальная юридическая аттестация `NOT_APPLICABLE`; массовая нагрузка и внешняя email-доставка не являлись частью этого synthetic production run. Tenant оставлен только для повторной приёмки, поэтому финальный residual cleanup ещё не выполнен. Это не меняет данные и настройки Ломбард Сандык.

### 4.2. Карта видимых пунктов меню

Статус ниже относится к рабочему backend-flow пункта меню на disposable production tenant. Один лишь факт наличия страницы в frontend не считался доказательством.

| Роль | Пункт меню / route | Проверенный рабочий результат | Итог |
|---|---|---|---|
| Superadmin | Тенанты `/admin/super/tenants` | tenant создан штатным API, admin учётная запись активна, tenant изолирован | PASS |
| Admin | Панель `/admin` | dashboard, stats, trial usage | PASS |
| Admin | Команда `/admin/team` | list/create/detail/deactivate и role boundary | PASS |
| Admin | Киоски `/admin/kiosks` | create/public identify/JWT/course/log/delete/invalid | PASS |
| Admin | Настройки `/settings` | навигационный hub; все четыре дочерние admin-поверхности доступны | PASS |
| Admin | Интеграции `/admin/settings/integrations` | безопасное чтение конфигурации, пустое состояние, без раскрытия secret | PASS |
| Admin | Шаблон сертификата `/admin/certificates/settings` | settings read + неперсистентный PDF preview | PASS |
| Методолог | Панель `/dashboard` | данные tenant/course доступны; admin route отклонён | PASS |
| Методолог | AI-генерация `/ai/generate` | grounded draft + 15 вопросов, meta/off-source 0 | PASS |
| Методолог | Курсы `/courses` | draft, editor/content, review guard, publish, immutable release | PASS |
| Методолог | Конструктор тестов `/quizzes` | 4 quiz, вопросы/порог/попытки, learner attempts и best score | PASS |
| Методолог | Документы `/documents` | DOCX upload, Docling index, catalog/download/hash, duplicate `409`, reindex | PASS |
| Методолог | Программы `/learning-paths` | create/publish/cohort assign/repeat idempotency/learner progress | PASS |
| Методолог | Группы `/cohorts` | create/update/membership; группа сама не создаёт назначение | PASS |
| Методолог | Сотрудники и структура `/staff?tab=structure` | initial/incremental/legacy XLS; 7 филиалов, 8 отделов, 14 должностей/сотрудников, без дублей | PASS |
| Методолог | Процедуры подтверждения `/training-procedures` | фактическая юридическая аттестация исключена из synthetic run | NOT_APPLICABLE |
| Методолог | Сроки хранения `/training-retention` | timer enabled/active; destructive purge не запускался | PASS |
| Методолог | Оценка кандидатов `/candidate-assessments` | campaign/link/PIN/consent/attempt/result/CSV/cleanup | PASS |
| Методолог | Назначения и доступ `/assignments` | published release, personal link/PIN, 30-minute policy, exact enrollment | PASS |
| Методолог | Журнал обучения `/training-log` | status/score/progress/evidence/export/signed scan | PASS |
| Сотрудник | Панель `/student` | exact enrollment, next/current state, manager routes закрыты | PASS |
| Сотрудник | Мои курсы `/my-courses` | course/lessons/progress/completion, post-completion mutation guards | PASS |
| Сотрудник | Мои тесты `/my-quizzes` | полный attempt flow, score/pass/retry limits | PASS |
| Сотрудник | Сертификаты `/certificates` | own detail/download + public verification | PASS |
| Public | Персональная ссылка `/access/{token}` | wrong PIN `401`, correct exchange `200`, timer/exact enrollment | PASS |
| Public | Киоск `/kiosk/{token}` | public token bootstrap под FORCE RLS, employee identify и short-lived JWT | PASS |

Скрытые маршруты (`training-rules`, `invitations`, `competencies`) проверялись только как части соответствующих сквозных сценариев и намеренно не рекламируются как отдельные пункты sidebar.

## 5. Инвентарь проверок

### A. Release и bootstrap

- `REL-01` Vercel alias/revision/build health.
- `REL-02` API revision/health/ready и proxy path.
- `REL-03` три worker/queue registration и image parity.
- `REL-04` PostgreSQL head, runtime grants, RLS/FORCE RLS.
- `REL-05` storage read/write/delete, converter, backup freshness/disk.
- `TEN-01` создать synthetic tenant.
- `TEN-02` первый admin активен и попадает на `/admin`.
- `TEN-03` admin создаёт/активирует methodologist; active role не смешивает полномочия.

### B. Admin sidebar

- `ADM-01` `/admin`: tenant summary/onboarding status.
- `ADM-02` `/admin/team`: создать/деактивировать системного пользователя, проверить роли.
- `ADM-03` `/admin/kiosks`: создать kiosk config/token, проверить guarded state; device/privacy QA пометить отдельно.
- `ADM-04` `/settings`: чтение/безопасное обновление tenant settings.
- `ADM-05` `/admin/settings/integrations`: Telegram/provider settings без вывода secret; внешний delivery без подтверждённого канала не имитировать.
- `ADM-06` `/admin/certificates/settings`: настройка и preview шаблона сертификата.
- `ADM-07` отрицательные RBAC: admin не управляет курсами, штаткой и назначениями.

### C. Methodologist sidebar и контекстные маршруты

- `MET-01` `/dashboard`.
- `MET-02` `/ai/generate`.
- `MET-03` `/courses`, создание draft, editor, review, publish, immutable release.
- `MET-04` `/quizzes`, создание/редактирование теста и проверка привязки к lesson.
- `MET-05` `/documents`: upload, статус, download, reindex/recovery, duplicate SHA, тот же документ с другим именем, повторное использование источника для нового курса.
- `MET-06` `/learning-paths`: draft, шаги, publish, audience assignment, linear/open behavior.
- `MET-07` `/cohorts`: создать группу, изменить состав, подтвердить отсутствие самостоятельного course assignment.
- `MET-08` `/staff?tab=structure`: импорт, preview, mapping, approval, commit, tree/search/collapse.
- `MET-09` повторный incremental import: существующие 2 филиала + 5 новых, вложенные отделы, новые/существующие должности, совпадения и конфликты; никаких дублей.
- `MET-10` legacy XLS/XLSX/CSV: секционные строки филиалов, отдельные/единое ФИО, произвольные заголовки и листы; методолог подтверждает распознанную структуру, а не вручную переписывает файл.
- `MET-11` ручное добавление сотрудника и канонические department/position IDs.
- `MET-12` карточка должности: профиль, ДИ, компетенции, обязательное обучение, версии.
- `MET-13` `/training-procedures`: draft/validation/activation guards; не создавать фактическую аттестацию.
- `MET-14` `/training-retention`: policy/dry-run; destructive purge не запускать до cleanup gate.
- `MET-15` `/candidate-assessments`: create/activate, link/PIN, attempt, result/CSV, residual cleanup.
- `MET-16` `/assignments`: опубликованный курс, user/cohort/department/position, email и personal-link policy, идемпотентность, revoke/extend.
- `MET-17` `/training-log`: filters, statuses, evidence, CSV/PDF/ZIP и signed-scan control.
- `MET-18` контекстные `/training-rules`, `/positions/{id}`, `/invitations`; проверить, что скрытие из sidebar не делает flow недоступным.
- `MET-19` скрытые unfinished `/announcements`, `/surveys`, `/competencies` не рекламируются как завершённые; доступ/отсутствие маркируется согласно каноническому contract.
- `MET-20` отрицательные RBAC и cross-tenant access для всех mutation families.

### D. Сквозные content и staff сценарии

1. Загрузить уникальный небольшой документ и дождаться `ready`.
2. Сгенерировать grounded draft, проверить provenance, структуру тестов и отсутствие fallback на общие знания.
3. Проверить/review, опубликовать, получить immutable release.
4. Импортировать структуру из нестандартного файла; утвердить предложенное сопоставление.
5. Повторно импортировать расширенный файл; сохранить существующие IDs и добавить только новые units/users/positions.
6. Создать cohort и программу; назначить опубликованный курс двум разным способом и проверить идемпотентную материализацию.
7. Выдать одному student email activation (если тестовый mailbox подтверждён), второму — personal link/PIN с ограниченным окном.

### E. Student и public surfaces

- `STU-01` `/student` dashboard.
- `STU-02` `/my-courses`: доступ только к назначениям текущего enrollment/release.
- `STU-03` `/my-quizzes`: полный набор ответов, score/pass, повтор/лимит попыток.
- `STU-04` `/certificates`: выпуск, download, public verify.
- `STU-05` `/learning-paths`: linear/open unlock/progress.
- `STU-06` `/access/{token}`: PIN, таймер, expiry/revoke и точная enrollment binding.
- `STU-07` invitation link + invitation-bound OTP отдельно от login OTP.
- `STU-08` собственный evidence PDF без чужих/служебных данных.
- `STU-09` learner не видит manager/content/staff routes.

### F. Нефункциональные и отрицательные проверки

- desktop и mobile smoke ключевых страниц; console/network errors.
- пустые/loading/error/retry состояния upload и AI.
- duplicate/double-click/idempotency.
- unknown/oversize/invalid file.
- tenant A не читает и не изменяет tenant B под runtime role.
- очередь/worker failure моделируется только безопасным contract test, без остановки production services.
- фактические задержки сравниваются с UI ETA/timeout, но не объявляются SLA.

## 6. Выпуск исправлений

На каждый дефект:

1. воспроизведение и строка `FAIL`;
2. focused regression test;
3. минимальное исправление без затрагивания Sandyk;
4. локальные backend/frontend gates и DB integration на мигрированной test DB;
5. чистый exact commit и CI;
6. staging/KZ release с проверкой DB head, API/worker/frontend parity;
7. повтор только упавшей строки и затронутого сквозного пути;
8. финальный production readback.

## 7. Cleanup и критерий завершения

Перед удалением проверяются итоговые счётчики tenant: users, units, positions, documents/storage objects, jobs, courses/releases, quizzes/attempts, enrollments, invitations/access credentials, certificates, evidence/signed scans, candidate objects, programs/cohorts/rules и audit.

После удаления/guarded cleanup повторно подтверждаются:

- tenant недоступен через API и runtime RLS;
- storage test-prefix пуст;
- нет pending/running jobs и outbox records теста;
- production Sandyk counts и контрольные маршруты не изменились;
- monitoring/backup/worker health зелёные.

Итог `GO` возможен только если все обязательные строки имеют `PASS`, все `BLOCKED` имеют явно принятую внешнюю причину, `FAIL` отсутствуют, cleanup/residual audit пройдены, а deployed revisions записаны в каноническую документацию.
