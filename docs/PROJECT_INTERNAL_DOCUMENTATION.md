# Kamilya LMS: внутренняя документация проекта

**Статус:** рабочая документация проекта
**Дата актуализации:** 2026-07-31
**Репозиторий:** `KamillaLMSCRM/Kamilya-NEW`

## 1. Назначение продукта

Kamilya LMS — multi-tenant LMS для корпоративного обучения. Tenant — отдельная компания со своими пользователями, курсами, документами, должностями, назначениями, сертификатами и настройками.

Главная продуктовая идея:

```text
документы компании → AI/методолог → курс и тест → назначение → обучение → сертификат → HR-контроль
```

Система рассчитана на работу HR, методолога, администратора tenant и обучающегося. Superadmin управляет платформой и tenant-ами.

## 2. Репозиторий и запуск

```text
apps/api/       FastAPI backend, SQLAlchemy, Alembic
apps/web/       Next.js 14 frontend, React, TypeScript
docs/           продуктовые, архитектурные и эксплуатационные документы
```

Локально:

```powershell
cd apps/api
python -m uvicorn app.main:app --reload --port 8000

cd apps/web
npm install
npm run dev
```

Для Windows production-проверка frontend запускается через `npx next build`. Unix-синтаксис вида `NEXT_TELEMETRY_DISABLED=1 command` в PowerShell не используется.

## 3. Архитектура

### Backend

- FastAPI routers группируют API по доменам.
- SQLAlchemy async используется для доступа к PostgreSQL.
- Alembic хранит миграции.
- `app.core.auth` отвечает за JWT, текущего пользователя, tenant context и RBAC.
- `app.core.email.EmailService` поддерживает `log` и Resend.
- AI-пайплайн генерирует структуру и содержание курсов из документов.
- Qwen используется как основной AI-провайдер в соответствующих потоках; fallback зависит от конкретного AI-модуля.

### Frontend

- Next.js App Router.
- `apps/web/src/components/layout/Sidebar.tsx` — основная навигация.
- `apps/web/src/lib/api.ts` — Axios-клиент с access token и refresh-on-401.
- `apps/web/src/store/authStore` — состояние текущей сессии.
- Локали: RU, EN, KK.

## 4. Tenant isolation и безопасность

Каждая tenant-сущность содержит `tenant_id`. Backend дополнительно проверяет tenant в запросах, а PostgreSQL использует `ENABLE/FORCE ROW LEVEL SECURITY` и `app.tenant_id`.

Новые tenant-таблицы должны обязательно иметь:

1. `tenant_id` и FK на `tenants.id`.
2. RLS policy с безопасным `NULLIF(current_setting(...), '')`.
3. `FORCE ROW LEVEL SECURITY`.
4. Проверку принадлежности входящих `course_id`, `user_id`, `position_id` текущему tenant.
5. Тест на доступ между tenant-ами.

Секреты хранятся только в локальном `.env` или в секретах Render/Vercel. В git нельзя добавлять `.env`, API keys, JWT secrets, пароли БД, root/VPS credentials или токены GitHub.

## 5. Роли

| Роль | Назначение |
|---|---|
| `superadmin` | Платформа, tenant-ы, провайдеры AI, impersonation, операционный контроль |
| `admin` | Администратор tenant: системная команда, настройки, интеграции, киоски и доступы |
| `methodologist` | Курсы, тесты, штат, должности, программы, назначения, cohorts, компетенции и результаты |
| `student` | Обучение, тесты, программы обучения, сертификаты, AI-помощник |

`methodologist` — единственная learning-content роль. Она владеет курсами,
тестами и назначениями, но не tenant-инфраструктурой.

Один системный пользователь tenant-а может иметь несколько назначенных ролей,
но в сессии выбирает один active working role. API и навигация используют
активную роль, а не объединение полномочий. Канон: ADR-0012 и ADR-0008.

## 6. Основные доменные потоки

### 6.1 Tenant onboarding

1. HR/владелец открывает регистрацию tenant.
2. Указывает компанию, контактное лицо, email и пароль.
3. Создаётся tenant, первый admin и trial-лимиты.
4. Вход выполняется email OTP через Resend либо Telegram-потоком, если он настроен.
5. После входа пользователь должен попасть в tenant dashboard, а не в student dashboard.
6. Admin получает один governance-шаг: добавить активного methodologist в
   системную команду.
7. Methodologist получает отдельные шаги: добавить обучающегося, подготовить
   документ, создать курс, назначить обучение, отправить invitation link и
   проверить завершённое обучение в журнале.

Onboarding status вычисляется backend по tenant-scoped данным. Admin не видит
learning-шаги, methodologist не видит governance-шаг. Trial state возвращает
срок и отдельные счётчики. Исчерпание ресурса даёт состояние `limited`, а
истечение периода — `support_required`.

#### Telegram auth session lifecycle

`apps/api/app/modules/auth/auth_sessions.py` хранит browser-to-bot flow в общем
Redis, а не в API-process memory:

```text
auth:code:<code>:pending
auth:code:<code>:verified
```

- allocation Lua script резервирует сразу обе lifecycle keys и не допускает
  повторного кода, пока существует pending или verified state;
- webhook Lua script создаёт verified payload с оставшимся TTL через `SET NX`
  и удаляет pending; повторная доставка webhook не перезаписывает первый
  authoritative payload;
- polling Lua script атомарно читает и удаляет verified key. Только первый
  consumer получает user payload; следующий получает `not_found`;
- TTL auth code — 300 секунд;
- process-local `_memory_store` разрешён только при
  `APP_ENV=development|test`;
- в production ошибка Redis возвращает unavailable/false и не создаёт session:
  authentication fail-closed.

Логи содержат только безопасные event names вроде
`auth_sessions_redis_unavailable`; auth code и user payload не печатаются.

### 6.2 Подготовка персонала

Канонический экран методолога: `/staff`.

- импорт штатки Excel/CSV с preview и mapping;
- для многолистового XLSX выбирается один лист сотрудников; справочные листы
  отделов и должностей не считаются импортированными;
- ручное добавление сотрудника без загрузки файла;
- каноническая запись `Department -> Position -> User`;
- визуализация дерева отделов, должностей и сотрудников после commit.

Ручная форма по умолчанию принимает канонические `department_id` и
`position_id`. Текстовые названия используются только в явно выбранном режиме
создания нового отдела/должности и в совместимом import-контракте. Backend
проверяет tenant ownership обоих ID и отклоняет должность из другого отдела.

Структура на `/staff?tab=structure` является единственным реестром отделов,
должностей и сотрудников в навигации методолога. Действие **Профиль и
обучение** ведёт на `/positions/{position_id}?tab=training`, действие
**Обязательные курсы** у отдела — на
`/training-rules?scope=department&department_id=...`, а
**Назначить обучение** у сотрудника — на `/assignments?user_id=...`.
Группы обучения ведутся в `/cohorts`.

### 6.2.1 Invitation delivery и activation

Bulk endpoint `POST /v1/users/invitations/bulk` принимает не более 200 email и
всегда создаёт только learner role. Service нормализует и дедуплицирует email,
проверяет tenant-local existing identity/pending invite и переиспользует
импортированного `User(role=student)` без login access вместо создания дубля.

Invitation rows и pending users коммитятся до внешней доставки. После commit
router ставит отдельную `users.deliver_invitation` Celery task для каждой новой
записи. Поэтому отказ broker/provider не откатывает приглашение и не теряет
copyable activation URL.

Task открывает новую DB session, устанавливает tenant context, блокирует
invitation row `FOR UPDATE` и проверяет terminal state. Duplicate broker
delivery пропускается для accepted/sent/permanent-failed invitation. Только
transient provider categories получают bounded Celery autoretry с backoff,
jitter и `max_retries=3`.

На `UserInvitation` сохраняются:

- `delivery_status`: `pending`, `sent` или `failed`;
- `delivery_message_id` внешнего provider;
- `delivery_last_attempt_at` и `delivery_attempt_count`;
- `delivery_failure_category` и ограниченное безопасное сообщение;
- обычный invitation lifecycle `pending/accepted/expired/revoked/superseded`.

Если email delivery не настроен или queue dispatch недоступен, backend пишет
`provider_unconfigured` либо `queue_unavailable`, а UI продолжает показывать
activation link для manual fallback. Это резервный путь, не единственная
доставка. Resend по-прежнему отдельно доставляет invitation-bound OTP после
открытия ссылки.

### 6.2.2 Каноническая карточка квалификационных требований должности

Канонический экран методолога для настройки должности:
`/positions/{position_id}`. Отдельный реестр `/positions` сохранён как
совместимый маршрут, но исключён из sidebar и command palette. Точка входа для
пользователя — дерево на `/staff?tab=structure`. Карточка объединяет сведения,
которые раньше были распределены между должностями, матрицей компетенций,
правилами обучения и onboarding-настройками.

Карточка состоит из следующих вкладок:

| Вкладка | Назначение | Источник истины |
|---|---|---|
| Профиль | Название, отдел, уровень, обязанности и требования должности | `positions` |
| Должностная инструкция | Текущий документ, статус индексации, версия и ссылка на источник | `documents` + поля должности |
| Компетенции | Обязательные компетенции и ожидаемый уровень для этой должности | связь должности с `competencies` |
| Обязательное обучение | Курсы, обязательные именно для должности, а также сводный эффективный набор | правила должности, отдела и компетенций |
| Onboarding-тест | Сохраненный шаблон контрольных вопросов по должности | `position_quizzes` |
| История версий | Снимки состояния квалификационных требований и восстановление | `position_qualification_versions` |

#### Источники обязательного обучения

Система показывает три независимых источника:

1. **Должность** — курсы, назначенные непосредственно этой должности. В этой вкладке методолог меняет правило `required`.
2. **Отдел** — курсы, назначенные отделу, к которому относится должность. Они показываются как унаследованные и не редактируются из карточки должности.
3. **Компетенция** — курсы, связанные с обязательными компетенциями должности. Они также показываются как унаследованные.

`effective_courses` — объединение этих источников без дублей. Это вычисляемый итог для контроля полноты требований, а не отдельный четвертый источник, который нужно редактировать. Для изменения унаследованного курса нужно открыть соответствующее правило отдела или компетенции.

#### Версии и аудит изменений

Карточка хранит неизменяемые снимки квалификационного состояния. При первом изменении создается базовая версия, последующие содержательные изменения создают новые версии с автором, датой, типом изменения и необязательной причиной. В снимок входят профиль, текущая ДИ, компетенции, правила обучения и onboarding-шаблон.

История нужна для ответа на вопросы «что требовалось от должности на дату назначения» и «кто изменил требования». Восстановление выполняется из вкладки истории и само становится новым изменением; старая версия не переписывается. Восстановление не должно ссылаться на удаленные или чужие tenant-объекты: если документ, компетенция или курс больше недоступны, операция отклоняется с понятной причиной.

Изменения, сделанные старыми редакторами ДИ, профиля или onboarding-теста, также должны попадать в эту историю. Поэтому историю нельзя считать только журналом действий новой карточки.

#### Ownership

Карточка принадлежит learning-content роли `methodologist`. Методолог отвечает за актуальность ДИ, профиля должности, компетенций, обязательного обучения и шаблона onboarding-теста. Tenant admin отвечает за пользователей, доступы, настройки и организационные данные, но не редактирует содержание карточки и не назначает учебный контур как методолог.

Onboarding-тест в текущей реализации является сохраненным и редактируемым шаблоном. Он может быть сгенерирован из ДИ, но пока не преобразуется в исполняемый `Quiz`, не назначается сотрудникам и не имеет самостоятельного маршрута прохождения. Это отдельный незавершенный продуктовый поток, который нельзя описывать как уже работающую автоматизацию.

### 6.3 Загрузка и индексация источников

`POST /v1/documents/upload` выполняет только проверку файла, сохранение
исходника в object storage и атомарное создание `Document` + `AIJob`. После
commit API ставит `document_reindex_task` в Celery и возвращает документ со
статусом `processing`, `indexing_job_id` и `status_url`. OCR и embeddings не
должны удерживать браузерный HTTP-запрос.

Worker скачивает сохранённый исходник и передаёт его в локальный гибридный
конвертер на VPS. PDF сначала классифицируется по ограниченной выборке страниц:
файл с пригодным текстовым слоем идёт через MarkItDown, а скан или text-poor PDF
через Docling OCR/layout. DOCX/XLS/XLSX сначала проходят через MarkItDown; при
непригодном результате используется Docling. Старый Word `.doc` предварительно
преобразуется headless LibreOffice в `.docx`, после чего идёт по тому же
Office-маршруту. MarkItDown работает без plugins и принимает только локальный
временный файл, без URL и внешнего OCR.

Результат задания сохраняет движок, его версию, факт fallback и предупреждения.
Для text-poor PDF отсутствие пригодного результата OCR является ошибкой:
MarkItDown не подменяет OCR и точное восстановление layout. Если допустимые движки не дали
пригодный Markdown, индексация завершается ошибкой; бинарный файл нельзя
подменять текстовой заглушкой. После конвертации worker перестраивает pgvector
index и переводит документ в `ready`, `partial` или `failed`. Базовый лимит
источника 50 МБ. Converter дополнительно ограничен 50 MiB, одним одновременным
заданием и 30 секундами ожидания слота; очередь документов остаётся durable в
Celery и обрабатывается отдельным worker с concurrency 1.

### 6.4 Создание курса

Канонические варианты:

- `/ai/generate`: загрузка документов, выбор аудитории, числа модулей и языка;
- `/courses`: ручной курс или SCORM 1.2 import;
- `/courses/[id]/edit`: редактирование модулей и уроков.

Для обычного AI-курса выбор документов является частью доменной модели, а не только параметром UI:

1. `POST /v1/ai/document-compatibility` строит tenant-scoped semantic-профили выбранных документов по центроидам chunk embeddings.
2. Complete-link clustering возвращает `compatible`, `mixed` или `incompatible` и не позволяет объединить две далёкие темы через промежуточный документ.
3. При неоднородном наборе методолог выбирает одну тематическую группу либо передаёт `source_strategy=intentional_combination` с общей учебной целью не короче 20 символов.
4. Backend повторяет анализ перед списанием trial-лимита и постановкой Celery-задачи. Клиентское состояние не является доверенным источником решения.
5. Architect назначает каждому уроку `source_doc_ids` только из выбранного набора. Writer извлекает контент строго из этих документов.
6. Если релевантные chunks отсутствуют, задача завершается контролируемой ошибкой. Fallback на общие знания LLM запрещён.
7. Qwen embeddings использует Voyage как fallback. При недоступности обоих провайдеров индексация завершается ошибкой; синтетические hash-векторы не сохраняются.

Перед резервированием trial-генерации и списанием LLM-бюджета backend выполняет
tenant-scoped admission. По умолчанию один tenant может иметь не более двух
задач генерации или регенерации в статусах `pending/running`. Решение
сериализуется блокировкой строки `tenants`, поэтому параллельные HTTP-запросы
не обходят лимит. Отказ возвращает `429`, код
`tenant_ai_job_limit_reached` и `Retry-After`; квота и бюджет при этом не
расходуются. Общий `create_ai_job` не ограничен этим правилом: индексация,
переиндексация и cleanup документов работают в отдельной очереди и не должны
останавливаться из-за двух генераций курса.

`AIJobResponse` содержит `tenant_active_jobs`, `tenant_active_limit`,
`queue_position` и `estimated_wait_seconds`. Позиция считается только среди
durable jobs текущего tenant и не выдаётся за глобальную позицию внутри Redis
или Celery. ETA основан на двух AI worker slots и историческом ориентире 510
секунд на задачу; это эксплуатационная оценка, не SLA. Отмена остаётся
идемпотентной, а поздний callback worker не может воскресить `cancelled` job.

Трассируемость сохраняется на двух уровнях:

- курс: `source_document_ids`, `source_strategy`, `source_combination_goal`, `source_analysis`;
- урок: `source_document_ids`, `source_references`, `source_validation_status`.

Векторный и OCR-ориентированный lexical retrieval сохраняют в каждой ссылке
реальный `document_embeddings.id` как `chunk_id`. Lexical fallback пропускает
фрагмент без `chunk_id` или `doc_id`; такой фрагмент не может сделать урок
`verified`. Это позволяет проверить ссылку урока до конкретной tenant-scoped
строки индекса, а не только до имени исходного документа.

Ручное изменение названия или содержания урока устанавливает `source_validation_status=needs_review`. Grounded-регенерация возвращает `verified`; одобрение курса методологом фиксирует явную проверку оставшихся изменений.

Публикация является единственной границей доступности курса:

- черновик доступен методологу, но не обучающемуся;
- AI-курс нельзя опубликовать до `review_status=approved`;
- ручное назначение черновика запрещено на backend;
- правила должности и отдела материализуют назначения только для опубликованных курсов;
- автор курса не записывается на него автоматически как обучающийся.

При каждой публикации backend формирует `ContentRelease`:

- детерминированный снимок курса, модулей, уроков, блоков, тестов, вопросов и
  вариантов ответа;
- идентификаторы и SHA-256 исходных документов или SCORM-пакета;
- номер версии, SHA-256 полного снимка, автора и время публикации;
- `courses.current_release_id` указывает на текущую опубликованную версию;
- новое назначение получает `enrollments.content_release_id` на уровне БД.

Опубликованный доказательственный снимок не редактируется и не удаляется через
обычные операции курса. Следующая публикация создаёт новый release. Поэтому
изменение черновика не переписывает содержание, которое было назначено ранее.

Тестовая попытка принимает только полный набор вопросов конкретного теста.
Неизвестные вопросы, повторная отправка одного вопроса и вариант ответа от
другого вопроса отклоняются. В `quiz_attempts` сохраняются:

- enrollment и content release;
- вопросы, варианты, выбранные и правильные ответы;
- баллы, результат и временные метки;
- `evidence_sha256` полного снимка попытки.

DB-trigger запрещает изменение и удаление доказательственного снимка попытки.
Эта модель подтверждает целостность данных внутри Kamilya, но сама по себе не
удостоверяет личность подписанта, не является ЭЦП и не гарантирует принятие
записи судом или регулятором.

Для двуязычного продукта язык выбирается при генерации; целевая модель — русский и казахский варианты из одного источника, а не простое переключение языка интерфейса.

#### AI-рекомендация аудитории

`POST /v1/ai/chat` поддерживает read-only intent
`audience_recommendation`. Сервис получает текущий курс и формирует
tenant-scoped снимок из агрегированной структуры, cohorts, компетенций,
существующих правил и назначений. В LLM payload не передаются ФИО, email,
телефоны и Telegram ID.

Явные связи курса с организацией, отделом, должностью или компетенцией имеют
приоритет над семантическим предположением модели и не могут быть удалены или
понижены LLM. Structured response валидируется по набору кандидатов,
сформированному backend. При недоступности LLM возвращается
детерминированный fallback по явным связям.

Контур не вызывает assignment mutations. `assignment_url` появляется только
для опубликованного курса и ведёт на `/assignments?course_id=...`;
окончательное действие выполняет методолог после проверки состава аудитории и
явного подтверждения.

#### Контекстные назначения и доступ

`/assignments` остаётся каноническим экраном ручной mutation, но исключён из
sidebar и command palette. Точки входа передают `course_id` или `user_id`, а UI
предвыбирает известный контекст. Назначаются только опубликованные курсы.

После подтверждения создаются недостающие `Enrollment` с `source=manual`.
Сотрудник штатной структуры уже является tenant-scoped `User(role=student)`,
поэтому приглашение не создаёт второго пользователя. Если у него ещё нет
подтверждённого способа входа, invitation service создаёт `UserInvitation` с
тем же `user_id`; UI запрашивает ссылку через
`POST /users/{user_id}/invitation-link` и не выполняет поиск пользователя по
email. Нормализованный email уникален внутри тенанта на уровне БД. Повторный
email при ручном добавлении или импорте штатки возвращает конфликт вместо
создания второго профиля. UI показывает персональную ссылку активации.
Сотрудник без email получает назначение, но требует отдельной настройки
способа входа.

Публичный экран приглашения отдаёт только маскированный email и кадровые данные
в режиме чтения. `POST /invitations/{token}/request-code` создаёт отдельный от
обычного login OTP код, привязанный к `invitation_id`, и доставляет его через
платформенный Resend. `POST /invitations/{token}/accept` принимает только этот
шестизначный код, после проверки фиксирует `email_verified_at`,
`verification_method=email_otp`, IP и User-Agent, активирует существующего
пользователя и выдаёт access/refresh session. ФИО, табельный номер и пароль
обучающийся не вводит и не изменяет.

`Quiz` принадлежит уроку через обязательный `lesson_id` и наследует доступ
курса. Отдельная панель назначения теста удалена из конструктора; старый
`/admin/quizzes/assign` перенаправляет в конструктор тестов.

#### Надёжность исходных документов

Карточка `documents` не заменяет бинарный исходник: файл хранится в настроенном
storage backend, а PostgreSQL содержит tenant-scoped метаданные, SHA-256,
версию и состояние индекса. Успешная загрузка считается завершённой только
после сохранения исходного файла; переиндексация читает тот же объект и не
создаёт новую версию.

- Подтверждённый ответ Storage `not_found/404` записывается как
  `index_error_code=source_blob_missing`. Это терминальное состояние для
  текущей версии: UI не предлагает повторять переиндексацию, а ведёт
  методолога в загрузку новой версии источника.
- Сетевая ошибка, таймаут или отказ провайдера Storage не считаются
  отсутствием файла. Backend поднимает временную ошибку, сохраняет повторяемый
  `reindex_failed` и не предлагает пользователю заменять заведомо существующий
  источник.
- `AIJob.errors` входит в ответ job polling API, чтобы frontend выбирал
  правильное восстановительное действие по машинному коду, а не по тексту
  сообщения.
- Восстановление старых данных допустимо только после проверки размера,
  SHA-256 или полного совпадения заново построенных chunks с существующим
  индексом. Нельзя выставлять `ready`, если исходный blob не проверен.

### 6.4.1 Курс по должностной инструкции

Канонический P0-поток реализован на `/positions`:

```text
Position
  -> current Document(category=job_instruction)
  -> AIJob(course_id=pre-created draft)
  -> Course(source_instruction_id, source_instruction_version_at)
  -> PositionCourse(required=true)
```

- `POST /v1/positions/{position_id}/instruction` сохраняет бинарный источник в настроенный storage backend, индексирует документ, привязывает его к должности и обновляет извлечённые поля.
- `GET /v1/documents/{document_id}/download` отдаёт исходник только пользователю того же tenant с learning-content ролью.
- `POST /v1/positions/{position_id}/generate-instruction-course` создаёт один native draft для текущей версии источника и запускает существующий AI pipeline в заранее созданный `course_id`.
- Для должностной инструкции architect ограничивает черновик шестью уроками, а
  assessment создаёт по три проверяемых single-choice вопроса на урок. Для
  обычного курса базовый assessment содержит пять single-choice вопросов на
  урок; дополнительные вопросы методолог добавляет осознанно в конструкторе.
- Повторный запрос при активной или завершённой генерации возвращает conflict и не создаёт дубль. После failed job разрешён повторный запуск того же draft без повторного списания лимита.
- Замена инструкции создаёт новый `Document`; новый курс остаётся черновиком и не меняет действующие назначения до публикации.
- При публикации новой версии курса по ДИ снимаются прежние `PositionCourse`-связи той же должности со всеми старыми курсами по ДИ, затем выполняется пересчёт назначений текущим сотрудникам.
- Старый курс и результаты завершивших его сотрудников остаются историческими; новым сотрудникам назначается только актуальная опубликованная версия.
- `TenantUsage.jd_course_generations_used` и `jd_course_generations_limit` образуют отдельный trial-счётчик. Обычный `ai_course_generations_used` для этого потока не списывается.

Текст, извлечённый из ДИ, не считается юридически проверенным. Методолог должен проверить поля должности и содержание курса, явно одобрить AI-результат и только затем опубликовать курс.

### 6.5 Назначение

Поддерживаются:

- ручное назначение через `/assignments`;
- правила должности/отдела;
- программы обучения (`/learning-paths`): прямые и групповые назначения
  материализуют только доступные сейчас курсы в `enrollments` с
  `source=learning_path`;
- cohorts (`/cohorts`) хранят только reusable audience. Cohort выбирается в
  программе или другом assignment rule, но сам не хранит и не применяет курсы.

Материализация идемпотентна: повторное применение не создаёт дублей, существующее завершённое обучение не сбрасывается.

### 6.6 Обучение

Обучающийся использует `/student` и `/my-courses`:

- видит назначенные курсы;
- продолжает незавершённый курс;
- проходит native или SCORM 1.2 курс;
- проходит тест;
- получает сертификат;
- использует AI-помощника в native-уроке в рамках контекста курса/урока.

Завершение опубликованного native-курса создаёт идемпотентное
`TrainingEvidenceEvent(procedure_type=training)`. Отправка теста создаёт
`knowledge_check`. Оба события связаны с enrollment и immutable
`ContentRelease`. Событие не создаётся для черновика или при отсутствии
release.

Если снимок события требует подтверждения, обучающийся получает purpose-bound
email OTP. Challenge привязан одновременно к tenant, пользователю и событию,
имеет TTL, cooldown и лимит попыток. Verify принимает только `challenge_id` и
код; канонический текст действия и версия объекта вычисляются backend. Это
step-up confirmation, не ЭЦП.

`GET /v1/training-evidence/events/mine` возвращает только безопасную проекцию
собственных событий. Dashboard включает `enrollment_id`, поэтому завершённый
курс при повторном открытии восстанавливает последнее событие `training` и
незавершённое подтверждение не теряется.

Kiosk — отдельный режим входа по QR/ссылке. Production QA kiosk требует валидный tenant kiosk token и отдельную проверку таймаута/приватности.

### 6.7 Контроль обучения

- `/training-log` — канонический экран методолога для единого журнала native и
  SCORM; backend route сохраняет префикс `/admin/training-log`;
- summary: assigned, in progress, completed;
- CSV export с локализованными пользовательскими заголовками, UTF-8 BOM и
  разделителем `;` для корректного открытия в русской версии Excel;
- evidence projection по каждому enrollment: события обучения и проверки
  знаний, confirmation status, correction/revocation/legal hold;
- индивидуальные PDF/ZIP и групповые PDF/ZIP доступны только methodologist для
  подтверждённых готовых событий; смешение tenant, сотрудников или процедур
  отклоняется backend;
- исходное событие нельзя update/delete. Исправление и отзыв создают новые
  связанные append-only записи; экспорт использует последнюю effective
  correction и сохраняет полную цепочку;
- `generated_at` пакета вычисляется из последнего события, подтверждения или
  перехода legal hold, а не из времени HTTP-запроса. Поэтому одинаковое
  состояние формирует идентичные PDF/ZIP, manifest и SHA-256;
- step-up проверяет отзыв по всему дереву original/correction. Отзыв потомка
  блокирует подтверждение исходной записи;
- PDF явно показывает `revoked` и активный legal hold, а manifest содержит
  полную машинно-читаемую историю;
- `/admin` — governance-сводка и системная команда для администратора;
- trial status и role onboarding берутся из
  `/api/v1/admin/onboarding-status`, без второго дублирующего запроса;
- `/competencies` — связь компетенций с должностями и курсами;
- `/announcements` и `/surveys` — сохранённые коммуникационные модули,
  временно скрытые из навигации до выполнения продуктового backlog.

### 6.7.1 Tenant procedures и fail-closed evidence gate

`/training-procedures` — methodologist-only CRUD для versioned tenant
definitions. Поддерживаются `acknowledgement`, `internal_attestation` и
`admission_decision`; состояния — `draft`, `active`, `retired`.

- edit/delete разрешены только для draft;
- один procedure code может иметь только одну active version;
- activation требует approval reference/date/approved by, legal или local
  basis, retention class и retention days;
- internal attestation дополнительно требует members, quorum и decision record;
- admission decision требует authority, decision record и effective date.

Procedure является конфигурацией и сама не создаёт evidence event. Generic
`POST /training-evidence/events` и correction router отклоняют `training`,
`knowledge_check`, `internal_attestation` и `admission_decision`. Первые два
типа создаёт trusted learning workflow; последние два остаются fail-closed до
отдельного фактического workflow комиссии/уполномоченного решения.

OTP или step-up confirmation подтверждает purpose-bound действие, но не ЭЦП.
Completion, quiz result и correction не являются аттестацией или допуском.

### 6.7.2 Restricted evidence share

Methodologist формирует share из одного или нескольких event ids. Service один
раз строит точные PDF/ZIP bytes и сохраняет их вместе с SHA-256, content type,
public filename и source event ids. Публичный download не пересобирает пакет,
поэтому выдаваемое содержимое остаётся immutable для данной share.

Ограничения share:

- token хранится только как SHA-256;
- expiry находится в будущем и не превышает 31 день;
- `max_downloads` — от 1 до 100;
- package size — не более 25 MiB;
- revoke делает ссылку недоступной;
- Redis rate limit — 20 запросов с hashed IP за 60 секунд;
- unavailable limiter закрывает public endpoint с `503`;
- перед выдачей проверяется SHA-256 package bytes;
- access log хранит outcome и download count без публичного PII.

Expired, revoked, exhausted или corrupted share возвращает одинаковый generic
`404 Share unavailable`, чтобы не раскрывать внутреннее состояние.

### 6.7.3 Retention cursor и manual purge

`/training-retention` управляет одной tenant policy на каждый procedure type.
Active policy требует legal или local basis. Удаление active policy запрещено.

Purge сначала запускается как dry-run. Execute требует точный typed token
`PURGE_TRAINING_EVIDENCE`, повторное browser confirmation, прямую Argon2-проверку
текущего пароля уже аутентифицированного методолога и `max_roots` от 1 до 100.
Проверка не выпускает новые JWT, не меняет login-сессию и закрыта для OTP-only
аккаунтов без password credential. DB SECURITY DEFINER function дополнительно
проверяет tenant context, confirmation token и root limit.

Таблица `training_evidence_retention_cursors` хранит per-tenant
`last_occurred_at` и `last_root_id`. Каждый bounded call продвигает cursor;
после конца выборки следующий проход начинает цикл заново. Scan budget равен
`min(max_roots * 10, 1000)`, чтобы active hold, более новая chain или active
share не занимали весь deletion budget и не скрывали новые eligible roots.

Result возвращает `scan_budget`, `roots_scanned`, `truncated`, eligible/purged
roots, удалённые events/confirmations/hold history/shares и reason counts.
Legal hold остаётся DB-level blocker. Scheduled purge, operational schedule и
backup retention не реализованы и остаются backlog.

## 7. Новые продуктовые модули

### Программы обучения

В UI доменная сущность называется **Программа обучения**. В API и БД сохранено
техническое имя `learning_path`.

Таблицы:

- `learning_paths` — версия программы, статус, семейство версий и режим
  прохождения `linear|open`;
- `learning_path_courses` — упорядоченные обязательные и дополнительные шаги;
- `learning_path_assignments` — индивидуальные назначения после разрешения
  аудитории (человек, cohort, отдел или должность), сроки, статус и аудит.

Базовая схема появилась в миграции `0056`; версии, назначения, неизменяемость
опубликованного содержания и RLS добавлены миграцией `0075`.

Правила:

- управляет только активная роль `methodologist`;
- публикация требует название, хотя бы один курс и хотя бы один обязательный
  курс;
- аудитория и сроки выбираются в draft на третьем шаге мастера; API назначения
  вызывается только после успешной публикации;
- команда **Опубликовать и назначить** последовательно сохраняет draft,
  публикует неизменяемую версию и создаёт назначения выбранной аудитории;
- если публикация прошла, а создание назначения завершилось ошибкой, версия
  остаётся опубликованной, мастер возвращает методолога на этап
  **Аудитория** для повторного назначения без повторной публикации;
- опубликованная версия неизменяема, изменения создают новый draft в том же
  `family_id`;
- обучающийся видит только назначенные ему опубликованные версии;
- в `linear`-режиме следующий курс открывается после завершения предыдущего
  обязательного шага, в `open`-режиме доступны все курсы;
- при завершении курса сервис пересчитывает прогресс программы и идемпотентно
  материализует следующий доступный `Enrollment`;
- отмена назначения не отнимает доступ, созданный другим правилом, и не удаляет
  исторические результаты обучения.

### Competencies

Таблицы: `competencies`, `position_competencies`, `competency_courses`. Миграция `0057`.

### Announcements

Таблица `announcements`, ручной delivery через Resend/log provider. Миграция
`0058`. Раздел скрыт из sidebar и command palette; условия возврата описаны в
[`PRODUCT_BACKLOG.md`](PRODUCT_BACKLOG.md).

### Surveys

Таблицы `surveys`, `survey_responses`. Опрос доступен только после
`Enrollment.status=completed`; один ответ на пользователя и опрос. Миграция
`0059`. Раздел скрыт из навигации вместе с learner entry point до появления
аналитики ответов и завершённого manager flow.

### Cohorts

Таблицы `cohorts`, `cohort_members`, `cohort_courses` появились в миграции
`0060`. Текущий продуктовый контракт использует только `cohorts` и
`cohort_members`: группа является сохранённой аудиторией сотрудников.
`cohort_courses` сохранена только для expand-compatible чтения старых данных.
API изменения course links отклоняет, endpoints apply/progress не являются
рабочим продуктовым flow. Новые назначения создаются из курса, программы или
правила.

### Operational console

`/admin/super/operations` и
`/api/v1/admin/super/operations/*` доступны только `superadmin`.

- summary содержит агрегированные AI queue/running/failure, индексацию и
  cleanup документов, состояние DB pool и runtime процесса;
- tenant names, email, filenames и job messages не возвращаются;
- synthetic cleanup по умолчанию выполняет dry-run;
- удаление допускается только для `is_demo=true`, фиксированного test-prefix,
  возраста не менее 24 часов и после точного typed confirmation;
- cleanup ограничен 100 tenant за один запуск и повторно проверяет guards перед
  каждым удалением.

## 8. Миграции и deploy

Цепочка текущих feature-миграций:

```text
0055 добавление роли methodologist
0056 learning paths
0057 competency matrix
0058 announcements
0059 surveys
0060 cohorts
0061-0062 последующие продуктовые и инфраструктурные изменения
0063 источники должностных инструкций и связь с курсами
0066 канонизация methodologist и удаление прежнего технического alias
0067 восстановление primary-ролей пользователей после канонизации RBAC
0068 тематический контроль, provenance и статусы проверки источников AI-курса
0069-0072 provider, kiosk, quiz и source-catalog hardening
0073 версии квалификационных требований должности
0074 удаление org_admin
0075 версии и назначения программ обучения
0076 правила обучения на уровне организации
0077 employment profile сотрудника
0078 tenant guard назначений программ обучения
0079 нормализация legacy-отделов из текстовых значений должностей
0081-0084 immutable content/evidence baseline и последующие evidence changes
0085 invitation delivery lifecycle
0086 tenant training procedures
0087 restricted training evidence shares
0088 retention policies, cursor и controlled purge
0089 procedure gate для regulated evidence types
```

Перед production deploy:

1. проверить `alembic current` и `alembic heads`;
2. применить миграции на staging;
3. проверить RLS под `lms_app`;
4. выполнить smoke API и frontend;
5. только затем раскатывать production.

Render и Vercel deploy green не заменяют проверку миграций и ручной happy path.

Текущий P1 рабочего дерева не имеет deployment evidence. До отдельной проверки
нельзя переносить на него исторические API/web/worker revisions, migration
state или production smoke. KZ PostgreSQL/object storage и реальный pawnshop
acceptance test отложены.

Владельцы DDL определены явно:

- Render выполняет `alembic upgrade head` в `preDeployCommand`;
- Docker API выполняет миграцию до запуска Uvicorn и завершает startup с
  ошибкой, если миграция не прошла;
- HTTP lifespan приложения миграции не запускает.

`app/models/registry.py` загружает все ORM-модули для Alembic. Registry
проверяется тестом на полноту, но это не означает автоматическое равенство
исторической БД и ORM. На 2026-07-29 `alembic check` обнаруживает накопленный
schema drift, включая SQL-only `document_embeddings`; применять предлагаемые
remove-операции без отдельной сверки запрещено.

## 9. Проверки

Минимальный gate:

```powershell
python -m compileall -q apps/api/app
python -m pytest apps/api/tests -q
cd apps/web
npm test
npm run typecheck
npx next build
```

Известные ограничения текущей проверки:

- Docker/Postgres может отсутствовать локально;
- полный integration suite требует PostgreSQL;
- production SCORM QA требует реальные пакеты iSpring/Articulate;
- browser console warnings от расширений не являются автоматически ошибкой приложения.

## 10. Правила дальнейшей разработки

- Сначала читать `AGENTS.md`, `docs/LESSONS.md`, ADR и текущий код.
- Не добавлять legacy-дубли экранов без миграционного плана.
- Разделять current code, deployment evidence и backlog; не описывать
  development candidate как уже выпущенный production-контур.
- Для каждой новой tenant-фичи добавлять RLS, миграцию, API, UI и focused test.
- Коммиты и push выполнять автором `kamilla_lms_crm@proton.me`; GitHub token использовать через `http.extraheader`, не через Credential Manager.
