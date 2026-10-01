# AI-driven Камиля: пошаговый план методического рабочего места

Дата: 2026-10-01. Владелец продукта: пользователь; технический владелец: root.
Статус: первый текстовый vertical slice реализован за выключенными flags;
изолированный Supabase DEV gate PASS. Голос и новый workflow ещё не доступны
пользователям. Ветка: `feature/methodologist-workbench-20261001`.

## Результат для методиста

Методист прикладывает документ и говорит: «Сделай вводный курс для склада на
20 минут, включи тест и практические примеры». Камиля показывает понятое
поручение, задаёт только необходимые вопросы и создаёт **черновик**. Затем:
«Во втором уроке упрости формулировки, добавь пример приёмки товара» — показывает
изменения до/после. После проверки методист публикует и поручает: «Назначь этот
курс отделу склада до 16 октября». Камиля показывает точную версию курса,
отдел, текущих получателей, дату/часовой пояс и уведомления. После подтверждения
выдаёт фактический результат, а не сообщение модели «готово».

Первый релиз — помощник методиста, **не автономный администратор**. Ручные экраны
остаются. AI не получает права пользователя и не пишет напрямую в БД.
Успех измеряется всей цепочкой: источник → проверенный курс → назначение →
завершение → журнал/доказательства, а не количеством голосовых сообщений.

## Архитектура и голос

```text
Голос → распознавание → редактируемая расшифровка ┐
Текст + прикреплённые источники                 ├→ поручение → уточнения
                                               ┘
→ серверный план → предварительный просмотр → подтверждение точной версии
→ существующая доменная операция → проверенный результат / ошибка
```

DeepSeek отвечает за смысл, уточнения и предложение плана. В опубликованном
API сейчас описаны текст/изображения, но не аудиотранскрибация:
[Responses API](https://api-docs.deepseek.com/api/create-response/).
Поэтому распознавание речи — отдельный этап, а не обещание голосового DeepSeek.
Существующий выбор моделей/tenant settings этим планом не меняется.

Предварительный выбор для испытания: **faster-whisper**, реализация Whisper на
CTranslate2 с CPU/GPU и int8. Отдельная ограниченная очередь/процесс не должна
блокировать HTTP API и worker генерации. Это не требует нового микросервиса или
GPU-сервера до измерений. Источник:
[проект faster-whisper](https://github.com/SYSTRAN/faster-whisper).

| Вариант | Выгода | Ограничение | Решение сейчас |
|---|---|---|---|
| Local/KZ faster-whisper | Контроль маршрута аудио, нет обязательной платы за минуту | Нужны ресурсы, сопровождение, проверка качества RU/KK | Кандидат для benchmark, не установлен |
| Готовый STT API | Не нужно ставить модель; быстрее интеграция | Новая стоимость и передача аудио внешнему провайдеру | Только после отдельного согласования бюджета и данных |
| Распознавание браузером | Мало backend-работы | Различается по браузерам; обработка может быть внешней | Не canonical путь V1 |

[Whisper API](https://developers.openai.com/api/docs/models/whisper-1) —
размещённый сервис; его не нужно устанавливать. Это не то же самое, что локальные
веса Whisper. Название поддерживаемого языка не доказывает качество распознавания
казахских названий, смешанной речи, отрицаний и сроков.

### Gate выбора ASR

1. Подготовить 60–100 разрешённых коротких записей: русский, казахский,
   смешанная речь; тихо/шумно; 15–60 секунд; названия отделов/курсов, даты,
   «не назначай», исправления. Не брать реальные записи без права использования.
2. Сравнить multilingual `large-v3` и небольшой multilingual CPU/int8 baseline.
   Англоязычные distilled-модели не считать заменой RU/KK.
3. Измерить WER по языкам, точность критических полей, долю необходимых
   исправлений, p50/p95 времени после окончания записи, cold/warm startup,
   пиковые RAM/VRAM, поведение при параллельности и отмене.
4. Цели пилота: не менее 95% точности критических полей на утверждённом корпусе;
   ноль непоказанных ошибочных назначений; p95 ≤15 секунд для 30-секундной записи
   на выбранном оборудовании. Это **цели**, не измеренный результат.
5. Зафиксировать конкретные версию/веса/ресурсы/маршрут данных. Если CPU не
   проходит — отдельно выбрать доступное уже оплаченное оборудование либо
   согласовать стоимость нового ресурса/API. Не ставить тяжёлую модель на VM126
   без измеренного capacity gate. Не включать скрытый cloud fallback.

## Этапы и критерии выхода

Этапы выполняются по зависимости; benchmark голоса может идти параллельно
текстовому ядру. Каждый этап не означает отдельный production-релиз.
Номера ниже обозначают блоки, не обязательный линейный порядок: после 0–1
первый вертикальный срез объединяет 3 + 7 для уже опубликованного курса;
2 идёт параллельно при наличии разрешённого корпуса, затем добавляем 4–6,
и только собранная цепочка проходит 8–9.

| № | Что делаем | Проверяемый результат | Зависимости / gate |
|---|---|---|---|
| 0 | Инвентаризация, границы V1, контракты | Установлены владельцы и отличия разового назначения от постоянного правила | Выполнена инвентаризация исходного кода |
| 1 | Чистое ядро поручений и подтверждения | Модель не может передать tenant/actor/approval; изменение версии/получателей/срока обнуляет подтверждение | Локальные policy/contract tests; без БД, HTTP и LLM |
| 2 | Распознавание RU/KK | Отчёт benchmark и выбранный маршрут аудио; проверка ошибочных дат/названий | Разрешённый аудиокорпус и ресурсный gate выше |
| 3 | Текстовый разбор и единая панель | Один вход для текста/голоса/документа, редактируемая расшифровка, уточнения, карточки действий, отмена | Нужны fixtures разбора и session/tenant contract; модель через existing policy |
| 4 | Документ → черновик курса | Реальный generation job, прогресс/ошибка/отмена; курс остаётся draft | Source ownership/version, quota admission, idempotency, existing generation worker |
| 5 | Корректировка курса | Показ до/после, source references, применить только утверждённую правку; published content → новый draft | Editor preview пока не общий apply-контракт; требуется impact addendum |
| 6 | Проверка и публикация | Нельзя обойти expert/quiz review; подтверждена версия и все побочные назначения публикации | Fresh snapshot под course lock; existing approval policy сохраняется |
| 7 | Разовое назначение отделу | Точный department UUID, замороженный список текущих активных сотрудников, срок/часовой пояс, отсутствие дублей | Existing direct enrollment; не DepartmentCourse rule; transactional recheck и outbox |
| 8 | Интеграция всей цепочки | CJ-01…CJ-08, RLS, повторы/гонки/отмена/ошибки, mobile, фактические receipts | Supabase DEV, постоянный QA-контур; реальные AI/STT только в утверждённых лимитах |
| 9 | Ограниченный выпуск | DEV browser acceptance, затем разрешённый production candidate с exact SHA/readback и живым flow | Feature flag off по умолчанию, Test & Evidence Runner + Release Runner, root финальная приёмка |

### Детализация первого вертикального среза

Сначала текстовый сценарий «назначь **существующий опубликованный** курс
**существующему** отделу до точной даты». Он быстрее проверяет реальную пользу и
самые рискованные поля без ожидания ASR и долгой генерации.

- Intent содержит только просьбу; сервер ищет курс/отдел внутри активного tenant.
- При двух совпадениях задаёт выбор. Несуществующий отдел не создаёт сам.
- В текущем bounded slice поддерживается только точная дата DD.MM.YYYY/ISO и
  явно показанный IANA timezone. «В пятницу», «к концу месяца», отрицания и
  составные команды пока требуют переформулировки, а не угадываются. Позднее
  LLM resolver должен показывать интерпретацию относительной даты до подтверждения.
- Предварительный просмотр показывает версию курса, количество и список
  получателей, уже назначенных/исключённых, срок и режим уведомления.
- Кнопка подтверждает fingerprint этой версии плана. При изменении состава
  отдела, курса, роли или срока исполнение останавливается для нового preview.
- Plan/preview хранятся на сервере с владельцем и revision: endpoint принимает
  ссылку на уже показанный preview, а не клиентский PlanSnapshot. Resolver
  сохраняет tenant timezone и происхождение календарного срока; эта видимая
  интерпретация также входит в binding подтверждения при интеграции.
- Транзакция создаёт назначения через существующие правила доступа. Повтор
  запроса возвращает receipt, не вторые назначения. Outbox отдельно показывает
  queued/sent/failed; queued не означает доставлено.
- Повторная речевая фраза «назначь» не является доказательством подтверждения.
  В V1 финальные publication/mass assignment подтверждаются кнопкой.

После этого добавляются draft-generation и коррекции. Цепочка не атомарна:
созданный черновик сохраняется при сбое последующего назначения; completed
шаги не проигрываются заново. Каждый опасный шаг имеет свой актуальный preview.

## Технические gaps, которые закрываем до интеграции

| Найдено в исходном коде | Что нельзя предполагать | Следующий контракт |
|---|---|---|
| `/departments/{id}/courses` создаёт DepartmentCourse и recompute; legacy name path может auto-create | Это не разовое назначение | One-time server-resolved audience → direct enrollments |
| `/courses/{id}/publish` имеет course lock/idempotency; fingerprint ключа привязан к course_id | Это не подтверждение точного плана/версии | Expected snapshot check в той же транзакции + preview existing rule effects |
| Audience advisor предлагает scope и ссылки | Не исполняет назначения | Оставить read-only; workbench server resolver отдельно |
| Editor assistant имеет question preview/base snapshot | Не даёт общего voice-edit/apply курса | Бounded patch contract + applicability/review/new draft |
| AI jobs/cancel/resume уже существуют | Нет общего workbench receipt и dedup всей цепочки | Plan/execution ownership + existing job binding |

## Безопасность, стоимость и хранение

- Только active role `methodologist`, не объединение прав нескольких ролей.
  Tenant/actor задаёт сервер; все IDs проверяются, tenant-scoped запись требует
  RLS/FORCE RLS/runtime без BYPASSRLS и cross-tenant negative tests.
- Документ/аудио — недоверенные данные: содержащиеся в них «инструкции» не
  меняют permissions, tools, publish gates, системный prompt или tenant.
- Модель никогда не исполняет SQL, shell, произвольный HTTP, удаление либо
  изменение тарифов/провайдеров. Неподдерживаемый запрос явно отклоняется.
- Голос ограничен по длине/размеру, MIME и фактическому декодированию; silence,
  timeout и отказ ASR возвращают редактируемый текстовый fallback, не выдуманную
  команду. Предварительная продуктовая граница: 60 секунд/8 MiB.
- Raw audio по умолчанию не сохраняется после транскрибации. Если нужна очередь
  временного хранения, до её запуска принять exact TTL/deletion/recovery contract;
  никакого неопределённого хранения. Не логировать аудио/текст/документы/PII.
- Долговечные plans/receipts принадлежат workbench. Migration0169 и ограниченный
  execution contract приняты root для реализации/изолированной проверки;
  public DEV/production migration ещё не выполнена. Retention/TTL metadata и
  scheduled cleanup остаются обязательным gate перед включением функции.
- Существующие AI quotas и provider policies не обходятся. Нужен reserve/settle
  usage для новых вызовов с лимитами/retry/cancellation, не unlimited chat.
- Новая стоимость, внешний маршрут данных, платный ресурс, провайдерный fallback
  и production release требуют отдельного точного решения владельца. Сам план
  не даёт такого разрешения.

## Проверки, исполнители и остановки

Root владеет общими контрактами, миграциями, интеграцией и выпуском. Дешёвые
leaf-агенты получают инвентаризацию, fixtures, узкие UI/test/review задачи с
непересекающимися write scopes; максимум два одновременно. Между агентами —
English-only handoff: result / changed / verified / blockers / next.

Test & Evidence Runner: точный принятый test packet и sanitized evidence;
не чинит приложение в ходе приёмки. Release Runner: сначала preflight exact
candidate, затем только отдельно разрешённый release packet; не включает billing
или provider changes. Root устраняет их подтверждённые blockers в рамках scope,
сам читает итоговые доказательства и завершает browser flow.

Локальный цикл: canonical pytest wrapper для owned tests + Ruff/Mypy через
canonical env; seam/neighbor regressions при подключении доменного модуля;
полная release suite один раз на candidate. DB — только canonical Supabase DEV,
не Docker PostgreSQL на этой машине. Производственная проверка — синтетический
QA-контур без изменения клиентских курсов/назначений.

Стоп: новый unlisted interface/data owner, неясное разрешение на аудио/стоимость,
непройденные tenant/RLS/idempotency gates, неучтённый side effect, stale plan,
capacity failure, расход за пределами лимита. Не «обходить» это агентом.

Откат: выключить workbench feature flag; ручной LMS остаётся рабочим. Не удалять
созданные/завершённые курсы, назначения и историю. Expand-only миграции и точный
операционный rollback принимаются до соответствующего release.

## Текущий progress и следующие действия

1. Source inventory и scope: выполнены.
2. Формальные документы: [epic](../product/contract-modules/methodologist-workbench/EPIC_V1.md)
   и [index](../product/contract-modules/methodologist-workbench/MODULE_INDEX.md).
3. Чистое contract foundation: реализовано в
   `apps/api/app/modules/methodologist_workbench/plan_contract.py`.
   Canonical pytest wrapper: **76 PASS**; owned Ruff: PASS; owned Mypy:
   **2 source files PASS**; canonical quality baseline: PASS, новой debt нет.
   Независимый read-only cheap-agent review: подтверждённых дефектов нет.
   Это pure policy/contract fixtures, не HTTP/БД/LLM/STT/browser/production
   acceptance. Runtime-доступность новой функции этими проверками не доказана.
   AST Graphify update выполнен один раз и остановлен shrink guard:
   новый граф 21628 nodes против прежних 23077; force/rebuild не применялись,
   старый индекс сохранён. Это навигационный пробел, не PASS графа. Ограниченная
   AST-проверка нового модуля подтвердила только standard library/Pydantic imports,
   без доменных/сетевых зависимостей; expected foundation map соблюдён по source.
4. Первый execution slice реализован по
   [assignment addendum](../product/contract-modules/methodologist-workbench/contracts/ASSIGNMENT_EXECUTION_ADDENDUM_V1.md):
   bounded parser, tenant-local resolver, immutable stored preview, transactional
   receipt, API и отдельная панель `/methodologist-workbench` без изменения меню.
   Оба flags выключены; VERSION/runtime0.11.25 не изменён. Это ещё не общий AI/NLU.
   Canonical pytest: **138 PASS** (123 owned/foundation +15 neighbor fixtures);
   owned Ruff и canonical Python baseline PASS, новой quality debt нет.
   Web targeted **10 tests PASS**, lint/typecheck PASS; UI tests не browser acceptance.
5. `scripts/ops/workbench_assignment_dev_gate.py --env-file <canonical .env> --execute`:
   **RUNTIME-DERIVED PASS**, non-BYPASS `lms_app`, isolated owned schema only.
   Upgrade0169 + ENABLE/FORCE RLS; cross-tenant/other-actor reads hidden;
   immutable snapshot UPDATE и ordinary DELETE denied; rollback совместно
   отменяет receipt/enrollment/access policy; два конкурентных подтверждения
   одного плана дают один receipt/назначение; replay после expiry без дублей;
   notify=false не создаёт dispatch; изменение membership блокирует исполнение.
   Owned schema удалена и отсутствие независимо прочитано; public revision и
   table inventory до/после совпали. Это не проверка полного public data digest
   или production RLS всех соседних таблиц: baseline copies не копируют их RLS.
   Начальные failures сохранены как результаты проверки: import config без dotenv,
   невалидный normalized_name fixture, затем PostgreSQL0A000 на eager outer join
   Position.department_obj. Исправление — `FOR UPDATE OF positions`; SQL regression
   добавлен, новый реальный gate PASS. Ни один failed run не заменён заявлением PASS;
   во всех completed gate runs cleanup/public schema inventory checks PASS.
6. Independent cheap-agent source review: дополнительных high-impact дефектов
   не найдено; root отдельно исправил повторный notification dispatch, session
   leakage/stale choices и реальную DB lock ошибку. Reviewer static evidence не
   подменяет RUNTIME-DERIVED gate выше.
7. Graphify AST update после изменения связей снова остановлен shrink guard:
   21765 против23077 nodes. Старый graph сохранён, force/rebuild не выполнены;
   source fallback подтверждает ожидаемые imports; extraction gap остаётся.
8. Второй slice принят по
   [reload/validation addendum](../product/contract-modules/methodologist-workbench/contracts/ASSIGNMENT_RELOAD_VALIDATION_ADDENDUM_V1.md):
   `?plan=<UUID>` восстанавливает preview/receipt через authenticated GET, не POST.
   URL содержит только locator, не authority/PII; сервер повторно проверяет owner.
   Подтверждение сохраняет URL для восстановления результата; новая команда или
   редактирование убирают locator. Серверные timezone/notify/scope сохраняются;
   исходная инструкция не реконструируется. StrictMode RED исправлен,18 UI tests,
   lint/typecheck PASS. Canonical API matrix160 PASS (добавлены gate safety и
   существующие outbox neighbors), quality baseline PASS.
9. Расширенный **RUNTIME-DERIVED DEV gate PASS**,24 checks: notify=true на
   synthetic активированном account, atomic outbox/receipt rollback и commit;
   один outbox, attempt_count0/status pending; replay без новых dispatch IDs;
   receipt GET; два разных плана дают одно исполнение и один stale;
   конкурирующее ручное назначение оставляет свой deadline и блокирует старый план.
   Public enqueue НЕ вызывается: body0097+0154 сверяется с live prosrc и только
   принятый body устанавливается в owned schema с fixed search_path/FORCE RLS.
   Runtime resolution owned, прямой app-role outbox SELECT denied. Нет delivery/
   recovery interfaces/worker dispatch; это не доказательство доставки писем.
   Cleanup/absence/public revision+table inventory neutrality PASS.
10. До DEV включения: metadata retention/cleanup contract, invitation/activation
   side effect gate, full neighbor RLS/organization mutation interleavings и
   полная browser acceptance постоянного QA-контура. Public DEV migration и
   release packet не выполнялись. Production остаётся отдельным exact gate.
11. Следующий кодовый шаг: закрыть эти gates; затем bounded LLM intent adapter через существующие provider/usage policy,
   после этого document→draft и безопасные corrections. Никаких новых paid resources.
12. ASR benchmark: NOT VERIFIED, аудиокорпус/выбранная capacity ещё отсутствуют.
13. AST update второго slice также остановлен shrink guard:21789 против23077
   nodes; старый graph сохранён, force/rebuild/upgrade не выполнены. Независимая
   локальная приёмка Test & Evidence Runner ожидает frozen candidate packet;
   root runtime gate не выдаётся за независимое выполнение Runner.

### Epic-update: ownership и зависимости

`WB-FOUNDATION -> WB-TEXT-EXEC -> WB-DEV-ACCEPT -> WB-RELEASE`

`WB-TEXT-EXEC -> WB-LLM-INTENT -> WB-DOCUMENT-DRAFT -> WB-CORRECTION`

`WB-ASR-BENCH -> WB-VOICE-INPUT` (отдельный resource/data gate)

| Node | State | Owner / writer / reviewer | Exit / next gate |
|---|---|---|---|
| WB-FOUNDATION | DONE | root / root / independent cheap reviewer |76 pure tests и quality PASS; commit5afa42f |
| WB-TEXT-EXEC | DONE | root; parser/UI cheap leaf writers; root + independent reviewer |138 API tests, web checks, isolated DB gate PASS; flags off |
| WB-DEV-ACCEPT | IN_PROGRESS | root; Test & Evidence Runner on exact accepted packet |Reload/activated-account outbox+manual overlap PASS; retention/activation/full-neighbor/browser still gated |
| WB-LLM-INTENT | NOT_STARTED | root shared contract; bounded leaf fixtures |Existing policy/quota binding; no new provider/spend authority |
| WB-ASR-BENCH | BLOCKED | root |Permitted corpus + measured already-paid capacity; no ASR installed |
| WB-RELEASE | NOT_STARTED | root + Release Runner |Exact accepted candidate, all preceding gates; no release authority inferred |

Write overlap: root owns migration/config/router/registry/purge/docs and DEV gate;
parser agent owns parser+owned tests, UI agent owns panel/client+web tests until
handoff. No concurrent writers to one file; no agents use secrets/external DB.
DEV mutation scope: one randomly named `workbench_<12hex>` schema with synthetic
rows; rollback/cleanup drops exactly that validated owned schema, never public.

Delegation task ledger (exposed token/time counters are NOT AVAILABLE, not zero):

| Task / type | Requested model / effort | Acceptance / correction rounds | Evidence |
|---|---|---|---|
| assignment_seam_inventory / read-only inventory + review |gpt-5.6-luna / medium; independently observed metadata NOT AVAILABLE |Accepted;0 correction rounds |Source-only findings, no external writes |
| assignment_text_parser / bounded implementation + review |gpt-5.6-luna / medium; observed metadata NOT AVAILABLE |Accepted;0 implementation correction rounds |24 parser tests; ownership transferred root |
| workbench_assignment_ui / UI+transport fixtures |gpt-5.6-luna / medium; observed metadata NOT AVAILABLE |Accepted after2 root correction packets, plus usability refinement |Targeted UI tests, lint/typecheck; no live browser claim |
| root / contracts+integration+DEV gate |Parent session; exact metadata NOT AVAILABLE |Atomicity/RLS/concurrency checks accepted after owned repairs |138 tests; isolated runtime gate PASS; elapsed/review/token counters NOT AVAILABLE |
| workbench_plan_reload / URL reload + fixtures |gpt-5.6-luna / medium; observed metadata NOT AVAILABLE |Accepted after1 correction packet; root StrictMode repair |16 leaf tests;18 after root regression; elapsed/token counters NOT AVAILABLE |
| root / second-slice integration |Parent session; observed metadata NOT AVAILABLE |Root review caught StrictMode cancellation bug, deterministic RED/GREEN |160 API /18 web /24 runtime checks PASS; notification delivery NOT VERIFIED |

Точные сроки оценим после вертикального среза и ASR benchmark; обещать голосовой
production за фиксированное число дней без этих измерений было бы неверно.
После полного выполнения плана его факты переносятся в durable contracts и
канонические эксплуатационные документы; временный план удаляется.
