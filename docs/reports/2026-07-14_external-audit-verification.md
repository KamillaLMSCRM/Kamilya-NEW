# Проверка внешнего технического аудита Kamilya LMS

Дата проверки: 14 июля 2026 г.  
Проверенный checkout: `master`, commit `8c811c1`  
Репозиторий: `KamillaLMSCRM/Kamilya-NEW`

## Итог

Внешний отчёт полезен как инвентаризация, но его итоговое заключение **`GO WITH CONDITIONS` и оценки 4–5/5 завышены**. Отчёт правильно обнаружил два существенных расхождения, однако часть функций названа `IMPLEMENTED` без полноценного доказательства UI → API → БД → worker → storage, а production readiness SCORM/RLS объявлена без достаточного E2E-подтверждения.

Текущий независимый вердикт: **`NO-GO` для полностью самостоятельного первого tenant-flow; `GO WITH CONDITIONS` только для контролируемого пилота с ручным оператором и ограниченным числом функций.**

## Подтверждённые findings

### FIND-01: дата окончания trial не является enforcement boundary

**Статус:** подтверждено, P1 коммерческий и продуктовый риск.

`Tenant.trial_ends_at` существует и заполняется при регистрации, но `get_current_user` в `apps/api/app/core/auth.py` не загружает tenant и не проверяет окончание trial. `trial_limits.py` проверяет количественные лимиты, но не дату.

Важно уточнить продуктовую политику перед исправлением:

- просроченный trial не обязательно должен блокировать сам login;
- login должен позволять попасть на экран upgrade/contact support;
- операции создания/генерации/назначения должны получать явный `trial_expired`;
- superadmin и разрешённый manual override не должны блокироваться;
- платный tenant с просроченным `trial_ends_at`, но активным `paid_until`, не должен считаться истёкшим.

Минимальный fix должен быть общей backend dependency/service-проверкой, а не только frontend guard. Нужны тесты для active trial, expired trial, paid_until, suspended tenant, superadmin и impersonation.

### FIND-02: AI endpoint запускает pipeline внутри web-процесса

**Статус:** подтверждено, P1 надёжности.

`apps/api/app/modules/ai/router.py` принимает `BackgroundTasks`, создаёт внутреннюю `_safe_pipeline` и вызывает `background_tasks.add_task(_safe_pipeline)`. Это не Celery и не Redis-backed durable queue. При restart/scale-to-zero Render job может остаться в `pending/running` или потеряться.

В проекте есть `apps/api/app/modules/ai/tasks.py` с `generate_course_task`, но endpoint его не вызывает. Более того, task использует `UUID(...)`, хотя `UUID` не импортирован в этом файле. Следовательно, одного переноса dispatch на Celery недостаточно: сначала нужно исправить task и проверить worker на реальном Redis.

Минимальная последовательность:

1. сериализовать все параметры job в БД;
2. отправлять `generate_course_task.delay(...)` после commit;
3. сделать task идемпотентным по `job_id`;
4. добавить retry/backoff и финальный статус `failed`;
5. добавить watchdog для зависших `pending/running`;
6. проверить worker, Redis, tenant context и async DB engine;
7. оставить fallback только как явно контролируемый development mode.

## Подтверждённые расхождения документации

| Документ | Проблема | Вывод |
|---|---|---|
| `PROJECT.md` | прямо говорит, что trial enforcement не завершён | актуально по времени trial, но количественные limits уже частично реализованы; формулировку нужно разделить |
| `AGENTS.md` | содержит запрет «Использовать SCORM (это v1.1)» | историческое правило конфликтует с текущим SCORM 1.2 кодом; обновлять после согласования product scope |
| `PROJECT.md`, `docs/PROJECT-CONTEXT.md` | описывают Celery worker, но не уточняют, что AI endpoint использует `BackgroundTasks` | документация скрывает критичный operational limitation |

## Что во внешнем отчёте завышено или не доказано

### 1. SCORM нельзя считать полностью production-ready

В коде действительно есть parser, reject SCORM 2004, asset security и commit route. Это подтверждает реализацию backend-составляющих SCORM 1.2.

Но unit/security tests не доказывают:

- работу iframe в браузере;
- реальные iSpring/Articulate exports;
- корректность полного CMI lifecycle;
- storage в production;
- повторное открытие и повторный commit;
- сертификат и training log через UI;
- отказ SCORM 2004 в production deployment.

Корректный статус: `PARTIAL` или `IMPLEMENTED — backend verified, production E2E pending`, но не безусловный `IMPLEMENTED` и не оценка `5/5`.

### 2. Tenant isolation нельзя объявлять полностью подтверждённой только по `set_config`

`get_current_user` действительно выставляет tenant context, но наличие вызова `set_current_tenant` само по себе не доказывает:

- что все tenant tables имеют FORCE RLS;
- что все policies используют безопасный context;
- что все endpoints проверяют связанные `course_id/user_id/position_id`;
- что superadmin/impersonation не обходят ограничения ошибочно;
- что есть cross-tenant integration tests для всех доменов.

Финальный статус должен быть разбит по таблицам и endpoint-группам, с результатами SQL/policy audit и тестами.

### 3. Все 10 флоу не доказаны end-to-end

Внешний отчёт часто называет функцию `IMPLEMENTED` на основании найденного router/page. Для production-аудита этого недостаточно. Особенно требуют фактического smoke/E2E:

- tenant registration → email/Telegram login → F5 → правильный dashboard;
- document upload → indexing → AI job → course/test;
- staff import с несколькими листами и дубликатами;
- cohort/rule assignment и отсутствие duplicate enrollments;
- learner completion → certificate PDF → training log;
- kiosk auto-logout и очистка состояния;
- trial expiration и concurrency на limits.

### 4. `Kiosk auto-logout` нельзя понижать до P3

Если kiosk выдаёт access token и следующий сотрудник может получить предыдущую сессию или данные, это privacy/security blocker для kiosk-сценария. Статус зависит от browser QA. До проверки корректнее держать его как `P1 conditional`, а не `P3`.

### 5. Оценки 4.5–5.0 не соответствуют найденным рискам

При отсутствии time-based trial enforcement, durable AI queue, production SCORM E2E и полной kiosk QA оценки должны быть ниже:

- implementation integrity: максимум 3/5;
- AI/document pipeline: максимум 2–3/5;
- SCORM readiness: максимум 3/5 до staging E2E;
- trial/billing enforcement: максимум 2/5;
- operational readiness: максимум 3/5, пока AI job durability не доказана;
- test confidence: максимум 2–3/5 при отсутствии полного integration/browser набора.

## Приоритетный план

### P0 до самостоятельного tenant-flow

1. Исправить и покрыть time-based trial policy.
2. Сделать AI generation durable через Celery/Redis или честно ограничить production claim ручным оператором.
3. Проверить production auth/session после F5 и правильный role/dashboard routing.
4. Провести cross-tenant tests для критичных learning/admin/superadmin endpoints.

### P1 для контролируемого пилота

1. Реальный staging E2E SCORM 1.2.
2. Kiosk privacy/auto-logout QA.
3. Staff import с multi-sheet preview, mapping, row errors и deduplication.
4. Cohort/rule assignment: worker, idempotency, duplicate protection.
5. Ручной superadmin onboarding и явные audit logs.

### P2 после первого пилота

1. Billing UI и upgrade flow.
2. Lead management.
3. Production observability и alerts по зависшим AI jobs.
4. Удаление/переписывание исторических инструкций в `AGENTS.md` и старых TZ.

## Что принять от внешнего агента

- подтверждение `trial_ends_at` gap;
- подтверждение in-process AI pipeline;
- необходимость синхронизации документации;
- наличие backend SCORM security hardening;
- наличие количественных trial limits.

## Что не принимать без дополнительного доказательства

- `GO` для самостоятельного production tenant-flow;
- `SCORM 1.2 = 5/5`;
- `Tenant Isolation = 5/5` по одному факту `set_config`;
- `Learning Delivery = 5/5` без browser/E2E completion;
- `Kiosk = IMPLEMENTED` без privacy QA;
- `AI = IMPLEMENTED` как durable production job;
- утверждение, что Celery path уже рабочий.

## Следующее действие

Не переносить внешний отчёт в product truth без корректировок. Сначала закрыть два подтверждённых P1: time-based trial policy и durable AI dispatch, затем повторить staging/E2E-аудит SCORM, kiosk и tenant-flow.

