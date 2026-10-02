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
  OWNER-CONFIRMED2026-10-01:15min validity, ready-plan delete24h after expiry,
  succeeded receipt90days from execution; [policy V1](../product/contract-modules/methodologist-workbench/contracts/RETENTION_POLICY_V1.md).
  Scheduled cleanup NOT_IMPLEMENTED; learning history never included.
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
10. На checkpoint второго slice до DEV включения оставались metadata retention/cleanup contract, invitation/activation
   side effect gate, full neighbor RLS/organization mutation interleavings и
   полная browser acceptance постоянного QA-контура. Public DEV migration и
   release packet не выполнялись. Production остаётся отдельным exact gate.
11. Следующий кодовый шаг: закрыть эти gates; затем bounded LLM intent adapter через существующие provider/usage policy,
   после этого document→draft и безопасные corrections. Никаких новых paid resources.
12. ASR benchmark: NOT VERIFIED, аудиокорпус/выбранная capacity ещё отсутствуют.
13. AST update второго slice также остановлен shrink guard:21789 против23077
   nodes; старый graph сохранён, force/rebuild/upgrade не выполнены.
14. Независимая локальная приёмка **Test & Evidence Runner PASS**, root review
   **ACCEPTED_LOCAL_ONLY**, candidate `7f82abd87f94e273b01da8b3c6ca1192470de079`.
   API160/web18 passed, failed0/skipped0; lint/typecheck и flags-off production
   build PASS (67 static pages). Run `WB-RELOAD-LOCAL-20261001-01`, evidence
   correction `-C1`: UTC recording time/root-review/counts уточнены append-only,
   без повторного запуска или source repair. [Ledger](../testing/TEST_RUN_LEDGER.md),
   sanitized local artifacts `.release-evidence/WB-RELOAD-LOCAL-20261001-01/local/`.
   Runtime/browser для Runner **NOT_RUN**; root DEV24 не является независимым
   runtime выполнением. Последующий closeout commit меняет только документацию.
15. Следующий bounded validation slice принят по
   [invitation addendum](../product/contract-modules/methodologist-workbench/contracts/ASSIGNMENT_INVITATION_VALIDATION_ADDENDUM_V1.md).
   Runtime application source не менялся. Root **RUNTIME-DERIVED DEV33 PASS**:
   preview warning без приглашения; notify=true готовит приглашение к исходному
   user_id; rollback атомарный; valid reuse, expired supersession и receipt replay
   без дублей; notify=false не готовит приглашение/outbox. Нет login activation,
   OTP/email/worker dispatch или нового пользователя; attempts0/pending.
   Добавлены только owned definitions user_invitations/tenant_settings, без строк.
   Все таблицы разрешаются в owned schema до application mutation; search_path
   `owned,pg_catalog` без public fallback. Cleanup/absence/public metadata neutrality PASS.
   3 guard tests RED→GREEN, focused API69/quality PASS, cheap independent source
   review без findings. Runtime artifact root:
   `.release-evidence/WB-INVITATION-20261001/dev/results.json`, unchanged committed
   script blob `7d579f7f7c7b8e335d1a726d5c729a74a7a529a6`.
16. Retention policy: owner question sent, values NOT_APPROVED; automatic deletion
   не включена. Full neighbor RLS/FK/trigger equivalence/org-change/browser и
   public migration всё ещё gated. Invitation gate доказывает preparation,
   НЕ acceptance/OTP/delivery. Graphify update21805 vs23077 stopped by shrink guard;
   old graph preserved, source fallback, no force/upgrade.
17. Test & Evidence Runner independently accepted local candidate
   `f547ab804dc8016a407fc113a5d924b14e98b405`:69 tests, failed0/skipped0,
   scoped Ruff PASS; source review без actionable findings, root review
   **ACCEPTED_LOCAL_ONLY**. Initial wrong non-unit selector was Runner invocation
   **HARNESS_FAILURE** (packet path was already correct); corrected command PASS.
   No source repair or unchanged UI/build rerun. DEV33 reconciled only as
   ROOT_EXECUTOR_REVIEW_ONLY, not independent runtime execution.
   Run `WB-INVITATION-LOCAL-20261001-01`; local report/results destination is
   `.release-evidence/WB-INVITATION-LOCAL-20261001-01/local/` (root accepted bounded
   destination amendment). Evidence-only C1 clarifies preview persists only plan,
   not invitations/domain assignments; prior ledger remains append-only.
18. Organization/isolation slice принят по
   [organization addendum](../product/contract-modules/methodologist-workbench/contracts/ASSIGNMENT_ORGANIZATION_ISOLATION_VALIDATION_ADDENDUM_V1.md).
   Application runtime source не менялся. Root **DEV42 PASS**: явный отдел
   сильнее position fallback; descendants только opt-in; чужой actor/tenant
   не читает и не подтверждает план; committed user move/position relocation/
   child reparent/new hire после preview вызывают stale без receipt/enrollment/
   access policy/invitation/outbox. Два runtime sessions: confirm действительно
   ожидает lock от конкретного mutator PID, затем committed move отклоняет план.
   Не заявляется serializable org predicate lock, future autoassign или проверка
   application cancellation. Owned schema удалена, отсутствие/public revision+
   table inventory neutrality PASS. Evidence:
   `.release-evidence/WB-ORG-ISOLATION-20261001/dev/results.json`, script blob
   `160f0325d505345355646a5bc7758e830246431d`.
19. Catalog-only DEV metadata **BLOCKED** для full neighbor acceptance:
   `user_invitations_public_pending_lookup` из0046 — unscoped pending SELECT,
   применяется к lms_app; tenants RLS enabled/FORCE false. Business rows не читались,
   API exploit/leak NOT VERIFIED; public policies/roles/migrations не менялись.
   Это не заменяется более строгой synthetic policy с заявлением equivalence.
   Требуется root impact amendment и auth/public-invitation compatibility contract
   перед локальным исправлением; public rollout отдельно gated. Retention owner
   choice, full FK/trigger proof и browser acceptance остаются открыты.
20. Root local **170 API tests PASS**, failed0/skipped0/1 existing warning;
   canonical quality baseline/scoped Ruff PASS; independent cheap review accepted
   после исправления неверной трактовки preview/guarded selection и coverage hire.
   Начальные попытки сохранены в `failures.json`: metadata internal-char false
   negative (retracted, explicit text cast), synthetic Position CHECK23514,
   root wrong selector/no tests, owned-test import-order issue. Corrected tests и
   actual DEV gate прошли; failures не переписаны в PASS. Test Runner local frozen
   candidate acceptance pending; unchanged UI/build не перезапускались.
   Graphify AST update21822 vs23077 остановлен shrink guard; старый index
   сохранён, source fallback, без force/upgrade. Это extraction gap, не FAIL gate.
21. Test & Evidence Runner independently **PASS** on frozen candidate
   `0355bd626613b0099192667dbf2085ea17ed92b8`:170 passed/failed0/skipped0,
   scoped Ruff PASS, exact source review no findings. Root inspected report/JSON,
   append-only ledger delta, unchanged source/blob and accepts **ACCEPTED_LOCAL_ONLY**.
   Run `WB-ORG-ISOLATION-LOCAL-20261001-01`, duration207.559s, evidence
   `.release-evidence/WB-ORG-ISOLATION-LOCAL-20261001-01/local/`.
   Original PENDING reports retained verbatim; later root-acceptance.json and
   append-only root C1 record disposition without repeated tests or source repair.
   DEV42 remains ROOT_EXECUTOR_REVIEW_ONLY; metadata neighbor gate BLOCKED;
   no public migration, browser, mail, AI/audio or flags enablement. Next root task:
   bounded compatibility contract and local negative DB proof for invitation RLS;
   existing token-based anonymous access must remain valid, no silent bypass.
22. Owner explicitly approved invitation isolation remediation ("делай"); root
   accepted [impact V1](../product/contract-modules/methodologist-workbench/contracts/INVITATION_TOKEN_RLS_IMPACT_ADDENDUM_V1.md)
   before users/migration edits. Local0170 drops broad0046 and installs exact-token
   SELECT TO lms_app with empty tenant guard; no status predicate, preserving intended
   public terminal reasons. Shared private lookup binds token parameter locally,
   selects exact equality, clears scope before existing tenant setup; get_db rollback
   remains SQL-error cleanup. Kiosk0119 precedent/source verified, no new definer/bypass.
   Root **synthetic DEV12 PASS**, source0042 policy + forced RLS: original foreign
   pending/anonymous enumeration reproduced, patched absence/wrong/case/space/injection
   token and cross-tenant negatives PASS, including foreign token in authenticated
   context; exact token all5statuses, anonymous INSERT/UPDATE/DELETE denied, own UPDATE
   preserved, same-connection commit/rollback cleanup, actual public view/rejection
   helper PASS. Owned schema removed/public revision+table inventory neutral.
   Managed security collection for this target: `artifacts/validation_artifacts/invitation-token-rls-dev.json`,
   SHA256`c947a5e2abb4d6b9ba3c083749fe6f6b7a4f7a21a309d083c302542729203e0f`.
   Script blob`c1421897a23572091a9c9aab4daf4d55ad6cd9f1`; app blob`2955002376c37b195a5e4f1acd6d0b04dc12cd3b`;
   migration blob`30e2026ef8e34f49f9ca6775b3a75578bfb3fc57`. Retained proof follows
   Codex Security managed artifact storage; no new parallel repository security report.
23. Root local212 tests PASS/failed0/skipped0/4 existing warnings; canonical quality
   and scoped Ruff PASS. Three new seam tests RED before implementation; nearest
   activation mocks initially48passed2failed then49passed1failed; semantic selector
   typo211passed1failed. Corrected exact test setup/selector, assertions not weakened.
   Fresh read-only investigator/bypass reviewer no remaining findings. Graphify
   update21853 vs23077 shrink-guard blocked; source fallback, old index preserved,
   no force/upgrade. Independent frozen-candidate Test Runner acceptance pending.
24. Owner selected retention proposal and replied "ок": values OWNER-CONFIRMED,
   accepted [RETENTION V1](../product/contract-modules/methodologist-workbench/contracts/RETENTION_POLICY_V1.md).
   No automatic deletion/worker/public migration enabled; must implement bounded
   cleanup, exact successful execution timestamp and deleted-locator retry proof.
   Public policy still unpatched. Release ordering is compatible API first,0170
   second; old API rollback after0170 forbidden, migration downgrade fails closed.
25. Test & Evidence Runner **independent local PASS**, frozen
   `3c23fffa87c86124314f03add0012538ba2b6ab9`:212/failed0/skipped0, scoped Ruff6files,
   source no drift/no findings, duration185.892s. Root read managed report/JSON,
   append-only ledger delta and exact blobs; **ACCEPTED_LOCAL_ONLY**.
   Run `INVITATION-TOKEN-RLS-LOCAL-20261001-01`; managed report
   `artifacts/local_acceptance/invitation-token-rls-report.md` SHA256
   `3de4bb1872b84975e4bb6204fe70c592feac4018f0d9840706fac7420cbcc774`, results
   `3783b1b17f31e05a5284492c255dbd67de36873ae897ee51d0f29750a041e807`.
   Original PENDING reports preserved; later root disposition in managed
   `artifacts/fix_report_invitation_token_rls.md` and ledger root C1. No rerun/repair.
   DEV12 only ROOT_EXECUTOR_REVIEW_ONLY; public rollout/browser/full-neighbor and
   cleanup implementation remain gated. Next bounded local step: retention cleanup
   implementation with execution timestamp/ACL/deleted-locator retry regressions.

### Epic-update: ownership и зависимости

26. Retention implementation under root-accepted
   [implementation V1](../product/contract-modules/methodologist-workbench/contracts/RETENTION_IMPLEMENTATION_ADDENDUM_V1.md):
   migration0171 DB-owned executed_at/terminal receipt trigger and bounded exact-tenant
   invoker cleanup (dry-run default, cap500, SKIP LOCKED). Legacy successfulNULL
   remains protected; no public migration/scheduler/API/worker change. Root local175
   tests/scoped Ruff/canonical quality PASS; first51PASS/1 formatting-sensitive
   harness assertion repaired with AST wiring check, then52PASS; invariant not weakened.
   Cheap independent named-source review found no remaining concrete defect.
   Actual owned DEV retention+assignment gate IN_PROGRESS, not accepted yet.
   Root owns source/migration/gate/docs; reviewer read-only. Frozen local Test Runner
   acceptance follows after integrated source commit. No new release authority.
   First owned run:45 preceding checks PASS, retention fixture failed with
   DBAPIError/22000/DataError/AttributeError; schema cleanup/public inventory neutral.
   Source diagnosis: asyncpg interval codec needs timedelta, not Python string;
   fixture now binds text before PostgreSQL interval conversion. Failure retained
   in `.release-evidence/WB-RETENTION-20261001/failures.json`; corrected176 local
   tests/scoped Ruff PASS, second actual owned run pending. No product guard weakened.
   Graphify update attempted once, shrink guard21881 vs23077 preserved old graph;
   source fallback confirms no new domain/worker/provider edges, no forced overwrite.
27. Corrected frozen`f12a63374d347768bd9b3fddca14a5dd42393bc2` root actual owned
   **DEV64 PASS**, schema absent/public revision+table inventory neutral. Real
   non-bypass lms_app: DB time/replay/rollback, terminal immutable receipt, ordinary
   and missing-context denial, dry-run, exact inclusive24h/90d plus1microsecond
   protected side, legacyNULL/future/recent preservation, batch ordering/cap,
   tenant context isolation, actual locked-receipt skip/replay, concurrent cleanup
   and repeat0, deleted GET/confirm not-found, every cloned domain row unchanged.
   No full neighbor RLS/FK/trigger equivalence claim: LIKE clones retain the prior
   limitation. `.release-evidence/WB-RETENTION-20261001/dev-results.json` SHA256
   `9d11e345893795456bab32c92318e6713fd9ea006dcb75f5a786f421d24cbea5`.
   First45check/fixture failure preserved separately, corrected runtime confirms
   text-before-interval diagnosis. Final canonical Python baseline PASS.
28. Test & Evidence Runner independently accepted local matrix at frozenf12a6337:
   **176 passed/0 failed/0 skipped**, scoped Ruff5files, source no findings/drift;
   duration139.076s. Root reviewed report/results, exact source blobs and append-only
   ledger; **ACCEPTED_LOCAL_ONLY**. Run `WB-RETENTION-LOCAL-20261001-01` plus rootC1.
   Report SHA256`dc216f094deac431ed591274b2ee35c6219192dbbd381dbbe1e5d164acb496f2`;
   results`eca75d3978db7a920aa470cd89a65acad0dda5d319876404a38bb55b3657540f`.
   Runner DB/browser NOT_RUN; DEV64 remains ROOT_EXECUTOR_REVIEW_ONLY. Original
   PENDING records kept, later root-acceptance.json records final disposition.
   Next: full neighbor runtime equivalence + DEV browser release preflight;
   public migration/cleanup activation and voice/provider use remain separately gated.

`WB-FOUNDATION -> WB-TEXT-EXEC -> WB-DEV-ACCEPT -> WB-RELEASE`
29. Root accepted read-only
   [neighbor catalog V1](../product/contract-modules/methodologist-workbench/contracts/NEIGHBOR_CATALOG_VALIDATION_ADDENDUM_V1.md).
   Actual canonical DEV READ ONLY snapshot:12 tables/26 policies/27 outgoing FKs/
   9 user triggers; actual non-super/non-bypass lms_app checked. All9 trigger bodies
   match latest reviewed migration source: BODY_MATCH_ONLY, not configuration/
   trigger/policy/FK equivalence. All12 deny runtime TRUNCATE/REFERENCES/TRIGGER;
   column SELECT/INSERT/UPDATE/REFERENCES captured, raw expressions/bodies omitted.
   Sanitized `.release-evidence/WB-NEIGHBOR-CATALOG-20261001/catalog-complete-acl.json`.
   Earlier compact/body-only snapshots retained; initial transport truncation was
   an output-size issue, not a database failure. No business rows/mutations.
   Public tenants.service_access is permissive ALL/PUBLIC USING(true), applies to
   lms_app, FORCE false; source0013e_rls_correct.sql verified. The0045 superadmin
   policy does not restrict a separate permissive policy. Auth domain/legacy login
   and registration slug lookup depend on pre-tenant reads; do not simply drop the
   policy or enable FORCE and break bootstrap. API exploit/customer leak NOT_VERIFIED.
   Invitation0046 remains public until separately approved0170 rollout. External
   FK targets documents/learning_path_assignments/recurring_learning_assignments
   not reconstructed by prior twelve-table clones. Full neighbor gate BLOCKED.
   Local180/failed0/skipped0/1 existing warning; scoped Ruff/quality baseline PASS.
   Independent cheap review caught incomplete ACL dimensions; corrected then
   accepted, one correction. Frozen Test Runner independently180/scoped Ruff3
   PASS atf0ff29c296d244166ff4ecdc5563ca871858ed17, no source findings; root
   inspected reports/blobs/ledger and accepts ACCEPTED_LOCAL_ONLY. Run
   WB-NEIGHBOR-CATALOG-LOCAL-20261001-01 plus rootC1, Runner140.269s;
   original PENDING retained, later local/root-acceptance.json records disposition.
   Catalog ROOT_EXECUTOR_REVIEW_ONLY; no independent runtime/browser/full gate.
   Graphify AST update attempted once:21911 vs23077 shrink guard; old graph kept,
   no force/upgrade; source fallback. Root owns tooling/contracts, reviewer read-only.
30. OWNER-CONFIRMED: explicit answer "Да, только DEV после всех проверок" grants
   conditional migration0169–0171 to public Supabase DEV and updates of EXISTING
   DEV API/worker/frontend at current free tiers, preserving production and
   permanent QA stand. UNUSED: all isolation checks must pass first; this is not
   permission for public0172, billing/capacity/provider changes, production or
   bypassing failed gates. Release Runner receives an exact packet only afterward.
31. OWNER-CONFIRMED explicit "да",2026-10-01: compatible tenants RLS
   remediation, expected migration0172, local contract/negative tests first and
   public Supabase DEV only after all gates. Replace legacy service_access with
   own-tenant/validated-superadmin access plus explicitly bounded pre-tenant
   bootstrap lookup/creation paths; preserve password/OTP/invitation, registration,
   demo and permanent QA behavior. Exact policy/helper/caller impact contract and
   frozen release packet must precede writes/rollout; no bypass role, blanket
   auth flag, customer-row reads, billing or production change. Current approval
   extended to0172 after all gates; approval UNUSED publicly. Full neighboring FK/trigger gates remain
   required after remediation, not automatically PASS.
   Root accepted TENANTS_RLS_IMPACT_ADDENDUM_V1 before writes, reconciled fresh
   cheap investigator/direct callers. Bounded migration-owner SELECT functions
   reuse0111 precedent, not new runtime/bypass visibility. Staged DEV compatibility
   procedure must reconcile existing schema gate before any rollout.
32. Compatible0172 candidate implemented under the accepted impact: fixed-path
   read-only slug->UUID and legacy eligibility functions, PUBLIC execute revoked,
   runtime own-ID policy with FORCE RLS, existing platform policy preserved.
   Three public creation callers allocate server UUID/context BEFORE insert;
   domain/legacy login, demo resolution and resolved Telegram tenant payload use
   scoped reads. Root focused85/failed0/skipped0/1 existing warning, scoped Ruff4
   and canonical quality PASS (ruff1010/mypy2200, no new baseline debt).
   Actual synthetic DEV20 PASS, empty/populated upgrade and no row rewrite,
   original foreign/anonymous access reproduced then denied; own CRUD, bounded
   helper ACL/exact inputs, credential compatibility and ambiguous/wrong/legacy
   suspended negatives. Inactive-domain rejection is covered locally, not claimed
   as a live gate. Strengthened third run pins the same physical connection, compares
   pg_backend_pid and reads cleared GUCs BEFORE any reset; anonymous read remains
   denied. Exact owned cleanup and public revision/table inventory neutrality PASS.
   Managed artifacts/validation_artifacts/tenants-rls-dev-pinned-connection.json
   SHA256`6f887f5226d775465e07d0e956a8b90577deb4a9a9608f8a6a6f49a7a5c60157`.
   First sanitizer-label HARNESS_FAILURE retained, corrected without weakening
   guard; label regression added, ERRORS TEST-INFRA-010. Root DEV only, no public
   migrations/deploy/mail/OTP/AI/STT/customer rows, permanent QA unchanged.
   One fresh cheap candidate review raised two source hypotheses: domain tenant
   status check and Telegram initial User visibility. Baseline9313d044 has the
   same domain semantics and unchanged Telegram candidate query; neither is a
   regression introduced here. Scope does not authorize sibling auth redesign.
   Delta Telegram context-before-payload unit PASS with outgoing calls mocked;
   actual complete Telegram/RLS authentication NOT_VERIFIED. Existing domain
   semantics explicitly preserved, not claimed as new account eligibility policy.
   Frozen Test Runner acceptance still pending; local candidate is not release GO.
   Current AST update21964 vs23077 stopped by shrink guard; old index preserved,
   no force/rebuild/tool upgrade. Bounded direct source/caller review authoritative.
33. Frozen Test Runner independently85/failed0/skipped0/Ruff4/quality/no actionable
   delta finding at5bc7d1a972ee2181cb321ed8d62b3bb67e53d7de; root reviewed managed
   reports/hashes/source/ledger and accepts ACCEPTED_LOCAL_ONLY. Runner214.910s,
   token/model-observation/root-review counters NOT AVAILABLE. One safe invocation
   correction: packet had correct unit/ paths, Runner's derived invocation did not;
   initial HARNESS_FAILURE/no tests retained. Suspended Tenant proof applies to
   legacy fallback only, not a new domain rule. Original PENDING kept; ledgerC1
   and managed artifacts/fix_report_tenants_rls.md record later root acceptance.
   Full neighbor/DEV rollout/browser still gated, no push/public migration.
34. Next bounded gate: source-bind ALL26 existing policies/ACL dimensions, ALL9
   complete trigger definitions/config/security (not just bodies), ALL27 outgoing
   FKs before owned reconstruction. Read-only cheap inventory confirmed four
   external edges to documents (2), learning_path_assignments (1), recurring_learning_assignments (1).
   Empty target-only stubs can prove FK child-side rejection, not target-side
   policy/trigger/business equivalence. Do not mislabel them full acceptance.
   Root must accept exact source-bound reconstruction impact before any new owned
   DDL; metadata-only addendum does not authorize it. Canonical DEV schema gate
   currently upgrades head before API, incompatible with tightening0170/0172
   before helper rollout. Reconcile staged expand/compatible API+worker/restrict
   procedure and QA expected revision before Release Runner dispatch.

35. OWNER-CONFIRMED2026-10-02: "продолжай по плану. выведи в прод" grants
   production release of the accepted bounded workflow after all applicable
   local/DEV/release gates, not paid tiers/resources, arbitrary data deletion or
   a claim of unimplemented LLM/voice capability. Authority UNUSED. Root accepted
   NEIGHBOR_RECONSTRUCTION_VALIDATION_ADDENDUM_V1 before validation source edits;
   all26 policy/27FK/9 complete trigger controls must be source-bound and read back
   in the owned schema. Four referenced targets include learning_path_courses
   discovered from0145 body; learning_paths is the fifth read-only policy dependency.
   No target-side lifecycle equivalence claimed.

36. Root assembled source-bound neighbor gate: actual isolated DEV73 PASS after
   exact0141 purge dependency binding, five target SELECT policies/ACLs and
   dependency-ordered organization fixture. Earlier partial failures retained;
   every run cleanup/public-neutral PASS. STAGED_COMPATIBILITY_RELEASE_ADDENDUM_V1
   accepted before implementation: additive169 helpers/shared installer, compatible
   API+worker with workbench OFF, then exact169->172; production controller unchanged.
   Final assembled staged owned DEV74 PASS, including baseline26policies/27FK/
   9triggers/11functionACL and169 no restriction, then170/171/172 plus all bounded
   assignment/invitation/organization/retention negatives/concurrency. Managed
   artifacts/validation_artifacts/workbench-neighbor-staged-pass.json SHA256
   `595b3104d45d8f9f56925826601cb2e682df92b23a474ee27f5f5e065d0772cd`.
   Root runtime evidence only; frozen independent acceptance pending. Cheap review
   found contract-phase no-op receipt gap, repaired BEFORE final packet; regression
   PASS. Canonical quality1010/2200 PASS; full frozen test count still pending.
   Graphify update22109vs23077 shrink guard, old index retained/no force or upgrade.
   Source fallback verified. Candidate0.11.26 compatibility A; no push/public
   migration/deploy/flag/scheduler/mail/AI/STT/billing/customer mutation yet.

37. Root accepted C2 LOCAL_ONLY at frozen2ce87398 after reading immutable C1/C2
   reports and exact two-file correction: delayed policy response reproduces RED,
   await loaded checkbox preserves all assertions, focused7 and full765 PASS,
   lint/typecheck/build/version PASS. API283/quality1010/2200 remain explicitly
   PRIOR_IMMUTABLE_EVIDENCE; owned74 proof remains ROOT_EXECUTOR. Original failures
   retained. Public DEV0168 exact25 API/worker/Vercel reconciled, QA warm verification
   PASS with zero business mutations. Production read-only exact25/all4 containers
   running, restart0, current/rollback images and57% disk verified. This accepts
   source publication/CI and the conditional additive DEV169 gate, NOT production
   deployment or feature GO. Final169 compatibility receipt, head172, real browser,
   protected migration/backup and CT137 capacity gates remain outstanding.

38. CI36969240393 at9480fe20 failed two hard gates: image-graph pypdf6.17.0
   7advisories and catalog-load ModuleNotFoundError. Original retained, no public
   migration/deploy. STAGED_RELEASE_REMEDIATION_ADDENDUM_V1 accepted BEFORE repair.
   Isolated catalog RED -> lazy execution import GREEN24; PDF/release62 and
   extraction/export/source81 PASS on explicit6.19.0; only pypdf lock entry/hash
   changed. Corrected actual owned74 reexecution PASS, cleanup/public-neutral.
   Independent leaf review accepted lazy imports/native explicitfalse, requested
   immutable manifest semantic gate. Root accepts this bounded gate BEFORE edit:
   existing inspect_native_artifact must require literal false for exact
   compatibility product0.11.26, reject missing/true/numeric/string; older
   artifacts remain compatible, no new packet/controller/feature activation.
   Canonical quality1010/2200 PASS; updated error header contract must be rerun.

39. Replacement5369 CI36970476153 dependency audit/catalog/RLS6jobs PASS,
   full integration stops demo-login500/tenants_slug_key (29 preceding PASS).
   Factory leaves bound tenant in shared outer transaction; client override
   yields that session unchanged, unlike production get_db fresh-session
   request. Bounded bootstrap correctly requires empty/nonplatform context;
   do NOT relax its SQL or weaken isolation. Root accepts BEFORE test-infra edit
   exact request-boundary correction: tests/conftest.py client dependency override
   resets transaction-local tenant/user/platform/auth-lookup/impersonation values
   BEFORE every HTTP request, retaining rollback-only fixture/savepoint ownership.
   Named local async regression must invoke actual client fixture with a synthetic
   FastAPI dependency and mock session, prove before-handler reset every request,
   no commit/rollback. Full CI demo/integration proves actual path after correction;
   no public business rows or shared DEV demo factory execution on workstation.
   Graphify current indexed helper absent/stale; bounded source confirmed instead.

40. Root accepts C3 LOCAL_ONLY after reading immutable report/results:160 named
   tests/Ruff6/quality1010-2200/release-contract/version PASS at5369e2e5; web
   C2 unchanged765 remains PRIOR_IMMUTABLE_EVIDENCE and root owned74 remains
   ROOT_EXECUTOR_REVIEW_ONLY. CI36970476153 FAIL remains NO_GO, not relabeled.
   Request-boundary fixture correction has actual local RED0vs1 then GREEN28,
   independent cheap source review accepted, no product/RLS/migration delta.
   TEST-INFRA-011 records recurrence; replacement immutable CI must prove real
   demo login and full integration. No public DEV/production migration, deployment
   or flag mutation has occurred. Current runtime remains25/schema0168.

41. Root accepts frozen HTTP fixture report/results LOCAL_ONLY:28/Ruff2/contract
   PASS; named boundaries unchanged. CI36971832018 at eb0211c8 reaches1449PASS,
   2SKIP then Telegram test StopAsyncIteration (finite execute mock exhausted).
   Exact narrow local RED1 reproduced; original CI retained/no public mutation.
   Root accepts BEFORE delegated edit statement-aware mock in ONLY
   tests/test_telegram_webhook.py distinguishing resolved User/UserRole/Tenant
   queries from set_current_tenant context setup, rejecting unknown statements,
   asserting exact bound tenant before payload read and preserving original
   UUID serialization/status/payload assertions. No product change authorized.
   Full named-file regression and replacement CI required. Leaf cheap writer
   owns that file only; root owns shared docs/evidence/release.

42. Cheap Telegram test writer delivered exact one-file correction; root reviewed
   statement mapping and context-before-read assertions against telegram.py.
   Narrow RED1->GREEN1 and full15/Ruff PASS accepted LOCAL_ONLY. No runtime/API
   change. TEST-INFRA-012 added; replacement immutable CI remains NO_GO until
   complete. Canonical CT125 inspection found byte-identical installed signed
   restore script and existing postgres signing key; initial root-key absence
   was an executor-identity diagnostic, not an access/credential blocker.

43. Exact23630036 CI36972605875 all7 PASS, main3767/2skip and unit2208.
   Published tag/Release26 and independent master/dev remote readbacks recorded.
   DEV A schema169/provider exact26/permanent QA/authenticated disabled404/actual
   Celery control PASS; no business writes/paid resources. Production protected
   run36975605117 accepted root A-only gate and fresh signed restore0168, deployed
   exact23630036/image5335396f9eb7b4d821d984ff2a94445540d492edd21ad7741d23e2b1298e2440.
   Independent four-service/private/public/catalog readback PASS, schema169;
   watchdog reconciled26/image; candidate-retention/watchdog oneshots and timers
   active. Phase EXPANDED_NOT_FINAL, flags OFF, not final172/feature GO.

44. Owner approved two conditional exact frontend cleanups. Obsolete23/36826
   tree/staging removed with verified off-host recovery; old24/1e10 MUST remain
   until actualfrontend26/current and actualrollback25. Frontend A execute stopped
   before switching; actualcurrent/marker25/running/no26dir, pair26 staged,
   free1464004KiB. Failed original artifact preserved. Root accepted BEFORE repair
   narrow sidecar mismatch: ninth explicit workbench flag vs eight-field helper.
   Cheap writer owned helper+unit file; root preflight now invokes the same strict
   helper before staging, without stripping metadata. Actual original artifact
   REDsidecar_fields_invalid; preflight regression REDnotraised->GREEN1;
   independent Test Runner37PASS/19UnixSKIP/9subtests/Ruff4/artifact PASS accepted
   LOCAL_ONLY, managed report c8186f5f/results9967d28a. Owner approved exact helper
   5db503fa835a6bbff18796a730c34ed96b8ca3a1836507b335fbc5b64b6e1060 replacement
   with backup/rollback/no privilege expansion. NOT INSTALLED: canonical Proxmox
   API TLS SSLError and browser ERR_CERT_AUTHORITY_INVALID; no guest mutation,
   TLS bypass, alternate credentials, cleanup2 or new deploy attempted.
   That proposed next administrative branch was subsequently STOPPED by root
   after owner's objection; no helper installation, TLS bypass or wider access.

45. Owner asks repair/finish without Proxmox. Root accepted native packaging
   amendment BEFORE implementation: distinct frontend-only27 source/tag/artifact,
   unchanged installed helper/exact8 manifest, local exact6 build-config attestation
   schema1/source/version/archive/manifest hashes/literalOFF. Old26 artifact stays
   unchanged and rejected. Actual RED2 then GREEN57/20UnixSKIP/9subtests/Ruff3;
   strict duplicates/symlink/missing/unknown/mismatch/drift-before-stage covered.
   Independent cheap review found old cached-download provenance gap; root repaired
   fresh unique exact-run download each phase, preserving earlier files, and safe
   malformed-package mapping. Frozen Test Runner C1 independently57/20skip/9subtests,
   Ruff/diff/exacthashes PASS; root read full3f7dd667/53cc8371 reports and accepts
   LOCAL_ONLY. Cheap correction review no remaining finding. No new
   push/CI/provider/production mutation at this checkpoint. Backend26/schema169/OFF,
   currentfrontend25/rollback24 remain prior verified state. Cleanup24 remains
   NOT_RUN; its approved condition is successful26, not an inferred27 substitution.
   Complete compatible frontend then distinct B/final172/activation/browser gates.

`WB-TEXT-EXEC -> WB-LLM-INTENT -> WB-DOCUMENT-DRAFT -> WB-CORRECTION`

`WB-ASR-BENCH -> WB-VOICE-INPUT` (отдельный resource/data gate)

| Node | State | Owner / writer / reviewer | Exit / next gate |
|---|---|---|---|
| WB-FOUNDATION | DONE | root / root / independent cheap reviewer |76 pure tests и quality PASS; commit5afa42f |
| WB-TEXT-EXEC | DONE | root; parser/UI cheap leaf writers; root + independent reviewer |138 API tests, web checks, isolated DB gate PASS; flags off |
| WB-DEV-ACCEPT | IN_PROGRESS | root; Test & Evidence Runner on exact accepted packet |DEV A26/schema169/OFF/provider/QA/worker PASS; finalB172/browser unresolved |
| WB-NEIGHBOR-CATALOG | DONE | root / root tooling / cheap reviewer + Test Runner |Read-only DEV12tables/26policies/27FK/9bodies and independent local180 PASS atf0ff29c2; root ACCEPTED_LOCAL_ONLY; no equivalence claim |
| WB-LLM-INTENT | NOT_STARTED | root shared contract; bounded leaf fixtures |Existing policy/quota binding; no new provider/spend authority |
| WB-ASR-BENCH | BLOCKED | root |Permitted corpus + measured already-paid capacity; no ASR installed |
| WB-RELEASE | IN_PROGRESS | root + Release Runner |Production API A26/schema169/OFF PASS; frontend25 retained, original26 blocked; packaging27/local acceptance pending, then B172 and live gates |

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
| Test & Evidence Runner / local acceptance |Requested gpt-5.6-luna / medium; independently observed model metadata NOT AVAILABLE |Accepted;1 evidence-only correction, no source repair |160 API/18 web/build PASS; primary run240.275s, correction38.008s; token/review counters NOT AVAILABLE |
| workbench_activation_review / inventory + independent delta review |Requested gpt-5.6-luna / medium; independently observed metadata NOT AVAILABLE |Accepted both handoffs,0 corrections |Exact source review only, no DB/network/writes; time/token counters NOT AVAILABLE |
| root / invitation gate integration |Parent session; exact metadata NOT AVAILABLE |3 RED guards repaired,10 GREEN;69 focused tests/quality; DEV33 PASS |Cleanup/public metadata neutrality PASS; invitation delivery NOT_RUN; time/token counters NOT AVAILABLE |
| Test & Evidence Runner / invitation local acceptance |Requested gpt-5.6-luna / medium; independently observed model metadata NOT AVAILABLE |Accepted corrected run;1 invocation correction +1 evidence C1; no product repair |69 tests/scoped Ruff PASS, original run180.738s/C1 37.168s; root rework/token counters NOT AVAILABLE |
| workbench_neighbor_rls_inventory / source-only inventory |Requested gpt-5.6-luna / medium; independently observed metadata NOT AVAILABLE |Accepted,0 corrections |Root verified source/actual catalog exception; no external agent access; time/token counters NOT AVAILABLE |
| organization_gate_review / independent exact-delta review |Requested gpt-5.6-luna / medium; independently observed metadata NOT AVAILABLE |Accepted after1 review-scope/contract correction + final hire-delta review; no leaf writes |No remaining findings; cancellation/after-selection semantics explicitly not claimed; time/token/review counters NOT AVAILABLE |
| root / organization and metadata gates |Parent session; exact metadata NOT AVAILABLE |Owned harness/fixture corrections; corrected DEV42/170 API/quality PASS |Public metadata blocker remains; cleanup/public inventory neutral; time/token/review counters NOT AVAILABLE |
| Test & Evidence Runner / organization local acceptance |Requested gpt-5.6-luna / medium; independently observed metadata NOT AVAILABLE |Accepted first packet;0 product corrections; later root-disposition receipt only |170 tests/scoped Ruff/no findings;207.559s; root rework/review/token counters NOT AVAILABLE |
| invitation_security_investigator / independent source tracing |Requested gpt-5.6-luna / medium; observed metadata NOT AVAILABLE |Accepted,0 corrections |Found source0119 precedent; no external reads/writes; time/token counters NOT AVAILABLE |
| invitation_bypass_review / fresh independent candidate review |Requested gpt-5.6-luna / medium; observed metadata NOT AVAILABLE |Accepted,0 corrections |No concrete surviving bypass/regression; source-only, no runtime claim; time/token counters NOT AVAILABLE |
| root / invitation RLS fix and retention policy |Parent session; metadata NOT AVAILABLE |Original synthetic trigger reproduced; patched DEV12/212 API/quality PASS; mock-order/selector corrections preserved |Public not patched; no cleanup enabled; time/review/token counters NOT AVAILABLE |
| retention_contract_review / bounded independent contract+delta review |Requested gpt-5.6-luna / medium; observed metadata NOT AVAILABLE |No remaining concrete source finding;0 correction rounds |Read-only named paths; initial pending behavioral-gate gap implemented by root; time/token counters NOT AVAILABLE |
| Test Runner / frozen retention acceptance |Persistent configured model/effort NOT AVAILABLE |Independent176/scoped Ruff/no findings; root accepted |139.076s; no DB/browser; token counters NOT AVAILABLE |
| root / retention migration+owned DEV integration |Parent metadata NOT AVAILABLE |Local176/quality and corrected actualDEV64 PASS |Initial harness string/interval failures preserved; no public cleanup; time/review/token counters NOT AVAILABLE |
| Test & Evidence Runner / invitation RLS local acceptance |Requested gpt-5.6-luna / medium; observed metadata NOT AVAILABLE |Accepted first packet,0 product corrections; later root disposition only |212 tests/scoped Ruff/no findings;185.892s; time/review/token counters NOT AVAILABLE |
| workbench_neighbor_inventory / source inventory + independent catalog review |Requested gpt-5.6-luna / medium; observed metadata NOT AVAILABLE |Accepted after1 ACL correction; root corrected initial misnamed tenants policy origin |Read-only sources; no agent DB/env/network; time/token counters NOT AVAILABLE |
| Test & Evidence Runner / bounded catalog local acceptance |Persistent configured model/effort NOT AVAILABLE |Accepted first packet, no repair/findings; root disposition C1 |180/Ruff3 PASS atf0ff29c2;140.269s; runtime not independently executed, token counters NOT AVAILABLE |
| tenant_candidate_review / fresh tenant review then separate neighbor inventory |Requested gpt-5.6-luna/medium; observed metadata NOT AVAILABLE |Root source-disposition2 preexisting auth hypotheses; separate inventory read-only,0 repairs |19 then-current tests PASS; no agent DB/network/writes; full Telegram/RLS NOT_VERIFIED |
| root / compatible tenants isolation candidate |Parent metadata NOT AVAILABLE |Accepted local85/quality + corrected pinned DEV20; sanitizer-label failure retained |Original broad access reproduced and denied; no public migration; same physical rollback proved; counters NOT AVAILABLE |
| Test Runner / frozen tenants local acceptance |Persistent configured model/effort NOT AVAILABLE |Accepted local only after1 safe invocation correction, no source repairs |85/Ruff4/quality PASS at5bc7d1a9;214.910s; root DEV20 reviewed only, token counters NOT AVAILABLE |

Точные сроки оценим после вертикального среза и ASR benchmark; обещать голосовой
production за фиксированное число дней без этих измерений было бы неверно.
После полного выполнения плана его факты переносятся в durable contracts и
канонические эксплуатационные документы; временный план удаляется.
