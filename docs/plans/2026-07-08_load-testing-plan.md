# План нагрузочного тестирования Kamilya LMS

Дата: 2026-07-08

Цель документа: зафиксировать практичный способ проверить Kamilya LMS под нагрузкой первого крупного тенанта, не смешивая обычную пользовательскую нагрузку с тяжелыми AI-операциями.

## 1. Что именно проверяем

Нагрузку нельзя описывать только фразой "500 пользователей онлайн". Для Kamilya LMS это разные классы операций:

1. Обучающийся читает курсы, открывает уроки, сохраняет прогресс, проходит тесты, завершает курс и получает сертификат.
2. Методолог работает с курсами, тестами, документами, AI-генерацией и публикацией.
3. Администратор тенанта управляет пользователями системы, штаткой, обучающимися и назначениями.
4. Суперадмин управляет tenant-аккаунтами, тарифами, лимитами и провайдерами AI.

Для запуска первого тенанта целевая модель должна быть такой:

- 500 активных пользователей могут проходить обучение без деградации.
- 10-30 администраторов и методологов могут одновременно работать в кабинете.
- AI-генерация не блокирует обучение и должна быть ограничена очередью/лимитами.
- Массовый импорт штатки и массовое назначение курсов не должны ломать обычные read/progress сценарии.

## 2. Базовая модель нагрузки

Реалистичный профиль на 500 онлайн:

| Роль / операция | Одновременная активность | Что делает |
| --- | ---: | --- |
| Обучающиеся | 400 | Dashboard, список курсов, структура курса, прогресс уроков |
| Обучающиеся на тестах | 50 | Получение теста, отправка ответов, завершение курса |
| Админы / методологи | 30 | Dashboard, пользователи, тесты, курсы, trial usage |
| Импорт / штатка | 10 | Preview файла, ручное добавление сотрудника, apply-rules status |
| AI-генерация | 5-10 | Запуск генерации, polling jobs |

Отдельный стресс-профиль:

- 750 виртуальных пользователей на чтении и прогрессе.
- 30 одновременных AI jobs.
- 3-5 параллельных импортов штатки по 300-1000 строк.
- Массовое назначение курса на 300-500 сотрудников.

## 3. Что уже подготовлено

Исполняемый стартовый k6-скрипт:

```text
tests/load/k6-test.js
```

Сценарии:

- `learners` - чтение и прогресс обучающегося.
- `admins` - легкая нагрузка на админские списки и overview.
- `mixed` - приближенная смешанная модель.
- `ramp500` - ступенчатый рост до 500 VU.
- `ai` - запуск AI-генерации, только если явно включить.
- `import` - preview импорта штатки, только если явно включить.

По умолчанию тяжелые и создающие данные операции отключены:

- `ENABLE_WRITES=false`
- `ENABLE_AI=false`
- `ENABLE_IMPORT=false`

## 4. Подготовка тестового tenant

Нужен отдельный staging/load-test tenant, не рабочий tenant клиента.

Подготовлен сидер:

```text
scripts/seed_load_tenant.py
```

Безопасная проверка без записи в БД:

```powershell
python scripts/seed_load_tenant.py --dry-run --learners 10 --courses 2
```

Создание стандартного load-test tenant:

```powershell
python scripts/seed_load_tenant.py --learners 500 --courses 20 --reset
```

Скрипт берет `MIGRATION_DATABASE_URL` или `DATABASE_URL` из `.env`, если `--database-url` не передан явно. Поэтому перед запуском на production нужно осознанно выбрать отдельный load-test tenant. Флаг `--reset` удаляет данные только внутри tenant с указанным `--slug`, но это все равно destructive-операция для этого tenant.

Результат скрипта:

- tenant `load-test.kml`;
- админы и методологи;
- обучающиеся;
- опубликованные курсы, модули, уроки, тесты;
- enrollments для обучающихся;
- файл `tests/load/load-users.csv` с тестовыми логинами для `k6`.

`tests/load/*.csv` добавлен в `.gitignore`, потому что это runtime-артефакт с тестовыми учетными данными.

Важно: для password-login текущий backend ищет tenant по домену email. Поэтому `--slug` должен быть доменоподобным, например `load-test.kml`, а тестовые пользователи будут созданы как `load-learner-0001@load-test.kml`.

Минимальный seed:

- 500-1000 обучающихся.
- 10-20 пользователей с ролями `admin`, `org_admin`, `methodologist` или `teacher`.
- 20 опубликованных курсов.
- 100-300 уроков.
- 100-300 тестов.
- 500-1000 назначений курсов.
- 2-3 загруженных документа для AI-генерации.
- XLSX штатки на 300, 500 и 1000 строк.

Для корректного `k6` прогона нужно заранее получить:

- `AUTH_TOKEN` для одного тестового пользователя, либо
- `USER_CSV` со строками `email,password` или `email,password,token`.

Для смешанного профиля лучше разделять токены по ролям:

- `AUTH_TOKEN` - обучающийся.
- `ADMIN_AUTH_TOKEN` - администратор tenant.
- `METHODOLOGIST_AUTH_TOKEN` - методолог/teacher для AI, тестов и импорта.

Также желательно передать:

- `COURSE_ID`
- `LESSON_IDS` через запятую
- `QUIZ_IDS` через запятую

## 5. Команды запуска

Локальный smoke:

```powershell
k6 run tests/load/k6-test.js
```

Проверка 100 пользователей на продоподобном API:

```powershell
$env:BASE_URL = "https://kamilya-lms-api.onrender.com"
$env:SCENARIO = "learners"
$env:VUS = "100"
$env:DURATION = "10m"
$env:AUTH_TOKEN = "<test-user-access-token>"
$env:ADMIN_AUTH_TOKEN = "<tenant-admin-access-token>"
$env:METHODOLOGIST_AUTH_TOKEN = "<methodologist-access-token>"
$env:COURSE_ID = "<course-uuid>"
$env:LESSON_IDS = "<lesson-uuid-1>,<lesson-uuid-2>,<lesson-uuid-3>"
$env:QUIZ_IDS = "<quiz-uuid-1>,<quiz-uuid-2>"
k6 run tests/load/k6-test.js
```

Ступенчатый прогон до 500 пользователей:

```powershell
$env:BASE_URL = "https://kamilya-lms-api.onrender.com"
$env:SCENARIO = "ramp500"
$env:RAMP_TARGET = "500"
$env:RAMP_HOLD = "10m"
$env:AUTH_TOKEN = "<test-user-access-token>"
$env:COURSE_ID = "<course-uuid>"
$env:LESSON_IDS = "<lesson-uuid-1>,<lesson-uuid-2>,<lesson-uuid-3>"
$env:QUIZ_IDS = "<quiz-uuid-1>,<quiz-uuid-2>"
k6 run tests/load/k6-test.js
```

Админский профиль:

```powershell
$env:SCENARIO = "admins"
$env:VUS = "30"
$env:DURATION = "10m"
$env:AUTH_TOKEN = "<admin-access-token>"
k6 run tests/load/k6-test.js
```

AI-профиль включать только на staging/load tenant:

```powershell
$env:SCENARIO = "ai"
$env:VUS = "5"
$env:DURATION = "5m"
$env:ENABLE_AI = "true"
$env:AUTH_TOKEN = "<methodologist-access-token>"
$env:AI_DOCUMENT_IDS = "<document-id-1>,<document-id-2>"
$env:AI_NUM_MODULES = "1"
k6 run tests/load/k6-test.js
```

Импорт штатки preview:

```powershell
$env:SCENARIO = "import"
$env:VUS = "3"
$env:DURATION = "5m"
$env:ENABLE_IMPORT = "true"
$env:AUTH_TOKEN = "<methodologist-access-token>"
$env:STAFF_FILE = "C:\path\to\staff.xlsx"
k6 run tests/load/k6-test.js
```

## 6. Метрики приемки

Для первого платящего tenant минимально приемлемо:

| Метрика | Цель |
| --- | ---: |
| `http_req_failed` | < 2% |
| `http_req_duration p95` для чтения | < 1.5 сек |
| `http_req_duration p99` для чтения | < 4 сек |
| `kamilya_lesson_progress_duration p95` | < 1.2 сек |
| `kamilya_quiz_submit_duration p95` | < 2 сек |
| Ошибки 500 | 0 на smoke и < 0.5% на stress |
| AI start latency | < 2 сек до получения job id |
| AI job processing | уходит в очередь/status, не держит HTTP request |
| Staff import preview 500 строк | < 10 сек |

## 7. Что смотреть во время прогона

Render:

- CPU/RAM backend service.
- Request latency.
- 5xx rate.
- Restart/crash events.
- Worker/background task logs.

PostgreSQL/Supabase:

- connection count.
- CPU/RAM.
- slow queries.
- lock waits.
- RLS/session context errors.

AI providers:

- rate limits.
- timeout/error rate.
- fallback from Qwen to DeepSeek.
- LLM cost per tenant.

Application logs:

- `tenant_id`
- `user_id`
- `request_id`, если есть
- `job_id`
- route + status + duration

## 8. Риски, которые надо проверить отдельно

1. AI generation сейчас является самым тяжелым сценарием. Его нельзя считать частью обычных 500 онлайн без очереди и лимитов.
2. Массовый импорт штатки может блокировать request, если apply-rules выполняется inline слишком долго.
3. Отправка тестов и завершение курса создают записи прогресса, attempts, enrollment status и сертификаты. Это write-heavy участок learner-flow.
4. `/quizzes/grouped` и course structure могут стать тяжелыми на tenant с сотнями курсов и тысячами уроков.
5. Trial limits должны выдерживать конкурентные запросы без гонок: нельзя позволить двум параллельным операциям превысить лимит.
6. Авторизация через refresh cookie не тестируется полноценно в k6, потому что k6 работает на API-уровне. UI/session нужно добивать Playwright smoke.

## 9. Следующие доработки для качественного load test

1. Добавить seed-скрипт `scripts/seed_load_tenant.py`, который создает tenant, пользователей, курсы, уроки, тесты и назначения.
2. Добавить сервисный endpoint или CLI для выдачи access tokens тестовым пользователям без email OTP.
3. Добавить structured access logs с route, status, duration, tenant_id и user_id.
4. Добавить Prometheus/Grafana или Render/Supabase dashboard для наблюдения во время прогона.
5. Вынести AI-генерацию и индексацию документов в контролируемую очередь с per-tenant concurrency.
6. Добавить отдельные тесты гонок trial limits: параллельное создание курсов, обучающихся и пользователей системы.
7. Добавить Playwright smoke под 10-30 браузеров: login, admin dashboard, course reading, quiz submit, logout.

## 10. Рекомендуемый порядок прогонов

1. Smoke: 5 VU, 2 минуты, staging.
2. Baseline: 50 VU, 10 минут, learners.
3. Working load: 100 VU, 15 минут, mixed.
4. Pre-launch: 250 VU, 20 минут, mixed.
5. Target: 500 VU, 10-20 минут hold, mixed/ramp500.
6. Stress: 750 VU, 10 минут, только если target прошел без деградации.
7. AI/import stress отдельно, с ограничением бюджета и только на load-test tenant.

## 11. Критерий готовности к первому tenant

Проект можно считать готовым к первому крупному tenant, если:

- learner-flow держит 500 VU без массовых 500/timeout;
- обычное обучение работает даже во время AI/import нагрузки;
- AI операции уходят в управляемый job-flow и не блокируют API;
- импорт штатки не приводит к долгим зависшим запросам;
- ошибки видны в логах с tenant/user/job контекстом;
- есть понятный runbook: как запустить тест, где смотреть метрики, как остановить тест.

## 12. Журнал первого прогона 2026-07-08

Подготовлено:

- установлен `k6` локально через `winget`;
- добавлен seed-скрипт `scripts/seed_load_tenant.py`;
- создан load tenant `load-test.kml`;
- сгенерирован `tests/load/load-users.csv` с тестовыми пользователями и короткоживущими access token;
- CSV и диагностические логи исключены из git.

Проверки:

| Прогон | Результат |
| --- | --- |
| 1 VU / 10 секунд, learner-flow | Успешно, 0 ошибок |
| 10 VU / 30 секунд, learner-flow с токенами | Успешно, 0 ошибок, p95 около 191 мс |
| 50 VU / 60 секунд, learner-flow с токенами | Не прошел: около 40% HTTP errors, p95 около 4.4 сек |

Корневая причина 50 VU:

```text
asyncpg.exceptions.InternalServerError:
(EMAXCONNSESSION) max clients reached in session mode - max clients are limited to pool_size: 15
```

Вывод: первый серьезный bottleneck не в k6-сценарии и не в логине. Backend в проде использует Supabase session pooler с лимитом 15 клиентов, а приложение было настроено на `pool_size=20` и `max_overflow=10`, то есть могло пытаться открыть до 30 соединений. Под нагрузкой это превращалось в 500/401 каскад уже на 50 VU.

Принятое исправление:

- вынести настройки DB pool в env;
- для Render задать `DB_POOL_SIZE=5`, `DB_MAX_OVERFLOW=5`, `DB_POOL_TIMEOUT=10`;
- после деплоя повторить 10 VU и 50 VU.

Ожидаемый эффект: вместо падения по лимиту Supabase лишние запросы должны ждать свободное соединение внутри приложения. Это может увеличить latency, но должно убрать массовые 500. Если после этого 50-100 VU будут слишком медленными, следующий технический шаг - менять стратегию подключения к БД: transaction pooling/отдельный DB plan/оптимизация количества DB-запросов на каждый learner request.
