# План: продуктова аналитика и feedback-loop ассистента вопросов

**Статус:** proposal (план на утверждение; кодом не проверен).
**Дата:** 2026-08-30.
**Владелец:** root orchestrator Kamilya.
**Контур:** разработка; без mutation dev/CT125/VM126/production.
**Родительский план:** `docs/plans/2026-08-30-contextual-ai-editor-and-generation-quality-plan.md`
(шаг 10 «Product analytics dashboard» и раздел 6 «Request and feedback logging»).
**Назначение:** превратить накопленные паттерны переработки методологов — запросы
вида «добавь больше информации к вопросу 3» или «дай другие варианты ответа» —
в измеримый privacy-safe feedback-контур для улучшения генерации курсов и тестов.

Все ссылки на символы в этом документе сверены с текущим рабочим деревом
2026-08-30. Элементы, которых в коде ещё нет, явно помечены `proposal` и не
должны описываться как существующие.

---

## 1. Продуктовые решения и non-goals

### 1.1 Решения

1. Таблицы lifecycle, таксономия и `EditorRequestService.record_event` уже
   существуют (`0135`–`0137`), но в текущем HTTP/use-case контуре подтверждено
   только emission события `requested`. Emission `preview_started`,
   `preview_ready`, `preview_failed`, `regenerated`, `applied`, `rejected`,
   `manually_edited_after_apply`, `published`, `superseded` и `expired` —
   proposal и **NOT VERIFIED**; runtime migration head также **NOT VERIFIED**.
2. Cross-tenant аналитика использует только нормализованные категории
   (`taxonomy.py`), counts, durations, безопасные версии и bounded reason
   codes. Raw instruction, тексты вопросов/ответов, provider output,
   fingerprints, request/payload IDs, event/request/target/actor IDs и любые
   row-level opaque identifiers не покидают tenant.
3. Feedback-сигналы необязательны для методолога: accept/reject работает и без
   причины; reason codes — это один клик по фиксированному списку
   `EditorReasonCode`, а не обязательная анкета.
4. Метрики влияют на генерацию только через версионированные изменения
   (prompt/generator/validator versions) и явный release-gate. Автоматической
   подстройки промптов, моделей или валидаторов из production-данных нет
   (родительский план, §7).
5. Владелец функции — методолог (`/courses/[id]/edit` и `/quizzes`);
   cross-tenant product view принадлежит superadmin. Tenant admin не получает
   доступ к контенту и аналитике ассистента (канонические границы ролей).
6. Минимальный размер когорты для cross-tenant отчётов защищает от
   деанонимизации низконагруженных tenant (см. §6.5).

### 1.2 Non-goals

1. Автоматический tuning промптов/весов/порогов из production-событий.
2. Отправка raw-контента во внешние analytics-системы, dataLayer или рекламные
   пиксели.
3. Fine-tuning моделей — отложено до отдельного ADR и evaluation-гейта
   (родительский план §11).
4. Замена существующего lifecycle-журнала новой таблицей событий; план только
   добавляет read-only проекции и опциональные reason-code DTO.
5. Публичный tenant-отчёт «как другие компании используют AI» — данные других
   tenant не раскрываются никогда.
6. Real-time дашборд: первый этап — отложенные агрегаты, а не потоковая
   аналитика.

---

## 2. Tenant-scoped таксономия событий

### 2.1 Три слоя данных

Код уже разделяет данные на три слоя; аналитика обязана сохранять эти границы:

| Слой | Хранилище | Содержимое | Роль в аналитике |
|---|---|---|---|
| Request projection | `ai_editor_requests` | normalized intent, версии provenance, `outcome_state`, raw `instruction_text` (tenant-only) | один ряд = один запрос; группировка по intent/locale/версиям |
| Lifecycle events | `ai_editor_request_events` | append-only события с allowlist-метаданными; фактически wired только `requested`, остальные emissions — proposal / NOT VERIFIED | потенциальный источник жизненного цикла и метрик исходов после wiring |
| Preview state | `ai_editor_request_previews` | pending/completed/failed + bounded `completed_result_json` ≤ 64 KiB | технический success/failure провайдера; не analytics source |

### 2.2 Классификация событий

Актуальные `event_type`-значения (`EditorLifecycleEventType`, taxonomy.py:63):

| Тип | Категория аналитики | Метрики |
|---|---|---|
| `requested` | lifecycle event | объём запросов, повторные кластеры |
| `preview_started` | lifecycle event | latency от requested до ready/failed |
| `preview_ready` | lifecycle event | provider success rate |
| `preview_failed` | lifecycle event + patch analytics | failure rate по `reason_code` |
| `regenerated` | lifecycle event | retries per request |
| `applied` | lifecycle event | acceptance rate |
| `rejected` | lifecycle event + patch analytics | rejection rate по `reason_code` |
| `manually_edited_after_apply` | patch analytics | manual-rework rate |
| `published` | lifecycle event | survival rate патча до публикации |
| `superseded` / `expired` | lifecycle event | abandonment |

Таблица и значения `EditorLifecycleEventType`, а также
`EditorRequestService.record_event`, существуют в текущем коде. Из
перечисленных событий сейчас подтверждено только фактическое wiring
`requested`; строки остальных типов описывают proposal-эмиссии и остаются
**NOT VERIFIED**. Поэтому метрики в третьем столбце являются целевыми, а не
уже вычислимыми runtime-метриками.

Примеры из запроса пользователя, отображённые в таксономию:

- «добавь больше информации к вопросу 3» → `intent_category=add_context`,
  `target_entity_type=quiz_question`;
- «дай другие варианты ответа» → `intent_category=regenerate_distractors`;
- повторный запрос того же intent по тому же `target_entity_id` → повторный
  кластер (см. §6.6).

### 2.3 Request projection vs patch analytics vs агрегаты

- **Request projection** — детерминированная функция
  `project_request(request)` (analytics.py:153), возвращает только
  `REQUEST_ANALYTICS_FIELDS = {intent_category, outcome_state}`. Это единственная
  санкционированная проекция запроса для аналитики.
- **Event projection** — `project_event(event)` (analytics.py:161): `event_type`
  плюс валидированные allowlist-метаданные. Невалидные метаданные отбрасываются
  в пустой dict, а не роняют запрос — privileged writer не может «провезти»
  произвольное значение через allowlist-ключ.
- **Patch analytics** — proposal: события `rejected`,
  `manually_edited_after_apply` и валидационные issue labels
  (`EditorQualityIssueLabel`) объединяются в per-request аналитику «что именно
  было не так»: relation intent ↔ issue labels ↔ reason code.
- **Aggregate reports** — proposal: сгруппированные cross-tenant отчёты
  (superadmin-контур), которые получают только cohort-safe агрегаты из новой
  validated aggregate-input projection; raw instruction, fingerprints и
  row-level identifiers не входят ни в один агрегат.

### 2.4 Событие validation outcome

Deterministic validator (`question_validator.py`, `validate_question_set`,
`ValidatorStatus` = `pass|warn|fail`) возвращает `QuestionValidationResult` с
`validator_version` и findings с кодами `EditorQualityIssueLabel`.
`validation_status` нельзя корректно восстановить только из `issue_labels`:
labels не кодируют blocking и не различают все причины `pass|warn|fail`.
Proposal: добавить отдельное валидируемое поле `validation_status` с закрытым
enum либо вычислять и сохранять статус внутри tenant-bound materialization;
до реализации этого контракта validation-status analytics остаётся **NOT
VERIFIED**.

---

## 3. Strict no-raw-content rule

### 3.1 Запрещённое содержимое

В события, метаданные, проекции, агрегаты, логи и reason codes запрещено
помещать: текст инструкции, текст вопроса, варианты ответов, объяснения,
фрагменты источников, provider raw output, промпты, email, имена, tenant
names, filenames, URL-подобные строки со смысловой нагрузкой и любые «evidence»
данные. Это распространяется и на «безопасные на вид» формулировки, полученные
копированием из tenant-контента.

### 3.2 Разрешённые типы значений

Tenant-bound storage и idempotency-контур могут использовать:

- **tenant-bound IDs и fingerprints**: `request_id`, `event_key`, UUID,
  `request_fingerprint_sha256`, payload/instruction fingerprints
  (SHA-256, schema `editor_assistant.request.v1`, service.py:460-492); они
  запрещены в любых cross-tenant projections, materializations, views,
  reports и exports;
- **enum-значения фиксированной таксономии**: `EditorIntentCategory`,
  `EditorQualityIssueLabel`, `EditorReasonCode`, `EditorLifecycleEventType`,
  `EditorAssistantFailureCode`;
- **counts и durations**: `attempt` (≤ 1000), `duration_ms` (≤ 30 дней,
  analytics.py:68-69);
- **versions**: `generator_version`, `prompt_version`, `model_id`,
  `validator_version` (нормализуются паттерном
  `^[A-Za-z0-9][A-Za-z0-9._:/-]{0,119}$`);
- **bounded reason codes**: только значения `EditorReasonCode` (taxonomy.py:48);
- **normalized fingerprints**: только `^[0-9a-f]{64}$`, исключительно внутри
  tenant-bound idempotency/retention контура.

Cross-tenant разрешены только enum-значения закрытых таксономий, counts,
durations, безопасные нормализованные versions и bounded reason codes. В
cross-tenant результатах запрещены request/payload/instruction fingerprints,
`request_id`, `event_key`, event/request/target/actor IDs, UUID-проекции и любые
row-level opaque identifiers.

### 3.3 Инженерные гарантии (уже реализованы)

1. `validate_event_metadata` (analytics.py:122) отклоняет неизвестные ключи
   целиком (`EditorMetadataValidationError`), а не молча вырезает: опечатка в
   ключе не теряет данные незаметно.
2. `issue_labels` валидируются по `EditorQualityIssueLabel`; `reason_code` — по
   `EditorReasonCode`; строка произвольного вида невозможна.
3. `project_event` при невалидных метаданных возвращает пустой dict — legacy
   или privileged-запись не протекает в cross-tenant view.
4. DB CHECK `ck_ai_editor_previews_result_size` ограничивает
   `completed_result_json` 64 KiB и требует JSON-объект.
5. Сырая инструкция хранится только в `ai_editor_requests.instruction_text`
   (tenant-контент). `instruction_expires_at` выражает retention intent, но
   purge worker и подтверждённое runtime/schema-состояние очистки отсутствуют:
   это proposal и **NOT VERIFIED**. CHECK
   `ck_ai_editor_requests_fingerprint_sha256` ограничивает fingerprint, но не
   доказывает purge raw-текста.

### 3.4 Proposal: guard для новых полей

Перед добавлением любого нового ключа в `EVENT_METADATA_ALLOWLIST` требуется:
(а) обновление `test_editor_assistant_telemetry.py::test_*allowlist*`;
(б) доказательство, что значение детерминированно нормализуемо; (в) отсутствие
свободного текста. Без этого аналитика читает только существующие восемь ключей.

---

## 4. Точные metadata allowlist по событиям

Канонический persisted allowlist — `EVENT_METADATA_ALLOWLIST` (analytics.py:45):
`issue_labels`, `duration_ms`, `attempt`, `generator_version`, `prompt_version`,
`model_id`, `validator_version`, `reason_code`. Ниже — proposal по уместным
ключам для каждого события (все значения проходят `validate_event_metadata`):

| event_type | Разрешённые ключи метаданных |
|---|---|
| `requested` | (пусто; версии provenance читаются из request-ряда, не дублируются) |
| `preview_started` | `attempt` |
| `preview_ready` | `duration_ms`, `attempt`, `generator_version`, `prompt_version`, `model_id`, `validator_version`, `issue_labels` |
| `preview_failed` | `duration_ms`, `attempt`, `generator_version`, `prompt_version`, `model_id`; failure должен либо явно маппиться в допустимый `EditorReasonCode` для `reason_code`, либо передаваться через proposal-поле `failure_code` с отдельной закрытой валидацией |
| `regenerated` | `attempt` |
| `applied` | `duration_ms`, `attempt` |
| `rejected` | `reason_code` (значение из `EditorReasonCode`), `issue_labels` |
| `manually_edited_after_apply` | `issue_labels` (повторно зафиксированные детерминированные сигналы, если пересчёт доступен) |
| `published` | (пусто) |
| `superseded` / `expired` | (пусто) |

Замечания:

1. `reason_code` валидируется только по `EditorReasonCode`; прямое помещение
   `EditorAssistantFailureCode` в этот ключ запрещено. Для `preview_failed`
   требуется явная таблица mapping failure → `EditorReasonCode` либо отдельное
   proposal-поле `failure_code` с закрытым enum и собственной валидацией.
   Утверждение о непересечении множеств кодов не является контрактом и не
   используется как гарантия.
2. `model_id` записывается только как `model_id`-строка provenance (например
   идентификатор модели из `ResilientLLMClient`), без endpoint-ов, ключей и
   payload-деталей.
3. Метаданные события `rejected` не содержат свободного комментария; текст
   пожеланий методолога — это tenant-контент запроса, а не метрика.
4. Приемлемость: событие `applied` не обязано нести `duration_ms`, если preview
   открывался в другой сессии; ключ опционален по определению allowlist.

---

## 5. UX методолога: reason codes без утечки

### 5.1 Принципы

1. Reason-код всегда необязателен: reject/apply работают одним действием без
   выбора причины. Отсутствие причины — валидное значение (`reason_code`
   отсутствует в метаданных).
2. Выбор — только из фиксированного списка; свободный текст в analytics-контур
   не вводится и не передаётся.
3. UI показывает причину на языке методолога (каталог фиксированных
   сообщений); в БД и аналитику уходит только enum-значение.

### 5.2 Каталог причин отклонения (уже в `EditorReasonCode`)

| Код | RU-подпись (proposal для UI) |
|---|---|
| `did_not_follow_request` | «Не то, что я просил(а)» |
| `unsupported_information` | «Есть информация не из источников» |
| `wording_worse` | «Формулировка стала хуже» |
| `answer_remained_obvious` | «Правильный ответ всё ещё очевиден» |
| `changed_too_much` | «Изменил(о) слишком много» |
| `provider_timeout` / `provider_error` / `validator_rejected` | в UX отклонения не показываются — это технические коды |
| `stale_base_version` | обрабатывается отдельным UX-состоянием stale, а не причиной reject |
| `other` | «Другое» |

### 5.3 «Что было не так» — issue labels

Если методолог отклоняет или вручную правит результат, UI может показать
готовые чекбоксы из детерминированных findings валидатора (то же множество
`EditorQualityIssueLabel`, что видит preview в `validation.issues` с
каталоговыми RU-сообщениями `_ISSUE_MESSAGES`). Мультивыбор ограничен
`_MAX_ISSUE_LABELS = 16`; выбранные значения записываются в `issue_labels`
события `rejected` или `manually_edited_after_apply`. Список initialized из
предложений валидатора, а не из произвольного ввода.

### 5.4 Дополнительные UI-ограничения (proposal)

- Причина запрашивается только на явном action «Отклонить с причиной»; основной
  reject — одно нажатие.
- Раздел «Что было не так» появляется максимум один раз на запрос и никогда не
  блокирует дальнейшую работу.
- Frontend не добавляет к событию никаких других полей: DTO-контракт
  (`EditorAssistantPreviewRequest`, `EditorAssistantApplyRequest`) остаётся
  без новых свободных строк.

---

## 6. Метрики

Метрики ниже — целевые определения. В текущем wiring подтверждено только
событие `requested`; остальные emissions и агрегирующая projection — proposal
и **NOT VERIFIED**, поэтому метрики пока не объявляются вычислимыми из
persisted runtime-данных. После реализации скользящее окно — по умолчанию 30
дней, с разбивкой по дням для трендов.

### 6.1 Acceptance / rejection / abandonment / manual rework

Для каждой пары `(intent_category, [slice])`:

- `preview_acceptance_rate = applied / preview_ready` (на request-уровне;
  `applied` учитывается один раз на request);
- `preview_rejection_rate = rejected / preview_ready`;
- `preview_abandonment_rate = (expired + superseded) / requested`;
- `manual_rework_rate = manually_edited_after_apply / applied` — ключевой
  сигнал «патч принят, но всё равно переписан вручную»;
- `regeneration_factor = regenerated / requested` — среднее число повторных
  генераций на запрос;
- `publication_survival_rate = published / applied` (terminal-состояние
  `published` подтверждает, что патч остался в опубликованной версии).

### 6.2 Distribution of issue labels

Частоты `EditorQualityIssueLabel` по событиям `preview_ready` (валидатор),
`rejected` и `manually_edited_after_apply` (человек). Пересечение валидаторных
и человеческих labels даёт «precision warnings»: доля warnings валидатора,
подтверждённых последующей ручной правкой или reject с той же меткой
(родительский план §7 «validator warning precision»).

### 6.3 Validation pass/warn/fail (proposal / NOT VERIFIED)

Доля `pass|warn|fail` требует explicit validated `validation_status` либо
tenant-bound materialization, вычисляющей статус из полного validation result.
Из `issue_labels` статус не выводится. После реализации рост `fail` по
`validator_version` будет сигналом к пересмотру порогов, а не автоматическому
откату (см. §7).

### 6.4 Срезы (slices)

Intent и уже разрешённые безопасные versions могут стать срезами после wiring.
`locale`, provenance/source-type и target-кластеры — proposal-only и требуют
новой validated aggregate-input projection. Она принимает только закрытые
нормализованные значения и никогда не экспортирует row-level IDs.

Предлагаемые срезы:

- intent (`EditorIntentCategory`);
- `model_id`, `prompt_version`, `generator_version`, `validator_version`
  (provenance с request-ряда);
- `locale` (ru/kk/…) — proposal, закрытый enum;
- `source_type_summary` — proposal, только закрытая source taxonomy; свободные
  source names/types запрещены;
- fallback/retry: `attempt` > 1 и `reason_code IN (provider_timeout,
  provider_error)` — доля запросов, потребовавших повтора провайдера;
- latency: p50/p95 `duration_ms` от `preview_started` до terminal
  (`preview_ready`/`preview_failed`).

### 6.5 Cohort-safe minimum sample sizes

- Cross-tenant агрегат отображается только при `n ≥ 10` запросов в ячейке;
  иначе ячейка объединяется в надгруппу или помечается «недостаточно данных».
- Экспорт/скачивание кросс-tenant отчётов на первом этапе не предоставляется;
  просмотр — только в superadmin-консоли.
- Метрики tenant-уровня (внутри одного tenant) показываются методологу без
  минимума выборки, но содержат только его собственные данные.

### 6.6 Repeated request clusters

Proposal / **NOT VERIFIED**: повторный кластер — ≥ 2 запросов с одинаковым
`intent_category` по одному `target_entity_id` в пределах 14 дней. Группировка
по `target_entity_id` выполняется только tenant-side; validated aggregate-input
projection передаёт cross-tenant только counts по закрытым категориям, без
`target_entity_id`, request/event IDs, fingerprints или иных row identifiers.
После реализации `rework_repeat_rate` — доля target-ов с кластерами среди всех
target-ов с ≥ 1 запросом.

---

## 7. Питание tuning-цикла

### 7.1 От метрик к изменениям

1. Регулярный (еженедельный) просмотр метрик §6 владельцем AI-качества.
2. Топ проблемных паттернов формулируется как **нормализованная гипотеза**:
   «intent X + issue label Y даёт manual_rework_rate > Z%».
3. Воспроизведение — только на синтетических фикстурах (существующие корпуса
   `test_question_preview.py`, `test_editor_assistant_question_validator.py`
   расширяются новыми случаями; копирование реального tenant-контента в фикстуры
   запрещено).
4. Изменение — одно из: prompt structure, deterministic validator thresholds
   (версионируется `ValidatorConfig`), model routing в
   `ResilientLLMClient.from_settings_async` (temperature 0.2, max_tokens 4096 —
   текущие значения router.py:159-162).

### 7.2 Experiment versioning

Каждое изменение несёт новый `prompt_version`/`generator_version`/
`validator_version`. Все три записываются в provenance запроса, поэтому метрики
§6 автоматически разбиваются по версиям без отдельной экспериментальной
разметки.

### 7.3 Holdouts и откат

- Новый релиз качества сначала включается на долю трафика (proposal: 50/50
  сравнение со стабильной версией по `prompt_version`), минимум до `n ≥ 200`
  preview-запросов на версию.
- Критерии промоции: acceptance rate не ниже, manual_rework_rate не выше,
  validation fail rate не выше, p95 latency в пределах оговорённого буфера.
- Откат thresholds: если новая версия валидатора даёт долю blocking fail выше
  оговорённого порога, `ValidatorConfig` откатывается к предыдущей версии
  (конфиг версионирован, откат не переписывает историю).
- **No automatic production tuning**: изменения промптов/порогов/роутинга
  выполняются только человеком через версионированный релиз; ни один сервис не
  читает production-события и не меняет конфигурацию сам.

---

## 8. Retention, изоляция, доступ, аудит

### 8.1 Tenant isolation (обязательный полный набор)

Три существующие таблицы уже имеют: `tenant_id` + FK на `tenants(id)` ON
DELETE CASCADE, RLS policy
`tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid`, FORCE
RLS (миграция `0135` для requests/events, `0136` для previews). Событие
защищено композитным same-tenant FK
`fk_ai_editor_events_same_tenant_request`, поэтому даже privileged connection
не может прикрепить событие к чужому запросу. Любая новая аналитическая таблица
повторяет все шесть пунктов (включая runtime role `lms_app` без `BYPASSRLS` и
cross-tenant тест) до merge.

### 8.2 Runtime privileges (факт миграции 0135)

- `ai_editor_requests`: `lms_app` — SELECT, INSERT, UPDATE только колонок
  `outcome_state, updated_at`; provenance-колонки иммутабельны.
- `ai_editor_request_events`: SELECT, INSERT; UPDATE/DELETE не выданы —
  append-only на уровне привилегий.
- `ai_editor_request_previews`: SELECT/INSERT + column-level UPDATE переходов
  жизненного цикла (миграция `0136`).

### 8.3 Retention

- `instruction_expires_at` выражает только retention intent. Purge worker и
  подтверждённое runtime/schema-состояние очистки — proposal / **NOT
  VERIFIED**.
- Требуется отдельная additive migration и worker/job, которые независимо
  purge или controlled-redact `instruction_text`, не полагаясь на fingerprint.
  Migration должна отдельно определить сохранение событий: какие event rows и
  cohort-safe metadata сохраняются после очистки инструкции, какие связи
  остаются tenant-bound и как исключается восстановление raw-контента.
- Proposal: retention-отчёт различает request без raw-инструкции и request с
  активной инструкцией только в tenant-bound view; cross-tenant получает counts.

### 8.4 Доступ

- Методолог: собственные запросы своего tenant (текущий scope
  `EditorRequestService.build_analytics_projection` —
  service.py:353, per-request).
- Superadmin: только cross-tenant агрегаты §6 через
  `/admin/super/operations`-стиль контура (без tenant PII, по образцу
  существующей operational console, где «tenant names, email, filenames и job
  messages не возвращаются»).
- Tenant admin: доступа к ассистенту и его аналитике нет.
- Learner: доступа нет.

### 8.5 Аудит и удаление/экспорт

- Кто запросил и применил — `actor_id` остаётся tenant-bound audit value; UUID
  запрещён в cross-tenant projections, reports и exports.
- Удаление tenant CASCADE удаляет и аналитические ряды; экспорт агрегатов —
  только через санкционированный superadmin-view без raw-контента.
- Любой новый export обязан проходить ту же no-raw-content проверку §3.

### 8.6 Aggregated cross-tenant privacy

RLS-safe cross-tenant architecture является prerequisite, а не текущей
возможностью ORM. Допустимы только: (а) tenant-by-tenant deidentified
materialization под обычным tenant-scoped runtime role; либо (б) отдельно
аудированная aggregate function/view, возвращающая только cohort-safe
агрегаты. Прямые cross-tenant ORM reads, сериализация `project_request`/
`project_event` rows и использование `BYPASSRLS` запрещены. Новый aggregate
контракт обязан доказать, что ответ содержит только enums, counts, durations,
safe versions и reason codes, без fingerprints и row-level identifiers.

---

## 9. Поэтапная реализация (без изменений кода в этой задаче)

Нумерация шагов продолжает родительский план (шаги 1–5 частично выполнены).
Каждый шаг проходит root review diff и независимую проверку.

### Шаг A. Причина отклонения (reason codes) в apply/reject контуре

- **Файлы:** `apps/api/app/modules/editor_assistant/preview_use_case.py`
  (запись `rejected` через `EditorRequestService.record_event` с
  `metadata={"reason_code": ...}`); proposal: расширенный apply/reject
  endpoint в `router.py` (сейчас apply-эндпоинта нет — только preview);
  `apps/web/src/lib/editorAssistant.ts` + UI-панель шага 5.
- **Таблицы:** без изменений; метаданные события уже принимают `reason_code`.
- **Тесты:** `test_editor_assistant_telemetry.py` (reject с reason code и без,
  reject с невалидным кодом → `EditorMetadataValidationError`);
  `test_editor_assistant_http_schemas.py` (DTO не принимает свободный текст
  причины).
- **Gate:** reject без причины и с причиной оба фиксируются; invalid code
  отклонён; в ответе API нет новых строк свободного текста.

### Шаг B. Tenant-level analytics projection (read-only)

- **Файлы:** proposal: `apps/api/app/modules/editor_assistant/analytics.py`
  (функции агрегата поверх `project_request`/`project_event`);
  `service.py` (`build_analytics_projection` уже существует — добавить
  per-tenant summary read-only endpoint в `router.py`).
- **Таблицы:** только чтение существующих трёх.
- **Тесты:** агрегат не содержит ни одного поля вне allowlist; повторный
  вызов идемпотентен; RLS-тест cross-tenant на чтение summary.
- **Gate:** методолог видит только свой tenant; ответ API сериализуем без
  инструкций и текстов вопросов.

### Шаг C. Cross-tenant aggregate для superadmin

- **Файлы:** proposal: новый bounded read-only service (по образцу
  superadmin operational console), `/admin/super/operations`-контур;
  возможна additive-таблица `ai_editor_analytics_daily` (tenant_id,
  день, intent, версии, counters) с полным набором §8.1 — только если
  on-the-fly агрегат слишком тяжёл.
- **Архитектурный prerequisite:** tenant-by-tenant deidentified materialization
  либо audited aggregate function/view с cohort-safe output; direct ORM
  cross-tenant reads и `BYPASSRLS` запрещены.
- **Тесты:** cohort gate (n < 10 → «недостаточно данных»); cross-tenant тест;
  тест на отсутствие tenant names в ответе.
- **Gate:** superadmin-агрегат не раскрывает tenant identity ниже порога
  §6.5; RLS/привилегии любой новой таблицы полные.

### Шаг D. UX reason codes и «что было не так»

- **Файлы:** proposal: панель ассистента (`apps/web`), использование
  `_ISSUE_MESSAGES` каталога для RU-подписей; i18n ru/kk/en.
- **Тесты:** frontend — reject flow без причины, с причиной, с issue-labels;
  отсутствие свободного текстового поля в analytics-DTO.
- **Gate:** вне-скрытие: незаполненная причина не блокирует reject.

### Шаг E. Отчёт метрик и tuning-обзор

- **Файлы:** proposal: read-only отчёт §6 (серверная агрегация), документация
  метрик в `docs/PROJECT_INTERNAL_DOCUMENTATION.md` после реализации.
- **Тесты:** детерминированный пересчёт метрик на фикстурах; regression на
  стабильность определения кластеров §6.6.
- **Gate:** все определения метрик воспроизводимы из кода; ручная проверка
  отсутствия raw-контента в каждом отчёте.

---

## 10. Детерминированные acceptance gates и таблица claims

### 10.1 Gates (проверяются при реализации каждого шага)

1. `validate_event_metadata` остаётся единственной точкой валидации метаданных;
   ни один новый ключ не добавлен без обновления allowlist и теста.
2. Cross-tenant ответ содержит только: enum-значения закрытой таксономии,
   counts, durations, safe versions и reason codes. Fingerprints, request/
   payload/instruction hashes, event/request/target/actor IDs и любые row-level
   opaque identifiers запрещены.
3. Cross-tenant тест RLS: анонимный/чужой runtime role не видит рядов другого
   tenant; композитный FK не позволяет attach события к чужому запросу.
4. Runtime role privileges: события append-only (UPDATE/DELETE не выданы).
5. UX: reject без причины работает; reason codes — только enum.
6. Отчёты: агрегат при n < 10 не выдаётся (cross-tenant), tenant-summary
   содержит только собственные данные.
7. Migration-файлы `0135`–`0137` остаются source references; runtime
   `alembic heads` и применённое состояние миграций **NOT VERIFIED**. Новые
   миграции должны быть additive.
8. Ни raw instruction, ни provider output не появляются в логах/ответах
   (расширение существующего теста на «absence of raw instruction text from
   analytics and log surfaces»).
9. Frontend typecheck/build не содержат нового свободного текста в
   analytics-полях.

### 10.2 Таблица claims

| # | Утверждение | Статус | Обоснование |
|---|---|---|---|
| 1 | Lifecycle-таблицы и allowlist-валидация метаданных существуют и tenant-scoped | VERIFIED | прямое чтение `models.py`, `analytics.py` и migration-файлов `0135`–`0137`; runtime `alembic heads` и применённое состояние миграций не заявляются |
| 2 | `project_request` возвращает только `intent_category` и `outcome_state` | VERIFIED | `analytics.py:153-158`, `REQUEST_ANALYTICS_FIELDS` |
| 3 | Таксономии intent/issue/reason/lifecycle соответствуют миграции `0135` CHECK-констрейнтам | VERIFIED | `taxonomy.py` vs `0135` `INTENT_VALUES`/`EVENT_TYPE_VALUES` |
| 4 | Preview-эндпоинт `POST /{quiz_id}/questions/{question_id}/assistant/preview` подключён через `quizzes/router.py` | VERIFIED | импорт `editor_assistant.router` в `quizzes/router.py:16,47` |
| 5 | Apply/reject HTTP-эндпоинт с reason codes отсутствует | VERIFIED | `router.py` содержит только preview; `EditorAssistantApplyRequest` не используется ни одним роутом |
| 6 | Метрики §6 вычислимы из существующих persisted данных | NOT VERIFIED | сейчас подтверждено wiring только `requested`; остальные emissions, aggregate-input projection, `validation_status`, locale/source taxonomy и target clustering — proposal |
| 7 | UX-каталоги RU-подписей reason codes соответствуют финальному UI | NOT VERIFIED | подписи §5.2 — proposal; UI шага 5 не реализован |
| 8 | Cohort-порог n ≥ 10 достаточно против деанонимизации | NOT VERIFIED | продуктовая гипотеза, требует пересмотра при росте нагрузки |
| 9 | Performance on-the-fly агрегатов достаточна без материализованной таблицы | NOT VERIFIED | решение за шагом C; сначала измерение |
| 10 | Существующие contract/coordinator/use-case/application тесты остаются зелёными после шагов A–E | NOT VERIFIED | test counts и green runtime status не заявляются; прогон тестов не входил в эту документную задачу |

### 10.3 Проверка перед следующим шагом

Перед реализацией любого шага этого плана перечитать: корневой `ERRORS.md`
(SECURITY-011 — PII в логах; TENANT-001 — RLS под runtime role; TEST-001/002 —
mock-запрет для mutation/RLS-доказательств), родительский план и текущее
состояние `apps/api/app/modules/editor_assistant/`. Любое расхождение плана с
фактическим кодом фиксируется обновлением этого документа, а не обходит
документ.
