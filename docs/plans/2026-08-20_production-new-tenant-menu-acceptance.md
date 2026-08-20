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
4. Production содержит требуемый adaptive staff-import contract. На 2026-08-20 каноническая документация фиксирует production DB head `0111`, а рабочее дерево содержит незавершённые `0112–0115`; до сверки нельзя считать новую загрузку структуры доступной в production.
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

На 2026-08-20 используется disposable tenant `e75b516a-d732-483c-a1cb-3d5445ecc570`; tenant Ломбард Сандык не изменялся. API и три worker работают на exact SHA `4f2816e`, Docling — на независимом образе `f314aa3`, PostgreSQL — `0118 (head)`, внешний `/health` отвечает `200`.

| ID | Проверенная поверхность | Наблюдаемый результат | Latency / async | Result | Примечание |
|---|---|---|---|---|---|
| REL-02 | API/proxy health | `200`, API и три worker на `4f2816e` | health < 15 s timeout | PASS | После controlled recreate |
| REL-03 | workers/Docling | AI/documents/ops `ready`; Docling `healthy` | startup около 16 s | PASS | Celery пока запускается под root — отдельный hardening backlog |
| REL-04 | PostgreSQL/Alembic | `0118 (head)` | migration < 5 s после исправления | PASS | Первый прогон поймал multi-statement asyncpg defect; исправлен commit `4f2816e` |
| TEN-01 | synthetic tenant | tenant создан и изолирован | — | PASS | Cleanup отложен до конца всей матрицы |
| TEN-02/03 | admin/methodologist login | обе реальные tenant-учётные записи аутентифицируются | < 1 s | PASS | Impersonation не используется для immutable evidence |
| MET-05 | DOCX upload/catalog/download/duplicate | индекс `ready`, 3/3 chunks, байты и SHA совпадают, duplicate `409` | catalog 76 ms; download 57 ms; duplicate 64 ms | PASS | Docling 2.106.0 подтверждён реальным DOCX |
| MET-02 | AI generation runtime | draft создан: 2 modules, 4 lessons, 4 quizzes | 312.5 s | PASS | Функциональная доставка завершилась |
| MET-02-Q | grounded quality | первые два quiz содержат вопросы о JSON/HTTP вместо исходного регламента | — | FAIL | Обязательный дефект качества до итогового GO |
| MET-03/04 | review/publish/quizzes/release | publish до review `409`; после review `200`; release создан | review 43 ms; publish 62 ms | PASS | 4 quiz, по 5 вопросов, pass 80, attempts 2 |
| MET-06 | learning path create/publish/assign | real methodologist: assign cohort `201`, 2 assignments, enrollments materialized | assign 90 ms; list 40 ms | PASS | Impersonation writer корректно отклонён tenant trigger |
| MET-06-IDEM | repeat completed path assignment | completed assignment был повторно посчитан `added` и реактивирован | repeat 49 ms | FAIL | Не создан второй enrollment, но completed state нельзя сбрасывать; TDD fix начат |
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
| ADM-01-A | admin stats/trial usage | оба route `200` | 110–130 ms | PASS | Tenant summary читается |
| ADM-01-B | admin dashboard | production `500`: recent kiosk/student содержит допустимый `email=NULL`, response schema требовала `str` | около 200 ms | FAIL | TDD-исправление локально готово; production повтор после release |
| ADM-02-R | team read/RBAC | team `200`; `include_students=true` ожидаемо `403` | около 118 ms | PASS | Mutation lifecycle отложен из-за login rate limit; сущности не создавались |
| ADM-03-R | kiosk read surfaces | list/scopes/access logs `200`, начальное состояние пустое | 106–142 ms | PASS | Create/public identify/delete ещё не выполнялись из-за login rate limit |
| ADM-05 | integrations read-only | `200`, пусто, секреты не раскрываются | около 122 ms | PASS | Внешняя отправка не выполнялась |
| ADM-06-R | certificate settings read | `200` | около 118 ms | PASS | Preview/mutation ещё не выполнялись |
| ADM-07 | methodologist negative RBAC | dashboard/kiosk/integrations/certificate settings отклонены `403` | — | PASS | Admin-only граница подтверждена |
| ADM-EXPORT | users/courses/quiz-results CSV | `200`; 2,158 / 727 / 555 bytes | — | PASS | Файлы не передавались наружу |
| MET-06-IDEM-FIX | completed path repeat contract | локальный TDD: completed сохраняется и считается skipped; cancelled можно реактивировать | 11 focused tests PASS | BLOCKED | Ожидает commit/release и production repeat |
| MET-02-Q-FIX | assessment grounding hardening | локально: untrusted-source boundary, exact supporting quote per question, quoted correct answer, meta-term rejection, safe retry/title/logging; full unit suite 261 PASS | — | BLOCKED | Ожидает final independent review, release и новую production generation |
| MET-02-QWEN | Qwen3.8-27B-NVFP4 direct quality probe | первый request получил engine HTTP 500, затем endpoint стал connection-refused | — | BLOCKED | Не переключать production failover до восстановления `/health`, `/models` и grounded probe |

Все строки без фактического production evidence остаются незакрытыми, даже если code-contract или unit test существует.

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
