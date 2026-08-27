# Защита работающих блоков и критических пользовательских сценариев

Практическое дополнение к документу
[«Система управления разработкой проекта с AI-агентами»](agent-project-development-governance-guide-ru.md).

Версия: 1.0  
Дата: 2026-08-27  
Статус: переносимый пример, который следует адаптировать к рискам и масштабу конкретного проекта

---

## 1. Зачем нужен отдельный слой защиты

Обычные unit-тесты хорошо проверяют отдельные функции, но не всегда защищают уже
работающий пользовательский сценарий целиком. Один агент может изменить миграцию,
другой - поиск данных, третий - формат результата. Каждый локальный тест останется
зелёным, а пользователь больше не сможет выполнить исходную задачу.

Типовые примеры таких регрессий:

- файл загружается, но больше не находится поиском;
- заказ создаётся, но уведомление не отправляется;
- сотрудник добавляется, но не может войти;
- платёж проходит у провайдера, но не отражается в продукте;
- курс генерируется, но уроки или тесты не сохраняются;
- миграция создаёт таблицу, но runtime-роль не получает необходимые права;
- API возвращает `200`, хотя бизнес-результат не появился;
- нормальное пересечение данных ошибочно считается конфликтом;
- новая версия данных записана, но чтение продолжает использовать старую.

Проблема не всегда состоит в недостатке тестов. Часто отсутствует явная связь
между пользовательским результатом, участвующими модулями и обязательными
проверками. Эта инструкция предлагает сделать такую связь машиночитаемой.

---

## 2. Основная модель

Для наиболее важных процессов проект хранит реестр **критических пользовательских
сценариев**. Каждый сценарий описывает:

1. Какой результат получает пользователь.
2. Какие компоненты участвуют в его формировании.
3. Какие изменения могут повлиять на результат.
4. Какие тесты подтверждают весь путь и его стыки.
5. Какие runtime или provider gates нужны дополнительно.
6. Какой evidence считается достаточным.

Архитектурный граф помогает найти связи, но не заменяет этот контракт. Полезная
комбинация выглядит так:

```text
Graphify или другой граф
        |
        v
Навигация и impact analysis
        |
        v
Машиночитаемый critical-journey contract
        |
        v
Impact resolver
        |
        v
Обязательные seam/integration/business-flow tests
        |
        v
Fail-closed CI gate
```

Graph показывает возможное влияние. Контракт определяет обязательства проекта.
Тесты доказывают поведение конкретной revision. Runtime readback подтверждает
фактически развёрнутую систему.

---

## 3. Термины

| Термин | Практическое значение |
|---|---|
| Critical journey | Важная задача пользователя от входа до наблюдаемого результата |
| Trigger path | Файл или каталог, изменение которого может затронуть journey |
| Seam | Стык модулей, форматов, ролей, транзакций или внешних систем |
| Invariant | Условие, которое должно оставаться истинным после любых изменений |
| Impact resolver | Скрипт, связывающий изменённые файлы с journeys и тестами |
| Fail-closed gate | Проверка, которая блокирует CI при повреждённом или неполном контракте |
| Business smoke | Минимальная проверка результата глазами пользователя или API-клиента |
| Evidence | Наблюдаемое подтверждение, а не предположение или старый отчёт |

Не каждый проект обязан использовать эти названия. Важно сохранить разделение
между навигацией, обязательством, тестом и runtime-доказательством.

---

## 4. Какие сценарии стоит считать критическими

Не нужно регистрировать каждую кнопку. Реестр оправдан, если поломка процесса:

- блокирует основную ценность продукта;
- затрагивает деньги, доступ, безопасность или юридическое доказательство;
- пересекает несколько модулей или сервисов;
- зависит от миграций, очередей, workers или внешнего провайдера;
- уже ломалась из-за изменения связанного компонента;
- трудно обнаруживается обычным unit-тестом;
- создаёт дорогое ручное восстановление;
- может остаться незамеченной до обращения клиента.

В типичном SaaS первыми кандидатами могут быть:

| ID | Пользовательский результат |
|---|---|
| `AUTH-01` | Новый пользователь получает доступ и успешно входит |
| `BILLING-01` | Оплата подтверждается и меняет доступ ровно один раз |
| `ORDER-01` | Заказ создан, обработан и виден клиенту |
| `IMPORT-01` | Файл импортирован, данные подтверждены и доступны в интерфейсе |
| `NOTIFY-01` | Бизнес-событие создаёт одно корректное уведомление |
| `REPORT-01` | Отчёт сформирован из актуальных tenant-safe данных |
| `AI-01` | Источники обработаны, результат AI сохранён и пригоден пользователю |

Начинать разумно с трёх-пяти процессов с наибольшим риском, а не с попытки сразу
описать весь продукт.

---

## 5. Рекомендуемая структура файлов

Один из возможных вариантов:

```text
project/
|-- AGENTS.md
|-- docs/
|   `-- critical-journeys/
|       |-- auth-user-access.json
|       |-- order-fulfillment.json
|       `-- ai-document-result.json
|-- scripts/
|   `-- ci/
|       |-- critical_journey_gate.py
|       `-- test_critical_journey_gate.py
|-- tests/
|   |-- unit/
|   |-- integration/
|   `-- journeys/
`-- .github/workflows/ci.yml
```

JSON не является единственным вариантом. YAML удобнее для ручного чтения, а
типизированный Python/TypeScript manifest может лучше подходить отдельному стеку.
Основные требования:

- формат однозначно валидируется;
- CI может прочитать контракт без LLM;
- ссылки на тесты и gates проверяются автоматически;
- изменение контракта видно в Git diff;
- неизвестное или неполное состояние приводит к ошибке, а не к тихому пропуску.

---

## 6. Шаблон машиночитаемого контракта

Ниже приведён пример, а не универсальная схема:

```json
{
  "schema_version": 1,
  "journey_id": "ORDER-01",
  "title": "Покупатель оформляет и получает заказ",
  "user_outcome": "Подтверждённый заказ сохранён, обработан и доступен покупателю",
  "risk": "critical",
  "trigger_paths": [
    "src/orders/**",
    "src/payments/**",
    "src/notifications/**",
    "migrations/**",
    "workers/order_worker.*"
  ],
  "required_tests": [
    "tests/journeys/test_order_checkout.py::test_checkout_persists_complete_order",
    "tests/integration/test_payment_idempotency.py::test_replayed_callback_is_idempotent",
    "tests/integration/test_order_worker.py::test_worker_completes_order_once"
  ],
  "runtime_gates": [
    "scripts/ci/order_schema_contract.py"
  ],
  "invariants": [
    "one provider event changes order state at most once",
    "order and payment belong to the same tenant",
    "success is reported only after durable persistence",
    "notification failure does not erase the committed order"
  ],
  "evidence_contract": {
    "source": "tests pass for the exact commit",
    "provider": "payment test event has a persisted provider id",
    "runtime": "created order is read back through the public application boundary"
  },
  "owner": "orders-domain",
  "reviewers": ["payments-domain"],
  "cleanup": "remove synthetic order and verify no pending worker job"
}
```

### Минимально обязательные поля

| Поле | Назначение |
|---|---|
| `journey_id` | Стабильный идентификатор для CI, ошибок и ADR |
| `user_outcome` | Наблюдаемый результат, а не название функции |
| `trigger_paths` | Граница автоматического impact analysis |
| `required_tests` | Точные исполняемые проверки |
| `invariants` | Условия, которые нельзя потерять при рефакторинге |

Поля `runtime_gates`, `owner`, `cleanup` и evidence contract особенно полезны для
production-систем, но могут быть избыточны для небольшой локальной библиотеки.

---

## 7. Как использовать Graphify

Graphify полезен до широкого чтения исходников и до формирования trigger paths.
Общий порядок может быть таким:

1. Найти entry point пользовательского действия.
2. Запросить контекст вызовов для route, handler, service или command.
3. Построить путь до модели, worker, adapter или persistence-функции.
4. Объяснить узлы, в которых меняются формат, tenant context или транзакция.
5. Найти существующие тесты для каждого важного seam.
6. Подтвердить найденные связи в исходниках, миграциях и тестах.
7. После изменения обновить граф проектным стандартным способом.

Конкретный CLI зависит от версии Graphify. Примерный набор операций:

```powershell
graphify query <symbol> --context calls --budget 1200
graphify explain <symbol>
graphify path <source-symbol> <target-symbol>
graphify update . --code-only --no-viz
```

### Что Graphify подтверждает

- символ существует в проиндексированном коде;
- между узлами найдена статическая связь;
- изменение потенциально затрагивает соседние компоненты;
- есть удобная точка для узкого чтения исходников.

### Что Graphify не подтверждает

- какой commit реально развёрнут;
- выполнилась ли миграция;
- есть ли у runtime-роли доступ;
- прошла ли транзакция;
- обработал ли worker сообщение;
- сохранился ли бизнес-результат;
- работает ли внешний провайдер;
- соответствует ли старый task status текущему состоянию.

Если граф устарел или parser не распознал файл, это нужно фиксировать как extraction
gap. Нельзя превращать отсутствие узла в доказательство отсутствия функции.

---

## 8. Impact resolver

Impact resolver должен быть маленьким deterministic-скриптом. Его задача:

1. Получить список изменённых файлов.
2. Загрузить и провалидировать все journey contracts.
3. Сопоставить пути с `trigger_paths`.
4. Собрать уникальный список обязательных тестов и runtime gates.
5. Проверить, что каждый указанный файл и test selector существуют.
6. Вернуть машиночитаемый результат для CI.

Пример результата:

```json
{
  "status": "READY",
  "journeys": ["ORDER-01", "NOTIFY-01"],
  "required_tests": 7,
  "runtime_gates": ["scripts/ci/order_schema_contract.py"]
}
```

### Fail-closed условия

Gate должен завершаться ошибкой, если:

- JSON/YAML повреждён;
- ID дублируется;
- обязательное поле отсутствует;
- trigger pattern некорректен;
- test selector указывает на отсутствующий тест;
- runtime gate удалён или переименован;
- изменён потенциально опасный путь, который не принадлежит ни одному journey;
- сам resolver изменён, но его собственные тесты не прошли.

Последнее условие с непокрытым путём стоит вводить постепенно. В зрелом проекте оно
полезно, но при первом внедрении может создать слишком много ложных блокировок.

---

## 9. Какие тесты нужны для одного journey

Хорошая матрица обычно содержит несколько уровней:

| Уровень | Что проверяет |
|---|---|
| Unit | Чистые преобразования, validation и локальные правила |
| Contract | Формат данных между модулями или внешними adapters |
| Seam | Стык source revision, transaction, role, queue или serializer |
| Integration | Реальную БД, очередь, storage или test provider |
| Journey | Полный пользовательский результат через публичную границу |
| Runtime smoke | Exact deployed revision и минимальный synthetic результат |

Не каждый commit должен запускать production smoke. Но каждый связанный commit
должен пройти детерминированные проверки, достаточные для своего слоя.

### Важный принцип

Проверять следует не только успешный ответ, но и durable outcome.

Слабая проверка:

```python
assert response.status_code == 200
```

Более сильная проверка:

```python
assert response.status_code == 201
order = repository.get(response.json()["id"])
assert order.status == "confirmed"
assert order.tenant_id == synthetic_tenant.id
assert payment.order_id == order.id
assert outbox.count(event="order_confirmed", object_id=order.id) == 1
```

Для AI-сценария дополнительно может потребоваться проверка структуры результата,
языка, ссылок на источники, количества сохранённых дочерних объектов и отсутствия
подмены tenant context.

---

## 10. Проверка стыков

Чаще всего регрессия возникает не внутри функции, а на границе двух решений.
Особое внимание полезно уделять следующим seams:

| Seam | Что может сломаться |
|---|---|
| Исходный файл -> нормализованный текст | Потеря идентичности версии источника |
| API -> service | Несовпадение optional/default полей |
| Service -> DB | Транзакция не фиксирует все дочерние объекты |
| Migration -> runtime role | Таблица есть, но приложение не может читать её |
| DB -> queue | Запись создана, событие потеряно |
| Queue -> worker | Повтор создаёт дубликаты |
| Provider -> callback | Callback меняет объект больше одного раза |
| UI -> API | Интерфейс сообщает успех до подтверждённой записи |
| Locale -> generated content | Результат появляется на другом языке |
| Active revision -> retrieval | Поиск читает устаревшие данные |

Для каждого критического seam желательно иметь хотя бы один тест, который падает
при реальном нарушении контракта.

---

## 11. Включение в CI

Пример логики pipeline:

```text
1. Validate journey manifests
2. Resolve impacted journeys from Git diff
3. Run resolver self-tests
4. Start required infrastructure
5. Apply migrations
6. Run required test selectors
7. Run runtime/schema contract scripts
8. Publish compact evidence summary
```

Пример условного job:

```yaml
- name: Resolve critical journeys
  run: python scripts/ci/critical_journey_gate.py --base "$BASE_SHA"

- name: Run impacted journey tests
  run: python scripts/ci/critical_journey_gate.py --base "$BASE_SHA" --run-tests
```

В реальном проекте безопаснее передавать сформированный список тестов в test runner
без shell interpolation либо использовать заранее валидированные selectors.

### Что не стоит делать

- запускать только тест изменённого файла;
- разрешать отсутствующий manifest как `warning`;
- молча пропускать DB-тест при недоступной БД;
- менять тест так, чтобы он повторял ошибочное новое поведение;
- считать общий зелёный CI доказательством production runtime;
- объединять migration, deployment и business smoke в один непрозрачный статус.

---

## 12. Дополнение для `AGENTS.md`

Ниже приведён переносимый фрагмент. Его следует сократить под конкретный проект.

```markdown
## Critical user journeys

- Before editing a critical path, query the architecture graph and identify all
  affected journeys, seams, migrations, roles, workers and external adapters.
- Treat Graphify as navigation and impact evidence, not runtime truth.
- Read the machine-readable journey contracts under `docs/critical-journeys/`.
- Changes matching a journey trigger must preserve every listed invariant and
  run every required test and gate.
- Do not weaken, delete, skip or rewrite a required test merely to accept new
  behavior. A changed invariant requires an explicit reviewed contract change.
- A successful function return or HTTP status is not enough. Verify the durable
  user-visible result and required child objects.
- New cross-module critical flows should receive a stable journey ID, trigger
  paths, seam tests, evidence contract and cleanup rule.
- After code changes, update the project graph using the repository-standard
  command and report extraction gaps honestly.
```

Этот блок не заменяет test commands, domain documentation или release runbook. Он
задаёт поведение агента, а исполняемые гарантии остаются в CI.

---

## 13. Рабочий порядок для агента

### До изменения

1. Прочитать применимые `AGENTS.md` и релевантные записи `ERRORS.md`.
2. Зафиксировать scope, branch, HEAD и dirty state.
3. Выполнить Graphify query/path/explain для entry point и ключевых seams.
4. Найти затронутые journey IDs через resolver.
5. Прочитать точные contracts, tests, migrations и source boundaries.
6. Составить минимальный список изменяемых файлов.
7. Определить, какие проверки должны стать красными до исправления.

### Во время изменения

1. Сохранять один writer на путь.
2. Не менять несвязанные контракты и тесты.
3. Отделять изменение intended behavior от исправления реализации.
4. Добавлять тест на подтверждённый root cause, а не на текст ошибки.
5. Не использовать production как экспериментальную тестовую среду.

### После изменения

1. Запустить resolver self-tests.
2. Запустить все тесты затронутых journeys.
3. Запустить proportional wider regression.
4. Обновить Graphify один раз проектным способом.
5. Проверить exact diff и отсутствие unrelated изменений.
6. Получить CI evidence для exact commit.
7. Выполнить runtime smoke только при необходимости и разрешении.
8. Удалить synthetic artifacts и подтвердить cleanup.

---

## 14. Как превращать инцидент в постоянную защиту

После регрессии полезно пройти следующий цикл:

```text
Симптом
  -> подтверждённый root cause
  -> минимальное исправление
  -> воспроизводящий regression test
  -> определение затронутого journey
  -> новый или обновлённый seam invariant
  -> CI enforcement
  -> запись в ERRORS.md только если причина может повториться
  -> skill только если остаётся повторяемая недетерминированная процедура
```

### Что куда переносить

| Наблюдение | Устойчивый артефакт |
|---|---|
| Ошибка в чистой функции | Unit test |
| Несовпадение форматов | Contract/seam test |
| Потеря DB privileges | Migration/schema gate |
| Повторяемый опасный workflow | Skill или runbook |
| Неправильный общий подход агента | Короткое правило в `AGENTS.md` |
| Подтверждённая повторяемая причина | `ERRORS.md` |
| Устойчивое архитектурное решение | ADR |
| Влияние нескольких модулей | Critical journey contract |

Не каждая ошибка заслуживает skill. Если защита может быть полностью
детерминированной, тест или CI gate обычно надёжнее инструкции на естественном
языке.

---

## 15. Review contract

Reviewer проверяет не только качество diff, но и сохранность journey:

- пользовательский результат сформулирован однозначно;
- trigger paths покрывают реальные точки изменения;
- Graphify findings подтверждены исходниками;
- для каждого важного seam есть проверка;
- тесты действительно падают при нарушении инварианта;
- тесты не закрепляют случайную внутреннюю реализацию;
- synthetic данные не содержат PII;
- миграции проверены на чистой и обновляемой схеме;
- runtime-role отличается от migration/admin role;
- retries и replay не создают дубликаты;
- cleanup проверен;
- provider evidence не выдан за runtime truth;
- production outcome относится к exact deployed revision.

Если reviewer не может подтвердить один слой, он маркирует его `NOT VERIFIED` или
`BLOCKED`, а не усиливает вывод на основании отчёта автора.

---

## 16. Версионирование контракта

Critical journey меняется только по двум причинам:

1. Intended behavior действительно изменён продуктовым или архитектурным решением.
2. Найден ранее неучтённый seam или invariant.

Изменение контракта должно быть видно отдельно от реализации. Полезный diff отвечает
на вопросы:

- какой пользовательский результат изменился;
- почему прежний invariant больше не подходит;
- какие тесты добавлены или заменены;
- кто подтвердил новое поведение;
- требуется ли миграция существующих данных;
- как проверяется backward compatibility;
- как откатывается неудачный выпуск.

Нельзя автоматически обновлять contract из текущего кода. Иначе ошибочная
реализация сама перепишет правило, которое должно было её остановить.

---

## 17. Antipatterns

### «Есть Graphify, значит связи защищены»

Граф помогает найти связь, но не запускает проверку и не доказывает runtime.

### «Полный test suite и так всё проверит»

Без явного manifest никто не знает, какой тест является обязательным и можно ли его
случайно удалить, переименовать или ослабить.

### «Добавим один большой end-to-end test»

Один непрозрачный тест медленно выполняется, трудно диагностируется и часто
пропускает seams. Лучше сочетать точечные seam tests с одним коротким journey test.

### «Любое изменение запускает вообще все проверки»

Это просто, но постепенно делает CI слишком медленным. Resolver позволяет сохранить
строгость без постоянного запуска нерелевантной инфраструктуры.

### «Ошибка доступа означает, что данных нет»

Это только `BLOCKED` или `NOT VERIFIED`. Отсутствие объекта требует успешного чтения
из правильного окружения.

### «Обновим тест под новый результат»

Сначала нужно подтвердить, что изменилось intended behavior. Иначе тест перестаёт
быть защитой и становится описанием регрессии.

### «Проверили на production, значит тесты не нужны»

Production smoke даёт важное evidence, но слишком поздно и дорого обнаруживает
ошибку. Он дополняет CI, а не заменяет его.

---

## 18. Поэтапное внедрение

### Этап 1. Один сценарий

- выбрать самый важный пользовательский результат;
- описать пять-десять trigger paths;
- связать существующие тесты;
- добавить один тест durable outcome;
- запускать contract вручную или отдельным CI job.

### Этап 2. Resolver

- автоматически читать Git diff;
- валидировать manifests;
- выводить impacted journeys;
- блокировать отсутствующие tests/gates;
- добавить self-tests resolver.

### Этап 3. Реальная инфраструктура CI

- запускать нужную версию БД и extensions;
- применять миграции;
- проверять runtime-role и ограничения;
- тестировать worker/replay/idempotency;
- публиковать компактный evidence summary.

### Этап 4. Governance

- закрепить правило в `AGENTS.md`;
- назначить domain owners;
- добавить review checklist;
- связать incidents с journey IDs;
- периодически удалять устаревшие или дублирующиеся contracts.

Необязательно сразу доходить до четвёртого этапа. Даже один хорошо выбранный
journey часто защищает продукт лучше, чем десятки несвязанных дополнительных тестов.

---

## 19. Минимальный starter kit

Для небольшого проекта достаточно:

```text
docs/critical-journeys/main-flow.json
scripts/ci/critical_journey_gate.py
scripts/ci/test_critical_journey_gate.py
tests/journeys/test_main_flow.py
```

Минимальные обязательства:

- один стабильный journey ID;
- один понятный user outcome;
- список trigger paths;
- хотя бы один seam test;
- хотя бы одна проверка durable outcome;
- CI, который падает при отсутствующем contract/test;
- короткое правило в `AGENTS.md`.

---

## 20. Чек-лист переноса в другой проект

### Проектирование

- [ ] Выбраны процессы с реальным бизнес-риском.
- [ ] Каждый journey сформулирован через результат пользователя.
- [ ] Назначены стабильные IDs.
- [ ] Определены seams и invariants.
- [ ] Graphify findings подтверждены исходниками.

### Реализация

- [ ] Manifests имеют проверяемую схему.
- [ ] Trigger paths соответствуют реальному codebase.
- [ ] Required selectors существуют.
- [ ] Resolver имеет собственные тесты.
- [ ] CI работает fail-closed.
- [ ] DB/provider dependencies запускаются до связанных тестов.

### Проверка качества

- [ ] Тест проверяет durable outcome, а не только статус ответа.
- [ ] Есть отрицательные и replay/idempotency проверки.
- [ ] Tenant/security boundaries проверяются отдельной ролью.
- [ ] Изменение intended behavior требует review contract.
- [ ] Runtime evidence относится к exact deployment.
- [ ] Synthetic artifacts полностью удаляются.

### Работа агентов

- [ ] `AGENTS.md` требует impact analysis до редактирования.
- [ ] Graphify не объявляется runtime truth.
- [ ] Запрещено ослаблять обязательный тест ради зелёного CI.
- [ ] Один writer владеет изменяемым scope.
- [ ] Reviewer проверяет journey целиком.
- [ ] Повторяемые причины превращаются в tests/gates, а не только в текст.

---

## 21. Итог

Graph engineering делает codebase понятнее агенту: помогает быстро находить entry
points, зависимости и возможный радиус изменения. Critical-journey contracts делают
эти связи обязательными для проекта. Tests и CI превращают обязательства в
исполняемую защиту. Runtime readback доказывает, что точная revision действительно
работает в целевом окружении.

Сильная схема состоит не из одного инструмента:

```text
Graph navigation
+ machine-readable journey contracts
+ seam and durable-outcome tests
+ fail-closed impact resolver
+ exact CI evidence
+ proportional runtime verification
= защита работающего пользовательского результата
```

Этот подход не гарантирует отсутствие всех ошибок. Он делает наиболее опасные
регрессии видимыми до выпуска и не позволяет отдельному агенту незаметно изменить
связанный блок без проверки всей цепочки.
