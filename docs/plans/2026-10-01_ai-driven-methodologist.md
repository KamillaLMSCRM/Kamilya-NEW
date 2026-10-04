# AI-driven Камиля: пошаговый план методического рабочего места

Дата: 2026-10-01. Владелец продукта: пользователь; технический владелец: root.
Статус обновлён 2026-10-04: текстовый assignment slice закрыт выпуском backend29/
schema174 на2026-10-02, включая живую проверку и штатную очистку A/B; native
frontend28 сохранён. Это датированное release evidence, не новое runtime readback.
Изолированный ASR-пилот на ASUS: CPU baseline и сравнение decoder policies
проверены; 15s отклонён, 30s оставлен исследовательским кандидатом, качество KK
ещё не улучшено. Подготовлен набор пользовательских записей под synthetic DEV QA.
Голос в продукте/LLM intent/document drafting ещё не выпущены.
Free-text interpretation выпущен в DEV e9f739dd на существующих Free/Hobby
ресурсах, CI all7 PASS; сохранённый QA/schema174 verify PASS. RU provider PASS;
KK сохранил внешние кавычки курса, probe остановлен после2 вызовов.
Принятый V3 fallback и актуальная RU/KK/EN справка исправлены локально:
9 регрессий/14 help/quality и реальный owned DEV72 PASS, cleanup/public neutrality
PASS. Следуют frozen Test Runner, повторный exact-SHA DEV и живой полный flow.
Production/голос/document drafting этим DEV-выпуском не добавлены.
Ветка: `feature/methodologist-workbench-20261001`.

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
| Local/KZ faster-whisper | Контроль маршрута аудио, нет обязательной платы за минуту | Нужны ресурсы, сопровождение, проверка качества RU/KK | Установлен только изолированный ASUS-пилот; не LMS runtime |
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

### Уточнённый план голоса и телефона — 2026-10-03

Цель: в существующем чате/рабочем месте напечатать либо надиктовать ту же просьбу,
проверить расшифровку и продолжить тот же разрешённый сценарий. Это не объединение
прав трёх помощников: learner chat отвечает по доступному учебному контексту;
editor assistant сохраняет question-scoped preview/apply; methodologist workbench
создаёт server-resolved preview и исполняет только явно подтверждённый план.

Docvoice использован только как названный владельцем технический пример:
MediaRecorder → серверная запись → STT → editable review; QR-телефон доставляет
аудио через сервер, а не напрямую в ПК. Не переносить пациентские сущности,
Groq-ключи, согласия либо Supabase Realtime в Kamilya. Историческое наполнение
полей существовало; текущий проверенный callback лишь логирует результат, поэтому
копирование последнего UI не равно работающему сценарию. Документ-источник:
`C:\Docvoice\app\docs\ai\voice-recognition-and-remote-microphone.md`.

| Шаг | Конкретная доработка | Проверка выхода |
|---|---|---|
| V0 — текущий | Изолированный ASUS benchmark: small CPU/int8 vs multilingual large-v3; публичные RU/KK записи с эталоном и лицензией; отдельная проба CUDA | Версии/ревизии/хеши, WER/время/RSS, сохранённые ошибки; не выдавать 10 записей за продуктовую приёмку |
| V1 — качество | Расширить независимый корпус до60–100 записей, включая реальные mixed/noise и вымышленные названия/сроки/отрицания; не подгонять prompt под test set | Критические поля≥95%, исправления и p50/p95; ручная эталонная разметка, запрещённые неверные действия0 |
| V2 — speech seam | Принять полный API/job/ownership/TTL addendum; отдельная ограниченная очередь/процесс, admission/cancel/timeout, без записи в бизнес-таблицы | Decode/MIME/длина/размер/тишина/повреждение; foreign tenant/actor/job denied; отмена не выдаёт поздний результат; text fallback |
| V3 — запись в браузере | Микрофон/стоп/отмена/прогресс/ошибка; показ редактируемого текста; отправка текста отдельным действием в тот же существующий помощник | Chrome/Android и Safari/iOS реальные codec/decode; запрет микрофона, уход со страницы, плохая сеть; одинаковые права text/voice |
| V4 — QR-телефон | Временная capability-сессия одного микрофона; результат видит только авторизованный desktop того же tenant/actor/context | Два изолированных browser contexts; expiry/replay/revoke/foreign-session tests; физический телефон по HTTPS, camera/mic proof |
| V5 — свободная команда | Existing LLM policy/quota → typed intent → server resolver; уточнить неоднозначные курс/отдел/относительную дату; voice использует тот же путь | «Не назначай», смена срока/отдела, неизвестный курс, две даты, повтор и stale preview; никогда не исполнять ответ модели напрямую |
| V6 — документ/коррекции | Прикреплённый источник → существующий generation job → draft; source-grounded правки до/после, published→новый draft | Existing AI-course critical journey, ownership/quota/cancel/dedup, review/publish не обходятся |
| V7 — выпуск | Сначала DEV синтетический QA; production только после отдельного принятого candidate/capacity/route gate | Test & Evidence Runner + Release Runner; exact source/image/schema/workers, browser/телефон, rollback и очистка |

ASUS — лаборатория, не подразумеваемая production-зависимость. На существующей
production VM отдельно измерить свободные CPU/RAM/disk, очередь и влияние на
API/генерацию без установки модели до принятого capacity packet. Даже хороший
результат ASUS не доказывает VM126 latency. Если малый CPU-кандидат не обеспечивает
RU/KK качество либо реальный ресурсный gate не пройден, feature остаётся в DEV;
выбор ASUS как production-ресурса/другой GPU/STT API — новое точное решение, без
скрытого платного fallback и без изменения текущих тарифов.

Предлагаемый QR-контракт (ещё не разрешение на migration/runtime): desktop после
проверки роли и контекста создаёт случайный одноразовый256-bit token; QR содержит
только capability, не LMS JWT/пароль/tenant ID. Короткий TTL до обмена, сервер
хранит только token hash; обмен по POST выдаёт ограниченное право ровно одной
загрузки, не доступ к курсам/назначениям/истории. Token не попадает в analytics,
access logs и referrer; использовать fragment и страницу без третьих скриптов.
Сессия bound к tenant/actor/active role/target context и отзывается при logout,
смене tenant/роли/контекста или отмене. Состояния issued→paired→uploaded→
transcribing→transcript/failed/cancelled/expired; каждое повторное upload/redeem
отклоняется. Desktop получает результат через ограниченный authenticated polling,
не public realtime channel. Exact TTL/job timeout/poll budget/temporary deletion
фиксируются в V2 impact addendum до реализации; они не равны workbench15min/90days.

Минимальные отрицательные проверки: silence/corrupt/unsupported/oversize/too-long;
один запрос при двойном stop; disconnect/retry/cancel/late result; job/QR чужого
actor/tenant; истёкший/reused/revoked QR; desktop switched context; ученик не
получает methodologist tools; переполнение существующего text limit не обрезает
команду молча; только кнопка подтверждает публикацию/массовое назначение.

Изолированный pilot packet принят root по текущему запросу владельца:
[ASUS-STT-PILOT V2](../product/contract-modules/methodologist-workbench/contracts/ASUS_STT_PILOT_ADDENDUM_V2.md),
с сохранением границ V1.
Исходная карта соседей для V1 была SOURCE-DERIVED из известных schemas/UI,
не graph-derived proof. Graphify index появился позднее в writer; это не
меняет происхождение исходной карты. Продуктовые интерфейсы пилотом не меняются.

### Измеренный ASUS baseline — 2026-10-03, CPU only

Источник: [Google FLEURS](https://huggingface.co/datasets/google/fleurs), CC-BY-4.0,
revision`70bb2e84b976b7e960aa89f1c648e09c59f894dd`. По5 разных test-фраз на язык,
выбранных до inference: RU17.16–24.36s, KK15.36–18.96s. Known-language hint RU/KK;
только диагностическая splice36.12s использует auto-language. Не benchmark
естественной mixed speech или автоматического выбора языка RU/KK.

Runtime: faster-whisper1.2.1/CTranslate2.4.8.2/PyAV16.0.1/HF Hub1.33.0,
CPU int8/4threads/one request, beam5/no context reuse/no VAD. Model revisions:
small`536b0662742c02347bc0e980a01041f333bce120`,
large-v3`edaa852ec7e145841d8ffdb056a99866b5f0a478`, обе MIT.
Одинаковые11 файлов/manifest hash`764456dc10ec0a8a1cb8d0f13b4ee2b7c517b2ad82ba49dae2cf895b3b71a0f4`.
Verifier повторно проверил artifact/input hashes, реальные durations/эталон,
ошибки, aggregates/RTF/decode policy и отсутствие product-proof flags.

| Измерение | small CPU/int8 | large-v3 CPU/int8 |
|---|---|---|
| RU weighted WER |3.62%, 5 errors/138 reference words |0%, 0/138 |
| KK weighted WER |64.47%, 49/76 |21.05%, 16/76 |
| RU median / max processing |1.91s /2.63s |8.43s /10.42s |
| KK median / max processing |1.67s /2.50s |8.83s /12.83s |
| Process peak RSS, including splice |1.23GiB |2.97GiB |
| Model-constructor load / first clip |0.53s /2.07s |2.91s /10.42s |
| Artificial RU+KK splice WER / processing |49.12% /12.08s |38.60% /24.60s |

Решение: технический ASR baseline работает, small не является достаточным RU/KK
продуктовым кандидатом. Large-v3 оставляем comparator, не считаем выбранной
production-моделью: казахский/смешанный сценарий пока требует улучшения и новых
данных. RU0% на5 записях не означает «безошибочный русский». Domain slots,
естественная mixed/noise speech, автоязык, p95/cold-cache/concurrency/cancel,
phone/browser flow и VM126 capacity **NOT VERIFIED**. Открытый GPU gate —
официальный aarch64 CTranslate2 wheel без CUDA; драйвер/другие окружения не меняли.

Результаты и weights/cache сохранены в task-owned ASUS root; отчёты без аудио
также в ignored`.release-evidence/stt-asus-20261003` writer. Owned footprint4.7GiB,
после теста available RAM≈116GiB/disk388GiB; другие операции хоста не исследовались.
Четыре защищённых timers active/enabled, listening sockets прежние; pre-existing
book failure сохранён. Первые pip-команды использовали обычный user cache, не
вычищаем общий cache; следующие installs задают PIP_CACHE_DIR внутри pilot root.
No new paid resource/provider/billing/production mutation. Следующий V1 шаг:
исследовать разрешённый RU/KK comparator/адаптацию, собрать domain/mixed corpus,
отдельно подготовить own CUDA build; не подключать текущий baseline к продовым
поручениям только из-за скорости. Для GPU build требуется отдельный bounded
packet, но не повторное согласование уже разрешённого изолированного теста.

### Decoder-policy comparison — 2026-10-03, CPU only

На тех же11 inputs/weights/runtime без установки или скачивания сравнили
auto-language/multilingual decoding с chunk_length15 и30. В обоих режимах
language=None/task=transcribe/beam5/condition_on_previous_text=false/VAD=false;
ни эталон, ни начальный prompt не передаются распознаванию.

| Измерение | Предыдущий hinted baseline | Auto15s | Auto30s |
|---|---|---|---|
| RU WER, errors/words |0%, 0/138 |18.84%, 26/138 |0%, 0/138 |
| KK WER, errors/words |21.05%, 16/76 |34.21%, 26/76 |21.05%, 16/76 |
| RU median processing |8.43s |18.85s |13.59s |
| KK median processing |8.83s |17.82s |14.01s |
| Artificial splice: diagnostic-only WER |38.60%, 22/57 |71.93%, 41/57 |5.26%, 3/57 |
| Artificial splice processing |24.60s |29.82s |29.88s |

Решение: Auto15s отклонён из-за ухудшения языка и скорости. Auto30s оставлен
кандидатом для следующего теста: на текущих отдельных RU/KK фразах убирает
необходимость заранее сообщать язык без роста WER, но медленнее baseline.
**Качество казахского пока не улучшено.** Искусственная склейка улучшилась,
но не доказывает качество естественного RU/KK code-switching.
Small по-прежнему не принят как общий RU/KK-вариант.

Оба remote audits PASS; независимые Windows hashes/row sums совпали.
Reports Auto15s SHA256`08e9b1bc7139297e5587bc66b2521bead3fdc35c4633165bb96085ee6fa321e7`,
Auto30s`d5a2ade4e83d0b7590c7de3f6a9796f040ff25d7b4539ed8b7f4509fc538fd0c`.
Schema2 механически отделяет artificial_splice от RU/KK и запрещает acceptance;
первый raw Auto15s/schema1 сохранён неизменным, typed audit записан отдельно.
Root focused27 tests/Ruff и независимые4 tests PASS. Postcheck:116GiB RAM,
370GiB свободного диска, pilot4.7GiB; те же TCP listeners/четыре active+enabled
timers, benchmark process отсутствует. Никакой новой service/GPU/production связи.

Исследован, **не скачан и не выбран**, KK-adapted
[Whisper Turbo](https://huggingface.co/shyngys879/kazakh-whisper-large-v3-turbo),
revision`dafae810c95496f66184605824be5a0a971d3c09`, declared Apache-2.0,
Transformers/Safetensors, не готовый CT2 artifact. Автор сам отмечает ограничения
RU/KK code-switching; его FLEURS-цифры — не наши измерения. Перед пробой нужен
bounded installation/conversion packet, проверка происхождения/license и
сопоставимость обучения/holdout; установка в другие окружения не разрешена.

Подготовлены [12 фраз для записи](../testing/voice-recording-kit-dev-qa.md)
под реально проверенные tenant/course IDs постоянного DEV QA. Отделов нет,
поэтому отделовые случаи только negative; ничего не создано/назначено/сброшено.
Первый login завершился ReadTimeout (причина NOT_VERIFIED); payload-free health
прошёл. Следующий login403 возник в helper без штатного Origin; исправлен сам
helper по canonical Client procedure, затем actor/course/empty-departments GET
readback PASS. Защита, пароль и стенд не менялись.

Следующий gate: естественные RU/KK/domain записи без подсказок эталона, ручной
ground truth и точные критичные поля. Кандидат30s сравнивается с baseline и
отдельным разрешённым KK comparator, не подбирается по этим пяти примерам.
До загрузки личного аудио уточнить способ/TTL pilot intake; публичные corpus
правила не означают бессрочное хранение голоса владельца. Product ASR/LLM intent,
phone/browser/cancel/p95 и VM126 capacity остаются NOT_VERIFIED.

AST-обновление Graphify попытались один раз после добавления helper: shrink guard
отклонил22508nodes против прежних24222. Force/reinstall не использованы; причина
уменьшения NOT_VERIFIED. Сохранённый graph24222/54919 structural diagnose PASS,
но freshness новых helper-связей отсутствует: финальный review SOURCE-DERIVED,
не graph-derived. Этот навигационный gap не заменяет/не отменяет unit/runtime proof.

## Этапы и критерии выхода

### Free-text assignment implementation — 2026-10-04, acceptance in progress

Accepted [intent V2](../product/contract-modules/methodologist-workbench/contracts/LLM_ASSIGNMENT_INTENT_ADDENDUM_V2.md)
preserves V1 boundaries and historical zero/None monthly-budget default. New
explicit parse endpoint returns an editable candidate only. Existing tenant-owned
exact resolution, recipient snapshot, fifteen-minute preview, revision/fingerprint,
confirmation and replay remain the sole execution path. Correction loads an owned
unexpired plan before any provider/admission; no IDs/recipients are sent in the
server-generated prompt. Candidate/source/session edits invalidate confirmation.
No automatic semantic repair/retry; existing tenant-aware provider chain is reused.

Root focused API166/quality1010+2200 PASS; leaf UI27/type/scoped ESLint PASS with
time-input normalization, then seven root malformed-candidate cases added for the
independent34-case packet. Three bounded cheap-agent scopes were used: policy/
independent review, pure parser+tests, UI/client+tests. Root repaired cancellation/
post-commit RLS refund and correction context; exposed tokens are NOT AVAILABLE.
No new $1 test ceiling, provider, paid resource or financial zero-budget meaning.

Real owned DEV attempts retained in
`.release-evidence/TEST-WB-LLM-INTENT-20261004-A/root-dev-failures.json`:
first DATA_FIXTURE duplicate settings, then PRODUCT_DEFECT SQL42P08 at first
budget INSERT. Both preceding64 checks passed; both exact schema cleanup and
public-schema neutrality passed. Mock tests were insufficient SQL type evidence.
Corrected real DEV gate71PASS with explicitly typed integer reservation,
candidate-to-owned-preview, exhaustion-before-provider, foreign previous-plan
denial, RLS refund, concurrency bounds and foreign usage hidden. Exact cleanup
and public neutrality PASS; external provider calls zero. Terminal receipt:
`.release-evidence/TEST-WB-LLM-INTENT-20261004-B/root-dev-pass.json`.
Independent corrected B/C1/C2 local acceptance is ROOT_ACCEPTED_LOCAL_ONLY:
310 API,25 AI-neighbor,34 UI cases; type/scoped ESLint/build67pages/quality/
release contracts/version/diff PASS. Original failures stay unchanged. C1 fixed
only invocation (pwsh7, not powershell5); C2 fixed only journal Date formatting.
Successful source/build proofs are hash-linked, not rerun; source is prepared
for the feature branch, not deployed. Actual model/DEV browser/release remain open.

CodeGraph1.6.1 used for exact parser/provider/budget seam and affected callers.
Initial missing-symbol query and truncated provider search are retained as
limitations, not successful navigation. Post-edit sync5599ms total/1301ms update,
1633files/30169nodes/80551edges, excluded-path audit PASS. Budget callers6 and
intent callees12 each20ms query body; source confirmed relevant consumers.
Two `db.commit` edges point to an unrelated fake test session: false dynamic
dispatch candidates, rejected through source. SQL/RLS/provider runtime is not
graph proof. Prior sync8500ms total/2466ms update is preparation overhead.
No Graphify rerun of answered relations; no matched A/B, exposed token or actual
CodeBurn subscription-saving evidence. ECC/Graphify/CodeBurn benefit is NOT
MEASURED for this slice; no causal speed/cost claim.

Next gates: corrected real owned DEV proof -> frozen Test Runner local regression/
build -> existing-free DEV deployment plus bounded actual-provider RU/KK semantics
and browser edit/correction/preview/confirm/replay -> exact Release Runner packet,
protected production rollout/readback/live QA. Voice/document drafting stays
separate; no new speech capability is claimed by this text slice.

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
- Долговечные plans/receipts принадлежат workbench. В текстовом slice миграции,
  retention metadata и scheduled cleanup реализованы; DEV/production29/0174
  закрыты датированным evidence2026-10-02. Это не срок хранения raw audio/QR.
  OWNER-CONFIRMED2026-10-01:15min validity, ready-plan delete24h after expiry,
  succeeded receipt90days from execution; [policy V1](../product/contract-modules/methodologist-workbench/contracts/RETENTION_POLICY_V1.md).
  Scheduled metadata cleanup реализован; learning history never included.
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

46. Compatibility frontend27/source30693e45 was committed/pushed with independent
   remote readback, tag/release published, CI36980494688 all7 and native36980536610
   SUCCESS. Canonical bridge preflight independently reviewed, same-packet execute
   RELEASE_OK; public/current/marker exact30693, runningtrue/Nginx2. Installed host
   helper unchanged, no Proxmox/privilege changes. Backend/DEV remain26/schema169/OFF.
   Owner explicitly approved exact24 cleanup after27 instead of26, retaining actual
   rollback25/3d127 and extras359/299. Fresh recovery/cleanup-plan and digest envelope
   PASS; obsolete24 tree and matching staging pair removed, off-host pair retained.
   Independent inventory/status/publichealth PASS, free735452->1463744KiB; managed
   cleanup receipt8c745bd8. Initial stale transcribed rollback/packet-key invocations
   were rejected before deletion; canonical frozen full identities then succeeded.
   Owner requested reusable no-repeat-approval rule; bounded oldest-successful
   frontend-only capacity class added to existing native runbook. Independent cheap
   review identified class/readback gaps; root corrected them, then its remaining
   version/success evidence gap with canonical off-host inspector and accepted
   historical receipt requirements. Root verified the documented invocation on
   original27 artifact and accepts the bounded rule (no privileged query added).
   B navigation has local91
   neighbor tests/lint/typecheck PASS but remains uncommitted; final172/activation
   and authenticated live acceptance are still unresolved, no full-feature GO.

47. Standing bounded frontend cleanup rule/status committed03ecee39, canonical
   master readback matches; primary fast-forwarded clean/PRIMARY_OK, no source
   redeployment. ROOT actual browser compatibilityA27 PASS: normal synthetic
   methodologist login, retained completion100%/active certificate after fullreload,
   OFF workbench direct route dashboard; no businesswrites/mail/AI/newattempts.
   Managed root receipt1efe1be5; screenshotFA7552A8. Test Runner independent B
   navigation local acceptance133files/766tests/typecheck/lint/diff PASS at frozen
   03ecee39+exact6file delta,244.623s. Root read full managed a6e37e23/5c9903f0 and
   append-only ledger, ACCEPTED_LOCAL_ONLY root decision2b0a55d4. No activated build,
   final172/provider/new-flow acceptance implied. Next: explicit build/packet flag
   contract, DEV B172/runtime/live acceptance, then production B and real flow.

48. Controlled B/native and DEV-controller versioned addenda accepted BEFORE
   implementation; immutable27 staysOFF and true allowed only28+. Cheap test
   writers actual nativeRED6failed/11pass, DEVRED17failed/1pass; root implemented
   typed V2/legacyOFF, both artifact inspections/digests, bridge binding and explicit
   artifact-vs-runtime evidence. Unified existing DEV controller prepare gates
   hashed canonical172 receipt/masterCI/exact source/current DEV/free targets,
   changes only3 flags with immediate readback/partial-stop; no second controller.
   Root corrected leaf test fixture receipt shape/error regex (HARNESS_FAILURE),
   independently found V2missing flag and pre-identity flag reads, then regressions.
   Root129PASS/2UnixSKIP/9subtests/Ruff6/quality1010+2200/version28 PASS. New checks
   wired into CI; persistent Test Runner frozen149/2skip/9subtests/quality/Ruff/version
   PASS,165.055s. Root read full reports+actual commands and C1 metadata correction,
   accepts LOCAL_ONLY (cf4d6e93/bb0cafaa/394f21fb; rootdecisiond3bd39be).

49. Root applied approved canonical DEV public169->172 using exact A26 accepted
   compatibility receipt1c40b2ab; no DockerDB/newtenant/resources. Initial QA health
   ReadTimeout retained; canonical existing-provider read-only reconcile26/Free-Hobby
   passed, retry permanentQA PASS/zero businessmutations at10:35:03Z. Authenticated
   OFF404/all3flags false, actual worker1node/DB1/queues/concurrency/pools PASS;
   read-only publicmetadata12FORCERLS/nonbypass/invitationexceptionremoved PASS.
   Managed consolidated3ba51bc4 and earlierB dispositionb18e1547. Candidate28 source
   prepared; production remains API26/schema169/OFF/frontend27. Enabled DEV28/live
   then protected B production/live gates still required. Graph update refused
   shrink22247vs23876, old graph preserved/no force; direct source/test coverage.

50. Final staged diff check caught extra EOF blank lines in both newly staged
   activation test files (earlier unstaged check excluded untracked files).
   Root removed whitespace only; both updated tests49PASS/Ruff/cached-diff PASS.
   Original149 runner receipt remains immutable; managed delta c7986c3a binds
   before/after hashes. Canonical Git-bundled-Bash tenant gate335queries/zero
   violations PASS. No behavior/interface delta or external mutation.

51. Candidate03b64371 pushed to master with independent exact remote readback;
   primary fast-forwarded clean/aligned. CI36998362296/job110810152408 stopped
   new activation step at collection (`scripts` import root absent in API-CWD),
   before DEV preparation. Root preserved failure, added entrypoint regression
   2RED/1PASS, explicitly bound API+repo PYTHONPATH on that CI step; affected87
   tests PASS/1WindowsSKIP. No product/controller/flag/provider delta. Corrected
   exact-SHA CI and enabled DEV/live acceptance remain required.
   Cheap independent reviewer accepted; persistent Test Runner independently87
   PASS/1WindowsSKIP/Ruff/diff (109.665s), managed003ac889/7caec4e8. Root read
   artifacts+actual commands, accepted LOCAL_ONLY; append-only ROOT-C1 corrects
   truncated ledger hash and six-vs-seven selector metadata, no extra rerun.

52. Corrected eb427100 masterCI36999146155/devCI36999932574 all7 SUCCESS;
   existing DEV providers exact28/0172/ON, workerDB1/queues/pools and permanentQA
   PASS. Root live text preview/reload/confirm/receipt-replay/student/mobile PASS,
   created1/skipped1/no duplicate/prior deadline preserved; no notification/AI.
   Owned B API204/404; populated A cleanup500/fk_enrollments_content_release_id,
   child runtime DELETE denied/FORCE RLS. Managed410deac8 NOT_READY; prod unchanged.

53. Root accepted populated-purge addendum BEFORE173/controller changes.
   Initial service-order regression3RED; direct-child SQL was rejected after
   actual ACL evidence and independent review correction. Added exact-tenant/slug
   superadmin EXECUTE-only helper, enrollment-before-release ordering, safe500,
   DEV V3/173 and staged-head173/QA verify extension. Cheap leaf12 contract tests,
   root97 release/admin +2231 unit +quality PASS; independent source review accepted.
   Actual owned Supabase DEV proof12 PASS/rollback/sentinel/ACL/downgrade-upgrade,
   owned namespace absent/public unchanged; managed5e2ccc9d. Newsource/CI/public173,
   normal API A cleanup, QA and production B173/live still required; no manual
   owner data-recovery or public/prod mutation in this repair proof. Persistent
   Test Runner independently2231unit/67controller/1collect-only/quality/scopedRuff
   PASS,187092ms; root read full reports+actualcommands, accepted LOCAL_ONLY,
   report07b698a4/results041f6be8 and ROOT-C1 metadata correction. No source repair.
   Post-repair Graphify AST update refused shrink22321vs23876, old index retained;
   no force/shared upgrade. Direct source/tests remain decisive navigation fallback.

54. Candidate08faf8db pushed master with exact independent readback/projectaccount.
   CI37007566259 six jobs SUCCESS, populated integration DELETE204 then staleORM
   GET200;349PASS/2SKIP/1FAIL. Root source/precedent confirms shared-session cache,
   not new ACL/FK failure. Preserve failedreceipt; move fixture expire_all before
   GET, add actual1RED->GREEN guard/focused24PASS. Runtime173/helper unchanged.
   Exact corrected sourceCI mandatory before DEV173; prod/dev172 unchanged.
   Root2232unit/quality/version28 PASS (release notes literal tag marker restored,
   clearly marked planned/notpublished). Independent Test Runner C1 local24/
   collect1/Ruff5/diff PASS,176810ms; reports a666579e/f79f4db8 read in full byroot.

55. Candidate6fb87c3b CI37009048414 confirmed API DELETE204/freshGET404;
   protected outbox direct SELECT then failed (349PASS/2SKIP/1FAIL, six other
   jobs SUCCESS). Canonical TEST-INFRA-007 applies: pending-before/empty-after
   via existing tenant/course-bound notification adapter, not runtime grants.
   New guard1RED->GREEN/focused25PASS; runtime/helper/ACL unchanged. Exact new
   PostgreSQL CI and DEV173/live cleanup remain mandatory; production unchanged.
   Root2233unit PASS; independent Runner25/collect1/Ruff2 PASS in175050ms,
   full reports/actualcommands accepted LOCAL_ONLY with ROOT-C1 storage/path/
   static-versus-runtime metadata corrections. Original report content preserved.

56. Actual source64/CI37011061920 all7SUCCESS. DEV173 API/worker/Vercel28 ON,
    owned fixture API cleanup204/fresh404/independent absence and retained QA PASS.
    Tag28/GitHubRelease published; protected production37015602293 backend28/173
    exact64/a395 image, controlled4-service ON and native37012329022 exact64/ON
    RELEASE_OK. Worker ping/queues/tasks/concurrency, timers/watchdog/readback PASS.
    Root live production preview/reload/confirm/replay/student-course/mobile PASS,
    created1/skipped1, prior deadline intact, no notifications/AI/voice.
    Normal owned B cleanup500/ProgrammingError, both synthetic tenants retained.
    Product final acceptance NO_GO; pre-cleanup live proof7fc74455 preserved.

57. Root read-only production catalogs/logs/EXPLAIN isolate first reminder helper:
    exact tenant SELECT visible1/rightslug, non-bypass-owner FOR UPDATE false RLS
    filter, all directDELETE/helperEXECUTE grants present. Accepted owner-lock
    repair V1 adds0174 owner-only UPDATE USING with WITHCHECKfalse/no grants.
    Root7 unit RED->GREEN, phase1 RED->GREEN and focused28PASS. Actual frozen
    Supabase DEV non-bypass transaction-only owner gate10PASS at15:34:01Z,
    schema/role/membership absent/publicneutral; managed0887f291. Canonical
    temporary-owner procedure replaces inadmissible SETROLElms_recovery; original
    harness42501 failures preserved. Candidate29 backend-only with native28
    retained. Historical preparation snapshot; subsequent disposition below.
    No manual owner tenant DML or blind DELETE.

58. Root accepted TestRunner2244unit/20schema-routing/quality and QA selector8,
    with append-only actual-timestamp corrections. Source32/tag29/Release/CI
    master37029874084 and dev37030568443 verified; fullCI3804PASS/2SKIP,
    PG17 RLS42PASS. Actual publicDEV174/catalog/ownerlock and existing free
    provider API/worker/Vercel29 PASS; permanentQA untouched, workercontrol and
    browser enabledworkbench PASS (managedbf93a2e4). ReleaseRunner local source/
    packet review accepted; known executor boundary preserved. Fresh signed
    production173restore passed. Protected37032048857 build96a1 SUCCESS;
    execution FAILED exact900s dockerpull before migration/switch. Independent
    production28/64/173/blue/a395/4servicesON readback PASS; retention restored,
    watchdog old identity active. Authenticated registrymanifest PASS;
    delaycause NOT_VERIFIED. No blind retry/guardbypass. Managedstopc9c3eda8;
    production174/live29/normalA-Bcleanup still mandatory.

59. Root delivery/production closeout2026-10-02 completed. Exact96 protected image
    delivered/all12 SHA256 verified; original workflow37032048857 failed-job
    rerun2 SUCCESS without rebuild. Production32/29/green/174/4servicesON,
    ownerlock/RLS/ACL/invitation catalog, workers/timers/health/rollback28 PASS.
    Root live existingreceipt reload/mobile390/studentcourse PASS. Test Runner
    actual API replay/foreign404/student403/baseline preservation and retainedQA
    PASS after13s login pacing; prior429/harness failures preserved, no limiter
    changes. Root normal B then A cleanup204/fresh404, independent10-table absence,
    retainedQA-after100%/history/PDF PASS. Managedroot27de3aed and runner21f1d4bb.
    Release closes text slice only. No voice/STT/LLM/mail/AI/customer/ownerDML/
    billing/DNS/Proxmox/landing change. Original transfer cause NOT_VERIFIED.

60. Isolated ASUS STT pilot2026-10-03: owner-local handoff verified, independent
    venv/public licensed corpus; pinned decoder repair ASR-001 and actual ARM
    CUDA failure ASR-002 retained. Small and large-v3 CPU/int8 compared on the
    same11 hashed inputs; comparison binding/aggregate/duration/decode audit PASS.
    Unit23/scopedRuff/quality1010+2200/release-contract PASS. Cheap reviewer
    identified comparison/audit gaps; root repaired and accepted actual evidence,
    no product-proof claims. Protected timers/listening sockets preserved;
    pre-existing book failure not repaired. ASR quality/production/phone gates
    remain OPEN; text production unchanged.

61. Decoder-policy continuation2026-10-03: same eleven immutable clips/large-v3
    weights, two offline CPU policies measured. Auto15s rejected; Auto30s
    exploratory only, KK WER unchanged/natural mixed not verified. Typed metrics
    separate artificial splice; old raw schema retained; audit/hash/row sums,
    root27+reviewer4 tests/Ruff PASS. Existing DEV identity/course readback only,
    empty departments; twelve recording phrases ready, no business changes.

`WB-TEXT-EXEC -> WB-LLM-INTENT -> WB-DOCUMENT-DRAFT -> WB-CORRECTION`

`WB-ASR-BENCH -> WB-VOICE-INPUT` (отдельный resource/data gate)

| Node | State | Owner / writer / reviewer | Exit / next gate |
|---|---|---|---|
| WB-FOUNDATION | DONE | root / root / independent cheap reviewer |76 pure tests и quality PASS; commit5afa42f |
| WB-TEXT-EXEC | DONE | root; parser/UI cheap leaf writers; root + independent reviewer |138 API tests, web checks, isolated DB gate PASS; flags off |
| WB-DEV-ACCEPT | DONE for29 | root; Test & Evidence Runner local freeze; root external |DEV174/32 ON, owner-lock catalog/workercontrol/permanent QA/browser enabled workbench PASS; prior28 full text-flow proof retained |
| WB-NEIGHBOR-CATALOG | DONE | root / root tooling / cheap reviewer + Test Runner |Read-only DEV12tables/26policies/27FK/9bodies and independent local180 PASS atf0ff29c2; root ACCEPTED_LOCAL_ONLY; no equivalence claim |
| WB-LLM-INTENT | ACCEPTED_LOCAL; owned DB PASS; model/browser/release OPEN | root shared contract/application/budget/DEV; cheap validator/UI leafs and independent reviewer; persistent Test Runner |Independent B/C1/C2:310 API/25 AI-neighbor/34 UI/type/lint/build67/quality/contracts/version/diff PASS; root real owned DEV71/cleanup/public-neutrality PASS. Live model/browser/release remain open |
| WB-ASR-BENCH | MEASURED_CPU_ONLY; decoder30s exploratory; quality gate OPEN | root / root pilot / cheap reviewer |Licensed11-clip comparisons verified; 15s rejected; KK WER unchanged, natural mixed/domain/capacity/CUDA open; recording kit ready; no LMS ASR installed |
| WB-VOICE-INPUT / WB-QR-MIC | NOT_STARTED in LMS | root shared contract; bounded UI/test leafs later |Accepted speech/job/QR impact contract + quality/data/capacity gate, then DEV browser/physical phone proof |
| WB-RELEASE | DONE for text slice29 | root execution/browser/cleanup + Release Runner local review + Test Runner actual API |Production29/32/174 ON; native28 retained; protected rerun2 SUCCESS, normalA/Bcleanup/independentabsence/permanentQA-after PASS; voice/LLM separate |

Write overlap: root owns migration/config/router/registry/purge/docs and DEV gate;
parser agent owns parser+owned tests, UI agent owns panel/client+web tests until
handoff. No concurrent writers to one file; no agents use secrets/external DB.
DEV mutation scope: one randomly named `workbench_<12hex>` schema with synthetic
rows; rollback/cleanup drops exactly that validated owned schema, never public.

Delegation task ledger (exposed token/time counters are NOT AVAILABLE, not zero):

| Task / type | Requested model / effort | Acceptance / correction rounds | Evidence |
|---|---|---|---|
| intent_policy_inventory / independent backend/UI/typed-SQL review |gpt-5.6-luna/medium; observed metadata NOT AVAILABLE |Root cancellation/RLS-context and time-input repairs accepted; runtime proof kept separate |Source-only review; no agent external actions; tokens/time NOT AVAILABLE |
| natural_intent_validator / pure parser and fixtures |gpt-5.6-luna/medium; observed metadata NOT AVAILABLE |Root bounded-output/duplicate-key/relative-deadline and correction-time hardening |23 leaf cases before root DST/inherited-time cases; no providers/DB; counters NOT AVAILABLE |
| natural_intent_ui / UI/client fixtures |gpt-5.6-luna/medium; observed metadata NOT AVAILABLE |Root correction/abort/late-response refinement and HH:MM normalization;34 finalcases |27 leaf,34 root/Runner PASS; exact source one writer; counters NOT AVAILABLE |
| Test Runner / LLM intent local B+C1+C2 |Persistent configured model metadata NOT AVAILABLE |Accepted LOCAL_ONLY after invocation and journal corrections; no source repairs, green matrix not rerun |310/25/34/type/lint/build67; build37.088s, quality5.281s, contract0.487s; turns227.497/75.485/72.709s include context/report overhead; tokens/root-review time NOT AVAILABLE |
| stt_decoder_policy_review / independent source and metric-boundary review |gpt-5.6-luna /medium; observed metadata NOT AVAILABLE |Source accepted after1 metric hardening; phrase kit corrected after1 semantic/traceability review |Reviewer4/root27 network-free tests; root actual sequential decoder comparisons/audits; elapsed/token counters NOT AVAILABLE |
| voice_pilot_contract_review / acceptance inventory + independent source review |gpt-5.6-luna /medium; independently observed metadata NOT AVAILABLE |Root accepted after source corrections; audit hardening completed root |Unit23/root actual CPU11permodel/source hashes verified; elapsed/token counters NOT AVAILABLE |
| root / isolated ASUS pilot and plan |Parent session; observed metadata NOT AVAILABLE |Completed technical baseline; product quality not accepted |Actual CPU/inference/comparison/host checks; runtime failures retained; no production/DB/customer data |
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
| frontend_cleanup_rule_review / independent bounded governance review |Requested gpt-5.6-luna/medium; observed metadata NOT AVAILABLE |Root accepted after2 correction cycles; final evidence-invocation correction verified by root |Read-only exact runbook/helper/controller; reported elapsed approximate3min+2min, exposed counters NOT AVAILABLE; no worker mutation |
| dev_activation_seam_inventory / bounded inventory |gpt-5.6-luna/medium; observed metadata NOT AVAILABLE |Accepted,0 corrections |Existing public schema/provider seams identified; no external access; counters NOT AVAILABLE |
| native_activation_contract_tests / bounded RED tests |gpt-5.6-luna/medium; observed metadata NOT AVAILABLE |Accepted; root added missing-evidence/type/provenance regressions |Actual6RED/11PASS before root code; no external access; counters NOT AVAILABLE |
| dev_activation_controller_tests / bounded RED tests |gpt-5.6-luna/medium; observed metadata NOT AVAILABLE |Accepted with root fixture-shape/regex/single-controller correction |Actual17RED/1PASS; root additional adapter/terminal/schema/identity tests; counters NOT AVAILABLE |
| native_activation_review / independent native then DEV review |gpt-5.6-luna/medium; observed metadata NOT AVAILABLE |Accepted after1 correction packet each; no leaf writes |Native V2missingflag/provenance, DEVidentity-before-flags fixed; direct-source final accepts; counters NOT AVAILABLE |
| Test & Evidence Runner / activation local acceptance + evidence C1 |Persistent configured metadata NOT AVAILABLE |Root accepted LOCAL_ONLY;1 metadata correction, no source repair |149PASS/2UnixSKIP/9subtests/quality/Ruff/version-release/diff;165.055s; C1 commands/hashes, runtime NOT_RUN; token/rootreview counters NOT AVAILABLE |

Точные сроки оценим после вертикального среза и ASR benchmark; обещать голосовой
production за фиксированное число дней без этих измерений было бы неверно.
После полного выполнения плана его факты переносятся в durable contracts и
канонические эксплуатационные документы; временный план удаляется.
