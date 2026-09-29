# Field-level аудит внешних AI, embeddings, email и support-потоков

## 1. Карточка аудита

| Поле | Значение |
|---|---|
| Статус | Статический аудит актуализирован после локального исправления tenant-aware routing |
| Дата | 29 сентября 2026 года |
| Проект | Kamilya LMS (`Kamilya-NEW`) |
| Срез кода | ветка `feature/privacy-foundation-20260929`, база аудита `4a73340c` |
| Охват | внешние payload builders AI/embeddings и email/support, их маршрутизация, локальное сохранение и логирование |
| Метод | Graphify-навигация, затем построчная сверка вызывающего кода, адаптеров, моделей и тестов |
| Не выполнялось | вызов внешних API, чтение кабинетов провайдеров, проверка их регионов/договоров/retention, DEV/production readback |

Аудит отвечает на узкий технический вопрос: какие поля Kamilya фактически
формирует и может передать за пределы основного tenant-контура. Он не требует
маскировать штатные карточки сотрудников, журнал обучения или внутренние
выгрузки уполномоченного tenant.

Статусы доказательства:

- `CODE VERIFIED` — поведение подтверждено текущими исходниками;
- `RUNTIME NOT VERIFIED` — активная production-конфигурация и сторона
  провайдера в этом проходе не проверялись;
- `PROVIDER CONTRACT NOT VERIFIED` — условия хранения/обучения/удаления у
  внешнего провайдера не выводятся из кода Kamilya.

## 2. Фактическая маршрутизация провайдеров

### 2.1. Генерация

Глобальная цепочка `ResilientLLMClient` строится в таком порядке:

1. DeepSeek — внешний managed provider, если ключ настроен и маршрут включён;
2. Qwen 3.8 Flash Next — частный OpenAI-compatible endpoint;
3. GLM 5.3 Flash — частный OpenAI-compatible endpoint.

Tenant override заменяет глобальную цепочку одним явно настроенным провайдером
и при ошибке его разрешения fail-closed. Но override применяется только там,
где вызывающий код передал `tenant_id` в `from_settings_async()`.

### 2.2. Embeddings

Глобальная цепочка `ResilientEmbeddingsClient` строится в таком порядке:

1. все модели совместимого семейства Voyage V4, начиная с настроенной модели;
2. три частные реплики ASUS Qwen3-Embedding-8B;
3. Cohere, если ключ настроен.

Следствие: при наличии ключа Voyage исходный текст отправляется managed provider
до попытки частных Qwen-реплик. При отказе выбранной модели тот же batch может
быть повторно передан другим моделям Voyage, а затем другим провайдерам.

Tenant embedding override также заменяет глобальную цепочку, но только при
передаче `tenant_id` вызывающим модулем.

### 2.3. Реальные HTTP payloads

Генерация отправляет:

```json
{
  "model": "<server-selected model>",
  "messages": [{"role": "system|user", "content": "<prompt>"}],
  "temperature": 0.2,
  "max_tokens": 8192,
  "response_format": {"type": "json_object"}
}
```

Embeddings отправляют один из вариантов:

```json
{"model": "<model>", "input": ["<source text>"], "input_type": "document|query"}
```

```json
{
  "model": "<cohere model>",
  "texts": ["<source text>"],
  "input_type": "search_document|search_query",
  "embedding_types": ["float"],
  "output_dimension": 1024
}
```

Ни один низкоуровневый адаптер не удаляет прямые идентификаторы из `messages`,
`input` или `texts`. Он считает подготовку разрешённого payload обязанностью
вызывающего модуля.

## 3. Матрица AI/embedding-полей

| ID | Функция | Поля, уходящие провайдеру | Маршрут tenant-aware | Что сохраняется Kamilya | Решение |
|---|---|---|---|---|---|
| `AI-01` | Индексация документа | `model`; массив полных `chunk.text` | Да: ingestion связывает client с tenant | исходный файл, chunks, vectors, provenance | Полный учебный текст является содержанием разрешённой операции; отдельное маскирование вводится только для отдельного подтверждённого сценария |
| `AI-02` | Evidence V2: retrieval quality | все `SourceFact.value`; запросы из title, objective и названий attributes | Да | facts, vectors, retrieval diagnostics | Полные факты нужны для качества retrieval; внутренние `fact_id` провайдеру embeddings не отправляются |
| `AI-03` | Evidence V2: урок | lesson title/objective; purpose/audience/emphasis; для каждого факта `fact_id`, subject, attribute, точный value, source locator; question seeds | Да | итоговые уроки, вопросы, evidence mapping, diagnostics | Учебные факты передаются полностью в выбранный tenant route; blanket masking не применяется |
| `AI-04` | Evidence V2: тесты и проверки | lesson title/objective; facts; semantic axes; candidates; options; explanation; source quote; cited facts | Да | вопросы, варианты, evidence IDs, axis/block outcomes | Повторная передача фактов является частью одной разрешённой генерации; отдельный sanitized envelope не является текущим требованием |
| `AI-05` | Ручная генерация теста к уроку | lesson title, до ограниченного объёма lesson content, difficulty, language, methodologist guidance | Да | черновик после подтверждения пользователя | Содержимое идёт через выбранный tenant route; дополнительная трансформация возможна позже для отдельного use case |
| `AI-06` | Регенерация модуля/урока | course/module/lesson titles и descriptions, lesson content, guidance, параметры структуры | Да | новая draft-версия контента и тестов | Tenant route соблюдается; дополнительный disclosure gate не блокирует текущую модель продукта |
| `AI-07` | Методистский AI-чат и подбор аудитории | course summary/content, target block, message; aggregate scope names/counts/context | **Да, локально исправлено** | ответ и применяемое изменение; recommendation response | `tenant_id` передаётся resolver; существующая очистка контактов сохранена |
| `AI-08` | Learner assistant | course title/description; lesson/module title; до 7000 символов lesson content либо сводные excerpts; свободный вопрос обучающегося | **Да, локально исправлено** | полный вопрос и ответ в `learner_assistant_messages` | Provider выбирается в контексте tenant; retention остаётся отдельной продуктовой политикой |
| `AI-09` | Question editor preview | instruction; question; все answer options и correct flags; explanation; evidence locator и excerpt | **Да, локально исправлено** | structured patch, source refs, provider provenance | Tenant берётся из проверенного `ResolvedQuestionContext`, а не из клиентского payload |
| `AI-10` | Анализ должностной инструкции | до 8000 символов извлечённого файла, название/отдел/уровень, обязанности и требования | **Да, локально исправлено** | структурированная должность и audit findings | Анализ и повторный audit используют один tenant route |
| `AI-11` | Рекомендации курсов и onboarding-тест по должности | position name, department, level, responsibilities, requirements | **Да, локально исправлено** | рекомендации/черновики после действий пользователя | Tenant provider contract соблюдается |

### 3.1. Что текущая очистка действительно умеет

Центральный `log_redaction.redact_sensitive_text()` скрывает email, телефон,
Bearer/JWT и некоторые пары `token/password/code/...`. Это граница журналов, а
не полноценный privacy-transformer исходных материалов. В частности, она не
обнаруживает надёжно:

- ИИН и иные 12-значные идентификаторы с контекстом;
- ФИО и подписи физических лиц;
- адреса и произвольные табельные/договорные номера;
- идентификаторы, расположенные в таблицах без явного имени поля.

Только отдельные функции — AI-чат методиста и audience advisor — вызывают
частичную очистку до LLM. Основной Evidence V2, ingestion, learner assistant,
question preview и JD analysis отправляют выбранный текст без такой очистки.

## 4. Матрица email/support-полей

При Resend Kamilya отправляет `from`, `to[]`, `subject`, `text`, `html`, иногда
`reply_to` и idempotency header. При SMTP те же значения входят в MIME message.
Тело письма неизбежно доступно выбранному транспортному провайдеру.

| ID | Письмо/операция | Поля у провайдера | Локальное сохранение | Оценка минимальности |
|---|---|---|---|---|
| `EM-01` | Login, registration и training confirmation OTP | recipient email, одноразовый code, назначение и срок | связанная auth/step-up state; payload не логируется | Минимально необходимо. Код нельзя маскировать в самом письме; запрещено логировать |
| `EM-02` | Team welcome/trial | email, имя, company name, login URL, текст о способе входа | user/tenant и provider message status где применимо | Пароль не отправляется; состав приемлем |
| `EM-03` | Invitation/course/path assignment/reminder | email, learner name, company, course/path title, due date, access URL с capability token при активации | invitation/outbox status; для `UserInvitation` raw token хранится в строке приглашения | Поля письма нужны адресату. Raw capability token at rest следует заменить verifier/hash после одноразовой выдачи |
| `EM-04` | Course review | reviewer name/email, course title, access URL, временный PIN; reminder без PIN | recipient; provider message ID; encrypted payload с URL/PIN для доставки | Состав письма обоснован. Локальная encrypted copy лучше открытого payload; retention всё равно надо определить |
| `EM-05` | Announcement | email, company, title, body, optional course title | announcement и список получателей определяются tenant | Полное body ожидаемо; нужна только обычная роль/tenant-защита |
| `EM-06` | Support request | support inbox; reply-to; reference; tenant; requester name/email/role; category; subject; full message; current path **вместе с query string** | те же поля в `support_requests`, status и provider message ID | Query string автоматически добавляется без необходимости. Передавать только нормализованный pathname либо allowlist безопасных параметров |
| `EM-07` | Public lead notification | операторский email; все сохранённые поля lead, включая contact, message, UTM, gclid, referrer, landing page, consent version и ROI-поля | полный lead в БД | Письмо является полной копией CRM-записи. Для оперативного уведомления достаточно контакта, компании, интереса/сообщения и внутренней ссылки; attribution лучше оставить в БД |

### 4.1. Техническая телеметрия email

Положительные свойства текущей реализации:

- payload и адрес получателя не пишутся в штатный email log;
- ошибки Resend сохраняют только HTTP status и закрытую error category;
- SMTP/Resend exceptions преобразуются в безопасные `EmailDeliveryError`;
- idempotency используется там, где повторная доставка создаёт риск дубля;
- course-review URL/PIN сохраняются зашифрованными.

Непроверенная сторона: retention и регионы самого email provider, содержимое
его dashboard/logs и фактическая production-конфигурация.

## 5. Findings

### `EXT-BACKLOG-01` — нет единого outbound disclosure gate для AI

`CODE VERIFIED`. Низкоуровневые клиенты передают полученный текст как есть, а
каждый feature самостоятельно решает, что включить в prompt. Общего контракта
`purpose + recipient + provider class + allowed fields` нет. Поэтому доказать
минимизацию для нового AI-вызова без ручного повторного аудита невозможно.

Это наблюдение не является блокирующим дефектом текущего продукта: tenant
передаёт учебный материал для генерации курса выбранному для него провайдеру.
Возвращаться к disclosure gate следует только при появлении отдельного сценария,
где часть исходного содержания действительно не нужна получателю.

### `EXT-OBS-02` — managed embeddings являются первым маршрутом

`CODE VERIFIED`. При наличии Voyage key document chunks/facts сначала уходят в
Voyage V4, а частные Qwen-реплики используются позже. Это не «внешний fallback
после локального контура». Внешняя передача происходит в штатном успешном пути.

Порядок провайдеров не меняется этим пакетом: это действующая операционная
конфигурация, а не доказанный дефект.

### `EXT-P0-03` — часть AI-функций обходила tenant provider selection

`LOCAL VERIFIED`. Learner assistant, editor question preview, methodology chat,
audience advisor, JD analysis и position recommendations теперь передают
достоверный `tenant_id`. AST-контракт запрещает новый user-facing resolver без
tenant context; поведенческие тесты фиксируют UUID на ключевых границах.

### `EXT-BACKLOG-02` — существующий redactor не предназначен для исходных документов

`CODE VERIFIED`. Он предназначен для логов и не покрывает ИИН, ФИО, подписи,
адреса и контекстные идентификаторы. Расширять его до «угадывания всего» тоже
неправильно: silent rewrite может повредить учебный смысл.

### `EXT-BACKLOG-03` — support автоматически прикладывает query string

`CODE VERIFIED`. Frontend формирует
`window.location.pathname + window.location.search`, API сохраняет значение и
EmailService отправляет его support inbox. Для диагностики обычно достаточно
pathname; query-параметры нужно исключать по умолчанию.

### `EXT-BACKLOG-04` — public lead email копирует расширенную атрибуцию

`CODE VERIFIED`. `_public_lead_rows()` перечисляет каждое поле dataclass,
включая UTM/gclid/referrer/landing/ROI. Email notification не нуждается во всей
аналитической записи.

### `EXT-BACKLOG-05` — raw provider response может остаться в exception cause

`CODE VERIFIED`. При HTTP 4xx AI adapter помещает первые 500 символов response
body в `HTTPStatusError`, затем в `ProviderFailedError`; обычные failover logs
пишут только тип ошибки, но `logger(..., exc_info=True)` в другом слое может
развернуть cause chain. Центральный redactor не гарантирует удаление
произвольного echoed source text. В exception нужно хранить status/category, а
не response body.

### `EXT-BACKLOG-06` — invitation capability token хранится открытым

`CODE VERIFIED`. `UserInvitation.token` хранит raw token, хотя публичные
capability-потоки в других модулях используют hash/verifier. Это не лишнее поле
email provider, но увеличивает ущерб при доступе к БД и относится к той же
цепочке приглашения.

### `EXT-OBS-03` — сторона внешних провайдеров не подтверждена

`RUNTIME NOT VERIFIED`, `PROVIDER CONTRACT NOT VERIFIED`. По коду нельзя
установить production route, регион обработки, retention, dashboard logging,
training opt-out и удаление данных у DeepSeek, Voyage, Cohere, OpenRouter или
Resend.

## 6. Обязательный архитектурный seam

Для текущей модели продукта обязателен один проверяемый маршрут:

```text
authenticated tenant operation
  -> verified tenant_id
  -> tenant-aware provider resolver
  -> tenant override, если настроен
     иначе platform provider chain
  -> provider adapter
```

Правила:

1. Каждый пользовательский AI entry point получает tenant identity только из
   аутентифицированного пользователя или уже проверенного tenant context.
2. Отсутствующий или неверный tenant context прекращает resolution до обращения
   к провайдеру; неявный переход на глобальную цепочку запрещён.
3. Ошибка tenant override не должна приводить к fallback с другим tenant или
   платформенным ключом.
4. Полный учебный payload разрешён выбранному provider route как содержание
   явно запрошенной tenant-операции.
5. `ExternalDisclosureRequest`, masking, `PRIVATE_ONLY` и typed email builders
   могут быть спроектированы отдельно только для подтверждённого сценария; они
   не входят в обязательный seam этого пакета.

## 7. Порядок исправления и приёмка

### Пакет A — закрыть маршрутизацию — локально выполнен

- сделать `tenant_id` обязательным для user-facing AI provider resolution;
- исправить `AI-07`–`AI-11`;
- добавить negative tests: tenant override никогда не обращается к global
  provider, а ошибка override не приводит к fallback с чужим ключом.

Критерий выполнен локально: статический контракт покрывает все перечисленные
user-facing modules, а поведенческие тесты проверяют tenant identity без
реального внешнего вызова. DEV/production readback не выполнялся.

### Необязательный backlog B — outbound disclosure policy

- catalogued purposes для `AI-01`–`AI-11`;
- provider class (`private`, `managed`, `email`);
- high-confidence detectors минимум для email, phone, IIN, capability token и
  labelled personnel number;
- stable in-request placeholders;
- private-only outcome для неоднозначного/смыслового identifier;
- один sanitized envelope повторно используется author/review/repair стадиями.

Не включать в текущий scope без конкретного продуктового сценария и отдельного
решения владельца: blanket masking может повредить учебный смысл.

### Необязательный backlog C — минимизировать email/support

- support отправляет pathname без query string;
- public lead notification получает явный allowlist оперативных полей;
- invitation raw token заменяется hash/verifier с одноразовой выдачей ссылки;
- raw provider response body удаляется из AI exception chain.

Критерий: contract tests сравнивают exact outbound payload; query/UTM/gclid/raw
token/provider response body отсутствуют в неразрешённых поверхностях.

### Отдельная эксплуатационная проверка D — runtime/provider readback

Без изменения тарифов и настроек подтвердить:

- фактический порядок production routes;
- provider account/project;
- регион, retention, training/data-collection settings;
- email dashboard/log retention;
- sanitized synthetic canary в telemetry;
- exact release SHA после отдельного разрешённого релиза.

## 8. Итог аудита

Внутренняя tenant-модель не требует blanket masking. Единственный подтверждённый
кодовый дефект этого аудита — обход tenant provider selection — исправлен
локально. Disclosure transformation, email/support minimization и provider
readback остаются отдельными необязательными или эксплуатационными задачами и
не блокируют этот пакет.

## 9. Индекс кодовых доказательств

| Предмет | Основные исходники |
|---|---|
| Порядок LLM/embedding routes и HTTP payload | `apps/api/app/modules/ai/llm_client.py`: `_BaseProviderClient._request`, `LLMClient.ainvoke`, `EmbeddingsClient._embed`, `ResilientLLMClient.from_settings_async`, `ResilientEmbeddingsClient.from_settings_async` |
| Tenant BYOK и provider classes | `apps/api/app/modules/admin/tenant_ai_providers/service.py`: `resolve_tenant_provider` |
| Evidence V2 fields | `apps/api/app/modules/ai/pipeline.py`: `_run_evidence_v2_generation`; `evidence_engine/provider_engine.py`: `_realizer_request`; `evidence_engine/application.py`; `evidence_engine/semantic_assessment.py` |
| Document chunks/embeddings | `apps/api/app/modules/ai/ingestion.py`: `EmbeddingsProvider`, `IngestionPipeline.ingest` |
| Assistant/JD/editor callers | `modules/learner_assistant/router.py`; `modules/ai/router.py`; `modules/ai/audience_advisor.py`; `modules/editor_assistant/router.py`; `modules/ai/question_preview.py`; `modules/positions/jd_router.py`; `modules/positions/recommendations_router.py`; `modules/quizzes/ai.py` |
| Email payloads/transports | `apps/api/app/core/email.py`: все `send_*`, `_send_resend`, `_send_smtp` |
| Support auto-context | `apps/web/src/components/support/SupportRequestDialog.tsx`; `apps/api/app/modules/support/schemas.py`; `router.py`; `models.py` |
| Lead notification | `apps/api/app/core/email.py`: `PublicLeadNotification`, `_public_lead_rows`, `send_public_lead_notification` |
| Invitation token/storage | `apps/api/app/models/users.py`: `UserInvitation`; `apps/api/app/modules/users/invitations_service.py` |
| Log/telemetry redaction | `apps/api/app/core/log_redaction.py`; `apps/api/tests/test_llm_failover.py`; `apps/api/tests/unit/test_log_redaction.py` |
