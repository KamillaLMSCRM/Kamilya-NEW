# История решений и доработок движка генерации

Дата сборки: **11 ноября 2026**. Это отдельный канонический журнал изменений.
Его задача — до очередной правки выяснить, делали ли это раньше, где находится
результат, вызывается ли он сейчас и чем подтверждена его пригодность.

Владелец потребовал вести журнал после повторного предложения «сопоставлять
требования источника с уроками и сохранять условия при правке». Такая работа
действительно выполнялась ранее. Ниже зафиксированы конкретные повторения;
объяснение «раньше просто не было правильного задания» недостаточно.

## Как читать и пополнять

- **ПЛАН** — предложение или контракт; реализация и выпуск из этого не следуют.
- **КОД** — изменение существует в Git или локальном файле. Это не доказательство
  его выбора текущей policy и не смысловая приёмка.
- **ЛОКАЛЬНО** — тест или сохранённый модельный ответ. Полный курс, DEV-worker,
  база, интерфейс и production проверяются отдельно.
- **DEV / PRODUCTION** — только по отдельному точному receipt/отчёту; исторический
  readback не объявляется сегодняшней свежей проверкой окружения.
- **ОБХОДИТСЯ** — модуль сохранён, но новая ветвь исполнения его не вызывает.
- **ОТКЛОНЕНО / НЕ ПРИНЯТО / НЕИЗВЕСТНО** — самостоятельные результаты, которые
  нельзя заменять последующим успешным контролем.

Для новой доработки **до редактирования** добавить `CHG-…`: дата/статус; причина;
похожие прежние записи; фактический прежний и предлагаемый новый путь; сохраняемые,
исключаемые и обходящиеся механизмы; файлы/policy; сохранённый пример и проверка.
После работы дописать точный commit или hashes, результат, обращения/токены,
границы проверки и следующий gate. Смена статуса датируется; неудачи остаются.
Правило обязательно в [AGENTS.md](../../AGENTS.md#история-доработок-движка-обязательная-сверка).

Источники имеют разные назначения:

| Источник | Что устанавливает | Чего не устанавливает |
|---|---|---|
| Git commit и diff | Какие файлы менялись, когда и в какой ветви истории | Выпуск, фактическое подключение, хорошее содержание |
| [Журнал дефектов](GENERATION_ENGINE_ERRORS.md) | Наблюдение, причина/гипотеза, сохранённый пример | Полную актуальную историю успешных изменений |
| [Журнал прогонов](TEST_RUN_LEDGER.md) | Конкретный прогон и его границы | Автоматический перенос результата на следующую версию |
| [Handoff](../CODEX_HANDOFF.md) | Точка продолжения, незавершённые действия | Неизменяемую истину всех старых абзацев |
| CodeGraph / Graphify | Кандидаты связей и путь к исходникам | Семантическую полноту курса, отсутствие дефекта, runtime-переключение |

### CHG-L93I — фактический LOCAL итог, 11.11

Нативный approved cash manifest получен SELECT-only restrictedlms_app: approval97abc070-40b1-4136-9dd8-ba65e54a616f, manifestSHA0a1b5b3f65be04a1e94df1d76639585e1365c9a49fbc3d9d364e182ddba0f6ec. Packetef7a5425/working3c73b32e unchanged;91blocks/264typedsegments concatenate exactly. Full record/receipt native-origin-parity-cash.json, no source/customer mutation.

| Run ID | Тип / модель | Fresh IN/OUT; time | Результат |
|---|---|---|---|
| H10-retained-course03/b | source-first retained editor;gpt-6-luna/HIGH |37476/7895;146.547s|NO_GO: unsupported imperative retained. Additional fiscal option claim subsequently WITHDRAWN as non-exhaustive, not another defect.|
| H10-blind-editorial-qa/b | extra read-only critic hypothesis;gpt-6-luna/HIGH |43968/1459|REJECTED:0findings on known wrong imperative; NOT integrated.|
| H10-retained-course04/b | typed-native-origin retained editor;gpt-6-luna/HIGH |44038/7712;142.562s|Independent LOCAL content GO10L30Q/10originalimages once; accountant field now descriptive, not prescribed. No error hints/manual edits.|

Same6L author and10topic automatic plan supplied from saved responses, NOT native checkpoint cache/replay or fresh complete generation. One positive outcome supports testing inDEV, not a causal guarantee or stable semantic detector. Image pixel/render proof,3freshnativecourses/provider/release gates remain OPEN. H10/origin-cash-full-quality-review.md and document-run-inventory-local93-final.json preserve exact artifact hashes/actual usage/UNKNOWN monetary cost and build. Old failed author6L18Q and earlier editor failures are not relabeled GO.

## Реестр обработок документов по модели и версии

**Обязателен с 11.11.2026 для каждого инженерного прогона.** До вызова сохраняется
intent/run ID; после ответа — фактические stage/model/usage/output receipts; после
QA — отдельный смысловой вердикт и связь с предыдущим run на той же редакции.
Failed/unknown/partial/cached попытки остаются. Первая генерация, обработка
сохранённого курса, только review, адресная правка, extraction и replay — разные
типы; их время/токены нельзя смешивать в стоимость одного нового курса.

Поля полного record: document ID/revision/working SHA и packet fingerprint,
engine version/commit либо LOCAL snapshot, policy/prompt/request hash, выбранная
и фактически сообщённая модель, reasoning, provider system/build fingerprint
при наличии, run/parent/stage IDs, fresh/cache/replay, время, IN/OUT/cached tokens,
денежный расход либо UNKNOWN, output/course hashes, число уроков/вопросов/картинок,
ошибки и независимое QA. Идентичность source packet и SHA рабочей редакции — разные
поля. Смена входной редакции отмечается отдельно от изменения движка. Название
модели-алиаса не доказывает неизменность скрытой provider build; недоступный build
ID остаётся UNKNOWN. Не записывать source/OCR, credentials и персональные примеры.

### Снимок доступных прогонов 11.11 — 18 записей

Это **ограниченная восстановленная выборка**, не полный реестр всех прогонов за
месяц и не все557commits. Детали40наблюдаемых стадий, hashes файлов и причины
отсутствующих полей: [исходный снимок](../../.release-evidence/simple-course-restoration-blind-20261111/document-run-inventory.json),
[расширенные метрики](../../.release-evidence/simple-course-restoration-blind-20261111/document-run-inventory-enriched.json).
Первый снимок сохраняет PDF92 PENDING на момент сборки; ниже завершение транспорта
PDF уточнено отдельно, смысловой QA ещё не объявлен успешным. Кэш не новый расход.

| Run ID | Документ | Движок / commit | Фактическая модель / reasoning | Тип | Свежие + кэш | Токены IN/OUT, свежие | Время; результат | Смысловой итог |
|---|---|---|---|---|---:|---:|---|---|
| isolated91-cash | касса | LOCAL isolated91 | gpt-6-luna / high | isolated review | 1+0 |31926/2738|55.0с;8L28Q|UNKNOWN|
| isolated91-pdf | ДИ из PDF | LOCAL isolated91 | gpt-6-luna / high | isolated review |1+0|33706/1123|24.9с;8L24Q|UNKNOWN|
| isolated91-standards | стандарты26 | LOCAL isolated91 | gpt-6-luna / high | isolated review |1+0|17752/2710|54.6с;4L15Q|UNKNOWN|
| H3-cash | касса | LOCAL92 H3 |gpt-6-luna / high|retained edit|3+0|100620/9754|190.3с;8L28Q|FAIL: добавлена неподтверждённая обязанность|
| H3-pdf | ДИ из PDF |LOCAL92 H3|gpt-6-luna / high|retained edit|3+0|112021/11087|214.6с;8L24Q|FAIL: пропуск/новое усиление ответа|
| H3-standards |стандарты26|LOCAL92 H3|gpt-6-luna / high|retained edit|3+0|54663/6458|132.5с;4L15Q|LOCAL GO|
| H4-pdf |ДИ из PDF|LOCAL92 H4|gpt-6-luna / high|failed worksheet|1+0|34053/12608|UNKNOWN; курс не принят|FAIL shape и смысл|
| H5-cash |касса|LOCAL92 H5|gpt-6-luna / high|retained edit|3+0|110718/11745|225.9с;8L28Q|FAIL: обязанность из образца пропущена ревью|
| H5-pdf |ДИ из PDF|LOCAL92 H5|gpt-6-luna / high|retained edit|3+0|134323/13543|257.6с;8L24Q|LOCAL GO|
| H5-standards |стандарты26|LOCAL92 H5|gpt-6-luna / high|retained edit|3+0|58107/7614|151.2с;4L15Q|FAIL: не замечено условие места|
| H6-cash |касса|LOCAL92 H6|gpt-6-luna / high|example guide control|2+1|78646/10379|196.3с;8L28Q|FAIL; guide удалён|
| H7-cash |касса|LOCAL92 H7|gpt-6-luna / high|addressed edit; supplied QA|1+1|38616/7435|139.3с;8L28Q|LOCAL GO, не blind discovery|
| H8-retained-standards |стандарты26|LOCAL92 H8|gpt-6-luna / high|retained five-role edit|3+1|68530/11184|215.5с;4L15Q|LOCAL GO; обнаружил explanation reviewer|
| native91-standards |стандарты26|b71b89f6|gpt-6-luna / high|fresh DEV course|3+0|53970/11127|346.4с;4L15Q|FAIL: условие места|
| native91-pdf |ДИ из PDF|b71b89f6|gpt-6-luna / high|fresh DEV course|3+0|109164/16701|445.1с;8L24Q|FAIL: предотвращение конфликта|
| native91-cash |касса|b71b89f6|gpt-6-luna / high|fresh DEV course|3+0|101083/15979|435.2с;8L28Q/10images|Контент пригоден; source-review дефект истории|
| native92-standards |стандарты26|20a5d281|UNKNOWN¹|fresh DEV course|ожидает checkpoint|UNKNOWN|487.6с;4L15Q|FAIL: «рядом» не задаёт границу территории|
| native92-pdf |ДИ из PDF|20a5d281|UNKNOWN¹|fresh DEV course|ожидает checkpoint|UNKNOWN|699.5с;9L30Q|Транспорт completed; смысловой QA pending|

¹ В DEV92 выбрана Luna6/HIGH; фактическую модель и полный per-stage расход
заполнить по прямому checkpoint/usage readback, не по настройке маршрута. Денежная
стоимость managed Luna для этих прогонов UNKNOWN; её не выводят из API-тарифа.
L/Q у isolated/retained — размер переданного/исправленного курса, не новая генерация.

**Наблюдаемая динамика, без причинной подмены:** на стандартах H3/H8 исправляли
сохранённый пример, но H5 и свежий DEV92 снова пропустили условие. Поэтому
«локальный пример исправлен» не равно улучшению новой генерации. На ДИ H3/H4
не прошли, H5 восстановил обязанность; свежий92 проверяется целиком. На кассе
H6 не помог обнаружению, H7 подтвердил только адресное исправление. Это разные
результаты, а не одна общая зелёная оценка последней версии.

Сравнения дополняются по тому же run ID; новый прогон получает новый ID и parent,
старый не переписывается. Для будущих моделей/версий действует тот же контракт.

### Обновление native92 после прямого readback и QA — 11.11

Оригинальный pending/UNKNOWN снимок выше сохранён в evidence; это дополнение,
а не замена неудачи успехом. Оба job завершились без ручной правки курсов.
Прямой SELECT-only readback ограниченной роли `lms_app` подтвердил модель,
HIGH route fingerprint, пять отдельных стадий и JSONB custody:
[checkpoint receipt](../../.release-evidence/simple-course-restoration-blind-20261111/checkpoint-read92.executed.json).

| Run | Модель фактически | Fresh calls | IN/OUT | Время | Последующий полный QA |
|---|---|---:|---:|---:|---|
| native92-standards |gpt-6-luna/HIGH|5|96239/16104|487.625с|FAIL: условие территории не задано; [полный review](../../.release-evidence/simple-course-restoration-blind-20261111/native-dev92-standards/independent-quality-review.md)|
| native92-pdf |gpt-6-luna/HIGH|5|210439/27935|699.5с|FAIL: не раскрыта превентивная обязанность; претензия к distractor о ставке позднее ОТОЗВАНА как недоказанная; [review с сохранённой первой оценкой и adjudication](../../.release-evidence/simple-course-restoration-blind-20261111/native-dev92-pdf/independent-quality-review.md)|

По сравнению с native91 на той же редакции standards вход вырос53970→96239,
время346.4→487.6с, но ошибка условия снова осталась. PDF вход109164→210439,
время445.1→699.5с; уроков/вопросов стало8/24→9/30, права и ответственность
дополнены моделью, но существенный пропуск сохранился. **Увеличение числа стадий
само по себе не подтвердило улучшение качества.** Третий fresh92 не запущен
после общего провала; существующий PDF завершён, ничего не отменялось наугад.

В PDF QA была также первоначальная претензия к дополнительной проверке; после
сверки §3.1.4 и формулировки «в установленном порядке» она снижена до advisory.
Это исправление оценки аудитора, не установленный третий дефект движка.

### CHG-DOC02 — 11.11: обязательный реестр document/model/version runs

- По указанию владельца добавлены18доступных инженерных прогонов/40наблюдаемых
  стадий, исходный immutable snapshot, расширенные метрики и прямой native92
  readback. AGENTS/PROJECT-CONTEXT закрепляют intent-before-call и результат
  после ответа/QA, разделение fresh/cache/replay и поколения/edit/review/extraction.
- Показаны неудачи и возврат ошибок после локальногоGO; отсутствие provider build
  ID/цены/старого snapshot не заменяется предположением. Новый запуск должен
  появиться здесь до inference, затем дополниться фактической моделью/расходом/
  результатом. Более ранние недели ещё не восстановлены покомпонентно;557Git
  commits — другая инвентаризация, не557генераций.

### Следующий ограниченный контроль, ещё НЕ результат

| Run ID | Документ / вход | Движок | План / модель | Статус |
|---|---|---|---|---|
| scope93-standards-negative-01 | свежий сохранённый native92 standards; workingSHA8febe470…; полный банк без key/body/explanations | LOCAL93A, base20a5d281; новый custody envelope над прежним v16 reader | 1fresh actualgpt-6-luna/HIGH;19444in3798out74.328s; noauthor/editor/targethints | LOCAL обнаружение: q3-2 DEPENDS/FOUND с альтернативной внешней процедурой;14peerquestions не flagged;0sourcequestions. Не freshcourseGO |
| scope93-standards-positive-01 | тот же saved bank, только синтетическая замена недостаточного места на явное inside-settlement условие; не правка native курса | тот же LOCAL93A/runtime snapshot | 1fresh Luna6/HIGH;19452in3432out;67.25s | PASS контроль:0proposals/15UNIQUE, нет ложного DEPENDS; H9/controls-positive/d/result.json |
| scope93-pdf-negative-01 | полный saved bank свежего native92 PDF; workingSHAea0b2408…; без key/body/explanations | тот же LOCAL93A/runtime snapshot | 1fresh Luna6/HIGH;48819in5362out;101.438s |30UNIQUE/0question-proposals;1source-question о приоритете начальников не требуется для реальных карточек; прежняя претензия к rate option ОТОЗВАНА как недоказанная; H9/pdf-rate-source-adjudication.md |
| prose93-pdf-negative-01 | полные9текстов fresh92 PDF, без тестов/ключей; тот же approved workingSHAea0b2408… | LOCAL93B role candidate; прежняя editorial schema/compiler | 1fresh Luna6/HIGH;52107in5348out;101.562s | FAIL: не найден пропуск профилактики конфликта; добавления о расписании/ознакомлении не приняты как доказанные дефекты; H9/prose-controls/c/result.json; в worker не переносить |
| prose93-pdf-positive-01 | ранее принятые8текстов H5 PDF; тот же approved source | тот же LOCAL93B role candidate |0calls/0tokens|NOT_RUN: negative не подтвердил гипотезу; дальнейший расход на эту роль отменён|
| unit93-standards-II-01 | буквальный source block IIкатегории + его I-category reference/общий context; original workingSHA8febe470… не меняется | LOCAL93C source-view experiment, base20a5d281 | модель не вызвана;0model tokens; остановка до selected-unit/request записи при чтении provider config | PRE_MODEL_FAILED DevReleaseBlocked; не семантический результат и не неизвестный модельный ответ |
| unit93-standards-II-02 | тот же источник/блок/роль; предыдущий model request не отправлялся | тот же LOCAL93C; immutable harness/output ID, расширенная safe диагностика |0model calls/0tokens|PRE_MODEL_FAILED: provider config GET TimeoutError;001request отсутствует|
| unit93-standards-II-03 | тот же буквальный unit и роль; рабочая редакция не меняется | LOCAL93C; тот же approved DEV credential из уже проверенного immutable worker env, только RAM/SSH; без Render GET |0calls/0tokens|PRE_MODEL_FAILED: root передал список в helper, ожидающий packet; ValueError до001request; credential read прошёл, модель не вызывалась|
| unit93-standards-II-04 | один буквальный II-category block +3 точных supporting blocks;5644source characters; исходная редакция неизменна, старый курс/замечания в payload не входят | LOCAL93C pure simple_source_unit module SHA842c876b…; harnessSHAa583164f…; base20a5d281 |1fresh gpt-6-luna/HIGH;12549in1680out;34.0s|4вопроса/ключи/объяснения без установленной ошибки; урок NOT_YET_ACCEPTED: не раскрыта отсылка к действиям при передаче; independent review; H9/unit-controls-04/d/result.json|
| unit93-standards-II-05 | тот же буквальный unit + целый текущий урок/4вопроса из unit04; без списка дефектов/целей правки | LOCAL93C ordinary editor role, тот же selected-source builder/schema |1fresh gpt-6-luna/HIGH;14054in1986out;40.406s|LOCAL_UNIT_PASS после independent QA/adjudication; модель сама раскрыла зависимости;1L4Q,IDs/keys сохранены; H9/unit-controls-05/d/independent-review.md; не полный курс/DEV proof|

Evidence последнего контроля: [intent](../../.release-evidence/simple-course-scope93-20261111/controls/d/intent.json),
[result](../../.release-evidence/simple-course-scope93-20261111/controls/d/result.json),
[8-file source snapshot](../../.release-evidence/simple-course-scope93-20261111/source-snapshot.json).
Actual native92 metrics/model/QA в [новом неизменяемом снимке](../../.release-evidence/simple-course-restoration-blind-20261111/document-run-inventory-final-native92.json):18runs/50observedstages;
первый pending snapshot сохранён. Изолированный LOCAL93control — девятнадцатая
обработка, зарегистрированная отдельно до inference, без новой генерации курса.

## Подтверждённые повторения и места утраты поведения

| Семейство | Прежняя реализация/наблюдение | Что произошло позже | Состояние на 11.11 |
|---|---|---|---|
| Источник → действия → уроки | Октябрьские планы; ENG-025, ENG-042; `2370a35a`, `df91ad9e` | В новом simple-пути старые atomic/compact/focused проверки не вызываются | Сам подход повторяется; сохранённый код не удалён, но обходится |
| Урок отдельно от теста | ENG-006/007, `dc8846ba`, `5467e5ae`, focused `4a3ec606` | Simple V1 снова проверял полный курс совместно | Возврат к разделению в локальном V2; ещё не принят |
| Условие/носитель/ветвь процедуры | ENG-008, ENG-041, ENG-052 | Новые модели повторили перенос или потерю условия | DEV91: вопрос без нужного места; PDF-правка усилила действие без области применимости |
| Составная обязанность | Предотвращение и сообщение разбирались в focused-пути | Общее ревью приняло только сообщение | В ДИ DEV91 и первом retained92 пропущено предотвращение конфликта |
| Актуальный текст против истории | ENG-012, ENG-043; текущие targets/доказательства в `df91ad9e` | Simple V1 снова передал исходные цитаты решений рядом с исправленным текстом | В V2 исключены заменённые quotes/offsets; причины решений и исходный аудит сохранены |
| Незакрытое замечание не пропадает | ENG-002/007/044/047/053, revision-bound retention | V2 собирает вопросы двух reviewers, но наружу берёт список editor | Открытый риск по исходникам; не объявлен подтверждённым случаем потери в живом задании |
| Реальная регистрация нового пути | ENG-021: managed admission выбирал старую policy | Simple был разрешён снаружи, но не во внутреннем owned-stage | `b71b89f6`: общий точный guard + тесты настоящего seam, без model calls |
| Форма/пример ≠ универсальная обязанность | Общие source-scope инструкции существовали | Retained cash92 назначил действие бухгалтеру из примера формы | Не принято; не выдавать за новую неоднозначность для клиента |
| Хороший сохранённый ответ ≠ стабильная генерация | Ранние эталонные/локальные курсы | Следующая native генерация дала иные ошибки | Каждый новый путь требует своих полных курсов; выбранный удачный ответ не доказательство повторяемости |

### Где проходит граница нового и старого пути

Проверено по исходникам текущей рабочей копии; это не отдельный runtime-readback:

```text
ordinary API admission → stored review_policy → generate_v3_course_from_corpus
  simple v1/v2 → generate_simple_course → simple controller
  other practical policy → generate_practical_course
      focused v36 → run_focused_cycle
      coherent v35 → run_coherent_editorial_cycle
      autonomous/joint → run_autonomous_editorial_cycle
```

См. [service.py](../../apps/api/app/modules/ai/v3/service.py),
[simple service](../../apps/api/app/modules/ai/v3/simple_course_service.py),
[practical service](../../apps/api/app/modules/ai/v3/practical_service.py).
В исходниках старые ветви сохранены. **Переключение на simple — обход этих
механизмов, а не их перенос.** Историческая совместимость старых jobs не доказывает,
что новые jobs получают их защиту. Не следует механически вернуть весь каскад:
сначала явно выбрать необходимые свойства, проверить их на сохранённых случаях
и измерить цену нового реально вызываемого пути.

## Существенные этапы с проверкой смысла и границ

### CHG-ARCH01 — архивная незавершённая линия LOCAL и Graphify-план

- Исходный запрошенный владельцем план найден в сохранённом worktree:
  [IMPACT_ADDENDUM_V88_V9.md](<C:/Kamilya New/Kamilya-NEW/.worktrees/cabinet-release-20261018/docs/product/contract-modules/lesson-cycle/IMPACT_ADDENDUM_V88_V9.md>).
  Снимок SHA256 `2dc4a694612f7b19365529ccae267fff96867e31274b933b8cf42750a4d3c4e1`.
- Его собственные записи 27–28.10 прямо говорят: Graphify-derived plan **не
  завершён**, LOCAL discrete engine ещё не подключён к native worker,
  три полных курса/67семейств/16неоднозначностей, DEV DeepSeek и production OPEN.
  Значит, нельзя считать прежний план выполненным по большим номерам локальных
  итераций или числу зелёных тестов. Ссылки на AI-QUALITY-101/116–120 и старый
  `ERRORS.md` — адреса архивных доказательств, не текущие исправленные симптомы.
- Этот архив содержит незакоммиченные попытки; они **не представлены полностью
  Git-реестром**. Их наличие сохранено отдельной ссылкой, а не потеряно при смене
  worktree. Клиентские/архивные данные при этой сверке не изменялись.
- Сохранённый [разбор MICRO R14](<C:/Kamilya New/Kamilya-NEW/.worktrees/cabinet-release-20261018/docs/testing/2026-10-29-microcredit-r14-token-analysis.md>)
  восстанавливает400учтённыхвызовов,7402839input/652708output,8055547всего,
 5828секунд,26уроков/73вопроса; RUNNER_FAILED, не принято. Числа взяты из отчёта
  по400provider-records; текущей повторной сверки каждого raw record не было.
- [Историческое сравнение расхода](<C:/Kamilya New/Kamilya-NEW/.worktrees/cabinet-release-20261018/docs/testing/2026-10-30-generation-token-comparison.md>)
  отличает сентябрьские105свежихGLMвызовов+52replay от R14. Оно уже фиксировало:
  весь набор фактов выбирается при помещении в лимит, а semantic narrowing без
  проверенного блока/связей возвращается к прежнему контексту. Наличие selector
  не означало корректное создание блоков или экономию в worker. Это ещё один
  прежний случай «реализация есть, её эффективное использование не доказано».
- В архивном handoff есть DeepTutor/Gemini/NotebookLM-сравнения и отдельный
  `.release-evidence/deeptutor-eval-20261030/REPORT_RU.md`. Это эксперименты,
  не интеграция в production: разные модели/адаптеры/источники, неполные и ошибочные
  запуски не дают честного A/B победителя. Они указаны для дальнейшего поиска;
  полная переоценка этих внешних движков в нынешнюю проверку не входила.

### CHG-H01 — 19–20.10: полнота правил, списков и условий уже была целью

- Код: `32e3afa2`, `fb9a8343`, `d616ff9e`, `0338f3b9` и соседние commits в полном
  реестре ниже. Названия и diffs устанавливают существование изменений, не успех.
- Исторический план `docs/plans/2026-10-19_lombard-generation-quality.md` доступен
  через `git show 32e3afa2:docs/plans/2026-10-19_lombard-generation-quality.md`.
- Уже требовались исходник → уроки **и** вопросы, независимое сравнение,
  свежая генерация и браузер. Отсутствующий тогда Graphify не был проверкой смысла.
- Вывод: нынешнее предложение «сравнить источник с уроками» не новое изобретение.

### CHG-H02 — 30–31.10: смысловые блоки, зависимости и V3

- `0ad011cc`: исторический root-cause plan описывает потерю управляющего условия
  при разбиении факта между блоками. Предложены зависимости соседних блоков/явное
  восстановление governing scope; это план, не подтверждение выпуска.
- `5dd36ad0`: historical quality plan различает полноту обучения и вопросы,
  сохраняет определения, исключения и ссылки; семантические gates оставались OPEN.
- Оба файла извлекаются `git show <sha>:docs/plans/2026-10-30_generation-engine-root-cause-and-plan.md`
  / `...generation-engine-quality.md`; commits входят в предков текущего HEAD,
  даже если файлы отсутствуют в текущем checkout.
- `f41c9aab` — V3 contracts/prompts/engine; `08349a32` — pipeline/persistence;
  `a915ea50` — транзитивные зависимости и передача ссылок/замечаний.
- Не смешивать существующую ветку другого агента с её фактическим объединением:
  `feat/v3-universal-cogen-assessment-bank`, `fix/generation-quality-audit-20261030`
  доступны локально; ancestor-состояние каждой фиксации приведено отдельно.

### CHG-H03 — 03–04.11: раздельная проверка и стоимость повторов

- V3 live/DEV запись в `ERRORS.md` описывает 36 принятых вызовов/20reviews,
  отсутствие готового курса и повторную передачу источников. Это отрицательное
  свидетельство, которое нельзя закрыть локальными 4948+47 тестами.
- `2370a35a` добавляет `practical_atomic_audit`/`practical_lesson_cycle`.
- [План 04.11](../plans/2026-11-04_practical-engine-release.md) уже описывает
  самостоятельный вопрос, prose/source-first coverage и разбор замечаний до правки.
- `dc8846ba`, `3a721225`, `5467e5ae`: разделение вопроса/текста, правильности ответа
  и полноты курса. Результат сохранённого P16-контроля не равен трём DEV-курсам.

### CHG-H04 — 05.11: типы замечаний, частичная правка и потеря первоначальной цели

- ENG-005: один источник в нескольких уроках ошибочно отвергался; связь many-to-many.
- ENG-006/007: покрытие не равно неверному ответу; несвязанная quiz-правка не может
  закрывать первоначальный учебный пробел.
- ENG-010/018/019/020: нельзя свести связное обучение к буквальным фразам;
  сжатие/смена роли может потерять обязанности и общие инструкции.
- P30 `e9c9571d` → `e1b5b945`/`002d7908` → coherent P31 `a416116c`.
- ENG-021: implementation существовал, но managed DEV admission выбрал v29;
  `c450f1af` исправил маршрут. Наблюдение v31 stage/save — доказательство маршрута,
  не содержательной полноты всех курсов.

### CHG-H05 — 06–07.11: согласование источника, части и иллюстрации

- `bad2df02`: человеческое одобрение рабочей редакции перед генерацией.
- ENG-027/029: модельное замечание об исходнике не должно теряться при косметической
  правке или неполном решении. Исправление исходника не даёт права выдумывать норму.
- `60681e1e`: выбор частей документа и встроенных иллюстраций; оригинал/рабочая
  редакция/хэш/approval/активы остаются разными сущностями.
- `87c423e8`, `ae11c4d3`: сохранённый ответ и его точная stage identity для replay.
- Границы исторической приёмки и оригинальных картинок описаны в старом handoff;
  это не сегодняшняя повторная проверка опубликованных клиентских данных.

### CHG-H06 — 09.11: единое текущее редакторское доказательство

- `d28d3cc4`, `1506f368`, `27391ca9`, `7b17e42d`: autonomous/joint review,
  объединение наблюдений, доказательства по текущим targets, дедупликация вопросов.
- ENG-040/043/044/045/047: исправленный текст мог проверяться по старой претензии;
  частичный ответ мог отбросить хороший остаток; неподтверждённая претензия могла
  повторяться; ремонт доказательства мог стереть актуальное доказательство.
- `df91ad9e`: operative-list guidance/актуальные targets; `7bc6f129`, `947afed9`
  уточняют решения и сохранение. Модули остались, simple-путь их не вызывает.
- Их собственные старые дефекты и расход — основание не возвращать каскад вслепую,
  но отказ от каскада требовал явной матрицы сохранения нужного поведения.

### CHG-H07 — 09–10.11: буквальный источник и focused v36

- `d58b9040`: literal-source/coherent current review после ошибочной производной карты.
- ENG-049/050: родительские/дочерние команды правки конфликтовали; производная карта
  сохраняла ошибочное ограничение даже после проверки.
- `4a3ec606`: focused v36; отдельные source/action/object и key-blind проверки.
- ENG-052: перенос условия между объектами/ветвями и смешение предотвращения с
  сообщением. Локально выбранные исправления не доказали стабильную blind discovery.
- ENG-053: у потерянного замечания была привязка к текущей ревизии; этот инвариант
  нужно явно переносить при новой orchestration.

### CHG-H08 — 10.11: публикация двух новых клиентских курсов с ручной QA

- Исторический handoff production88 фиксирует два новых курса PDF и кассы,
  оригинальные10картинок и неизменность старой когорты. Это поставка, но не полная
  автономность движка: отдельные финальные правки выполнены вручную с разрешения.
- ENG-055: широкий кассовый distractor пережил whole-course review.
- Клиентские опубликованные курсы не используются как разрешение менять их при
  текущем эксперименте. Сравнение с эталоном не должно скрывать его первоначальный
  пропуск двух перечней городов и последующее исправление.

### CHG-H09 — 10–11.11: авторский null-контракт и JSONB custody

- `a23b4f30` / 0.11.89: null-only extensions, source decisions в editor,
  адресные правки по сохранённым замечаниям с сохранением хороших частей.
- Исторический авторский ответ был получен, но tuple/list изменились в JSONB.
  ENG-056; `16504ca0` / 0.11.90: каноническая JSON-представимость и ограниченный
  owned replay без повторного запроса. Это техническое исправление, не новое
  доказательство обнаружения смысловой ошибки.
- Приёмка production90 имеет отдельный отчёт в worktree
  `engine-author-transport-20261110/docs/testing/2026-11-11-engine90-production-acceptance.md`.
  Текущие локальные92изменения в production90 не включены.

### CHG-H10 — 11.11: outline-прототипы отклонены, simple V1 подключён

- ENG-057: outline → author → combined editor потерял действие при передаче смены;
  разделение review/editor не исправило scope, а outline повторно переподчинил его.
- Прототипы сохранены в `.release-evidence/simple-course-editor-20261111/local-r2..r4`;
  они отклонены, не удалены из истории и не объявлены рабочим выпуском.
- `fb0fecae`: author непосредственно из утверждённого источника → reviewer → editor,
  без model outline и старого semantic cascade. Подробные локальные расходы/правки:
  [отчёт](2026-11-11-simple-course-editor.md).
- **Что сохранено:** source custody/approval, null-normalization, worker/persistence,
  proposed provenance, lease/cold replay. **Что обходится:** старые focused/atomic/
  joint проверки. Перенос их существенных свойств не был доказан общей матрицей.

### CHG-H11 — 11.11: реальный transport seam и DEV91

- Первый native job `fb0fecae` завершился до курса: наружный transport признавал
  SIMPLE, следующий owned-stage gate — нет. Отрицательный job сохранён.
- `b71b89f6` разделяет общий exact guard между слоями; тестируется собранный путь
  всех стадий, cold replay, отрицательные source/owner/request/policy случаи.
- В DEV91 получены три полных курса: **4L15Q**, **8L24Q**, **8L28Q/10картинок**;
  **9 вызовов**, **264217 input / 43807 output**, reasoning HIGH. Денежная стоимость
  managed Luna **UNKNOWN**, распознавание исключено.
- API/source/route/custody/assets readback выполнен; общий semantic GO отсутствует:
  ENG-058 фиксирует место в вопросе, часть обязанности и устаревшее слово.
- Источник evidence `.release-evidence/simple-course-editor-nativefix-20261111/`.

### CHG-L92A — 11.11: раздельные bodies/cards и текущие решения, ЛОКАЛЬНО

- Основание: CHG-H03/H06/H07, ENG-043/052/058. Это повтор существующего принципа
  в другом controller, а не новое решение по существу.
- Новый V2 оставляет четыре роли: author, body review, card review, editor.
  Реальный quiz title виден постоянно; отсутствующий контекст нельзя брать из
  соседних вопросов/скрытого урока. Старое слово из replaced quote не считается
  текущим источником; все интерпретационные причины решений сохраняются.
- Файлы: `simple_course_editor_v2.py`, policy/router/service, shared stage guard,
  `practical_author_transport.py`, scoped tests. V1 не переписывается.
- Retained standards:3вызова **54663/6458**, исправлены только prompt/explanation,
 4текста/14соседних вопросов/варианты/ключи сохранены; независимая локальная приёмка.
- Retained PDF:3вызова **112021/11087**, составная обязанность снова пропущена,
  правка ключа усилена без условия пригодности; **НЕ ПРИНЯТО**.
- Retained cash:3вызова **100620/9754**, устаревшая формулировка не вернулась,
 10активов сохранены,0sourcequestions; добавлено неподтверждённое действие бухгалтера
  из примера формы; **НЕ ПРИНЯТО**. Это ошибочная нормативизация примера, не новый
  вопрос владельцу исходника.
- Root и первый независимый аудитор тоже пропустили standards scope; другой
  cash scope вывод отозван после сверки реально видимого quiz title. Нельзя считать
  все замечания root/агента безошибочным эталоном.
- H3=`.release-evidence/simple-course-editor92-20261111/`. Не применено к native
  курсам, не commit/deploy. Никакого нового paid DeepSeek вызова.

### CHG-L92B — 11.11: source worksheet внутри того же review, ЛОКАЛЬНО/НЕ ПРИНЯТО

- Основание/повтор: CHG-H01/H03/H06/H07/L92A. Старый принцип source-first coverage
  возвращён в новый4callcontroller; отличие — явный worksheet по source blocks,
  независимым action/actor/condition и точным excerpts, вместо списка впечатлений.
- Что добавлено: `simple_course_content_review_v2.py`; регистрация нового schema
  в `response_contracts.py` и существующем `simple_stage_allowed`; role tests,
  actual owned seam/cold replay. Нет нового critic call/loop или semantic regex.
- Structural scope/source/excerpt проверки не доказывают entailment. Все blocks
  могут быть формально перечислены, а обязанность всё равно ошибочно признана taught.
- Финальный локальный API unit **7943 PASS /1skip/7warnings**, baseline **1004/2174**;
  focused transport/controller/source **102 PASS**, critical-journey gate **6 PASS**.
- H4=`.release-evidence/simple-course-editor92-worksheet-20261111/retained92/edit/c`:
  один известный ответ Luna **34053 input /12608 output**,229source refs учтены
  без пропусков/дублей,31group/89components. Ответ отвергнут `_ResponseDecodeError`:
  один row помечен context, но содержит component. Editor не запускался; повторов нет.
- Даже до structural rejection ответ признал избегание конфликта taught по
  фразе о сообщении; требование содержания не выполнено. Следовательно, раздувание
  отчётности само по себе не решило ошибку. Сохранять результат отрицательным.
- Открыт отдельный custody risk: reviewer-only source question может отсутствовать
  в финальном editor-only списке без явного disposition. Установлено по коду,
  но не воспроизведено как реальная потеря в native job. Не смешивать с подтверждённым
  старым ENG-053. Изменения не приняты, не выпущены; сначала завершить историческую сверку.

### CHG-DOC01 — 11.11: обязательная история перед новой доработкой

- Запрос владельца: фиксировать каждую доработку и сверять новые предложения с
  прежними реализациями, чтобы не повторять одинаковые попытки под новыми словами.
- Добавлены этот журнал и ссылки/обязательный preflight в `AGENTS.md` и
  `docs/PROJECT-CONTEXT.md`; текущая задача — документация и проверка связей.
- Не меняет runtime/policy/client data/бюджеты. Снимок всех доступных Git-изменений
  приведён ниже, локальные незакоммиченные попытки L92A/L92B отмечены отдельно.
- Графовая сверка и проверка ссылок приведены после автоматического реестра.

## Полный доступный Git-реестр

### CHG-L92C — 11.11: перенос подтверждённых свойств в simple, LOCAL ПРОВЕРЕН

- Основание: новый запрос владельца восстановить удачные наработки по этой истории;
  CHG-H03/H06/H07/H09/L92A/L92B, ENG-042/043/053/058. Два независимых аудитора
  сверили код и доступные raw artifacts. Устойчивого автономного обнаружения
  составной обязанности в старом движке не доказано; это не объявляется «потерянной
  гарантией», которую достаточно включить.
- **KEEP:** прямое авторство из полной утверждённой редакции; текущие решения и
  причины без replaced quotes; source/actor/route custody, JSONB/cold replay,
  оригинальные активы и исторические policy. Никакой смены reasoning/model/provider.
- **RESTORE:** узкий content-versus-question edit authority и сохранение peer
  text/questions/media из `practical_source_editor._restrict`/revision compiler;
  журнал явного решения каждого reviewer source-question, привязанный к source/
  draft, вместо его молчаливого исчезновения в editor-only списке.
- **REUSE:** сохранённое prose-only literal source→lesson задание из
  `engine-author-transport-20261110/.release-evidence/source-alias-r73/blind-editor91-r2/c/001.request.json`.
  Оно обнаружило конкретное пропущенное направление обращения клиента; это один
  положительный control, не общая гарантия и не source-only reader до знакомства
  с курсом. Сохраняется исходник как authority и domain/severity/basis из существующего
  editorial-review контракта; сравнение с уроками отделено от question cards.
- **DROP from active V2:**229block worksheet, уже дважды не подтвердивший нужное
  смысловое поведение; сохранить его файлы/raw/снимки как отклонённый эксперимент.
  **BYPASS:** прежний полный каскад и отдельный source-reader эксперимент, улучшение
  которого не подтверждено. Не добавлять ещё один общий critic или retry-loop.
- Файлы: simple V2 orchestration, отдельный versioned revision-contract/merge helper,
  response-contract registration/actual owned-stage gate, focused tests. V1 не меняется.
- Перед правкой сохранить точный исходный LOCAL92snapshot. Регрессии: quiet editor
  не теряет reviewer source-question; явное разрешение имеет source/draft/disposition;
  content-правка не переписывает quiz, question-правка не переписывает prose/peers;
  исходные10images/ключи/IDs/order сохранены; неверные refs/stale fingerprints reject.
- Модельные сохранённые контроли: PDF compound duty+scope, standards location,
  cash current history/example roles/media; в blind discovery не передавать root
  target hints. Адресный repair ранее зарегистрированного замечания маркировать
  отдельно, не выдавать его за blind discovery. Новые полные курсы только после
  сохранённых контролей; exact DEV/DeepSeek/protected production остаются отдельными.
- Результаты/токены/новые hashes: ещё не получены; дополнить после проверки.

### CHG-L92D — 11.11: перенос границы «образец формы / действие», ОТКЛОНЁН ПО КОНТРОЛЮ

- Основание: CHG-H05/L92A/L92C, ENG-034/035/058. Старый preparation
  `_VISION_REVIEW_TASK` различает печатную строку подписанта, пустое поле и реальную
  подпись/выполненное действие. Новый prose reviewer получил literal OCR, но не эту
  границу: сохранённый H5cash3calls110718in11745out оставил неподтверждённое действие
  бухгалтера. Вход проверен локально: OCR/пометки примера присутствуют; гипотеза
  потери текста отвергнута. Полный source payload с данными примеров не включать
  в распространяемый отчёт; использовать только хэши/счётчики/нормативные выводы.
- Изменение: перенести existing example-authority distinction в prose-review role
  при наличии исходных illustration markers. Не игнорировать изображения вообще:
  обязательные поля/действия, явно заданные инструкцией, остаются обязательными.
  Печатная роль/строка подписи на образце сама не назначает действие организации.
- KEEP: source/course/approved meaning и остальные роли/схемы. Это не новая
  source-interpretation regex, не новый critic и не переиндексация исходника.
- Контроль: повторить только изменённое prose review и адресный editor; прежний
  card review разрешено воспроизвести лишь при точном равенстве request bytes/
  source/draft/schema. Сохранить отрицательный H5cash, явно учесть новые обращения.
  PDF/standards без image markers должны сохранять прежние review bytes.
- Состояние: локальная гипотеза переноса, не доказанное исправление; выполнить
  сохранённый контроль и независимую сверку до DEV. Новые три курса не запускать
  ради проверки этой одной ошибки.
- Результат11.11: H6 вернул те же неполные выводы; accountant assignment остался.
  2freshcalls78646in10379out плюс точный replay прежнего card review,0новыхвызовов
  на replay. Дополнительная инструкция снята из активного кандидата; её точный
  controller/raw сохранены. Повторное промпт-подстраивание этого случая прекращено.

### CHG-L92E — 11.11: восстановление key-blind данных и отдельного объяснения, LOCAL ПРОВЕРЕН

- Основание: CHG-H03/H07, `practical_option_predicates` из старого focused пути;
  отдельная проверка объяснений уже была в истории `906b5a11`. Текущий simple
  card payload фактически включает `correct_index`, `explanation` и author refs.
  Это проверено на сохранённом запросе H5standards002; проверяющий не работает
  только с видимыми ученику данными. Новый повторный H5standards3calls58107in7614out
  снова не заметил пропущенное место l3q2, поэтому общий заявленный standalone brief
  недостаточен при подсказанном авторском ключе. Нельзя считать это гарантированно
  единственной причиной всех смысловых ошибок.
- RESTORE: существующие `option_predicates_messages/format/interpret` без авторского
  ключа, объяснений и refs в независимых item payloads; добавить реально видимый quiz
  title к prompt, чтобы не терять законный контекст. Исходник остаётся полным.
- KEEP: source→prose review; точный source/draft, scoped editor и retention.
  Объяснения не удаляются из проверки: отдельный bounded explanation-review
  использует исходник и вопросы/ключи/объяснения, его результат не поступает назад
  независимому solver. Объединить текущие наблюдения перед адресным editor.
- Новый путь имеет5содержательных вызовов на новый курс: author / prose / independent
  options / explanations / editor. Это фиксированные роли, без каскада повторных
  критиков и без подбора модели; HIGH остаётся. Увеличение с4до5обосновано разделением
  непересекающихся видимостей, а не правилом «повторить ещё раз».
- До модели: RED payload-leak regression; exact five-phase owned transport/cold
  replay и forged-policy/source/request negatives. Сохранённые неизменившиеся
  requests можно replay лишь при полном byte/schema/fingerprint equality; это не
  свежая генерация. Старые policy и их checkpoint identity не переписываются.
- Файлы: новый тонкий wrapper над existing key-blind primitive, V2 controller,
  stage guard/progress и mandatory regressions. Никаких новых semantic regex.
  Критерий: независимый solver не получает hidden key/explanation/body; модельные
  выводы ещё требуют независимой содержательной проверки, не становятся truth.

### CHG-L92F — 11.11: незакрытая независимая проверка → actionable draft, LOCAL ПРОВЕРЕН

- Сверка: CHG-L92C/E уже сохраняют молчание editor и findings без поля, но новый
  key-blind wrapper сохраняет UNDECIDABLE только в nested diagnostics. Независимый
  аудит нашёл реально не подключённый consumer: materializer читает proposals,
  source questions и unapplied findings, но не independent unverified observations.
- RESTORE тот же инвариант retention, без новой модели: source/draft-bound
  UNDECIDABLE становится адресным ordinary editorial issue с question_id.
  Это не неоднозначность исходника и не автоматический запрет создать черновик.
  Последующая правка вопроса не считается разрешением без проверки; retain
  reviewed-draft fingerprint и final question fingerprint отдельно.
- До исправления: добавить actual native service/five-owned/cold replay regression
  с quiet explanation/editor и одной UNDECIDABLE, показать отсутствие issue.
  Затем consumer с проверкой source/draft/target custody и повтор той же регрессии.
- Файлы: simple_course_service и owned-transport/service tests. Никаких новых
  prompt/semantic guard/cascade/provider или клиентских изменений.
- Отдельное замечание аудитора о guide L92D не принято: он намеренно удалён после
  отрицательного H6. Это не потерянная успешная наработка, повтор запрещён.

### CHG-L93A — 11.11: вернуть DEPENDS / контрпример самого вопроса, ПРЕДЛОЖЕНО

- Сверка CHG-H03/H06/H07/L92E, ENG-058 и фактических callbacks: nativeDEV92
  standards cf2b111d завершён487.625s/4L15Q, но вопрос02e18b14 использует «рядом
  с офисом» вместо условия одной территории; first-workday ответ зависит от
  неуказанной границы. Author/reviews/editor завершились без proposals/changes.
  H8retained успех не обобщился; новой приёмки нет.
- Фактический пробел: key-blind `practical_option_predicates` доказывает один
  compatible case, но не представляет альтернативный совместимый случай с другим
  результатом. Старый `practical_review` уже содержит UNIQUE/DEPENDS/AMBIGUOUS/
  UNKNOWN + typed counterexample и tested whole-bank режим v16. Это найденный
  механизм, не новый лозунг «проверь внимательнее» и не обещание стабильности.
- RESTORE в существующей одной question-review роли: старый whole-bank standalone
  contract/reader/interpretation, с реально видимым quiz title, скрытыми ключами,
  объяснениями, body и author refs. Вопрос о требуемой процедуре проверяется по
  всем source-permitted cases, совместимым с указанными фактами. Generic/may
  вопрос сохраняет existential semantics; не требовать универсальности от него.
  Никаких regex для слов «рядом», названий городов или кассовых операций.
- KEEP prose/explanation/editor, scoped merge/UNVERIFIED retention/current source/
  approved reasons/custody. Пять ролей, без шестого критика и каскада повторов.
  СтарыйV2 и его jobs сохраняют прежнее поведение; новый путь получает отдельную
  V3policy/group identity. До native: exact saved negative и explicit-scope
  positive, generic broad/narrow cash controls; сравнить обнаружение и отсутствие
  ложных претензий. Сначала zero-inference producer/owned/cold replay proof.
- Custody-уточнение до реализации: старый v16 echo содержит только source fingerprint
  и IDs вопросов; сырой ответ с теми жеIDs и другой формулировкой сам по себе не
  отличим. Thin wire envelope добавляет **только bank_fingerprint** и собственное
  имя схемы; semantic поля/старый strict compiler не меняются. До компиляции
  сверяется текущая visible-bank projection, envelope снимается и вызывается
  прежний v16 interpreter. Request-hash journal остаётся обязательным. Это не
  новая semantic эвристика; stale-bank negative обязателен до платного вызова.
- Состояние: локальный монитор batch остановлен до cashPOST; уже запущенный
  PDF bba11768 продолжает worker, GET-only observer26571, без повторной генерации
  и изменения failed standards. После общего провала не отправлять третий курс
  на том же заведомо недостаточном reader. Это гипотеза переноса до saved proof.

### CHG-L93B — 11.11: контрпример к положительному покрытию уроком, ПРЕДЛОЖЕНО

- Сверка CHG-H06/H07/L92B/C, ENG-041/052/058 и actual native92 PDF prose reply:
  summary сгруппировал3.11–3.12, назвал только сообщение о конфликте и объявил
  раздел объяснённым. Он НЕ давал отдельного вывода «устранение = предотвращение»;
  почему пропущена самостоятельная обязанность внутри модели, UNKNOWN.
- H4 полный worksheet уже перечислял обязанности, но ошибочно засчитал reporting
  как обе и сломал shape; H5 один source→prose контроль находил старый пропуск,
  но свежий92его не находит. Поэтому не возвращать worksheet/cascade и не
  повторять общий guide. Старый compact review хранит INCOMPLETE/CONTRADICTED/
  SUPPORTED, literal evidence; membership/evidence само по себе не entailment.
- Ограниченная гипотеза В ТОЙ ЖЕ prose-review роли и существующей схеме:
  для материальной положительной coverage claims искать конкретный случай,
  когда сотрудник выполнил всё написанное в курсе, но отдельная исходная
  обязанность/условие остались неисполненными; также проверять, допускает ли
  курс действие, запрещённое источником. Два направления смыслового сравнения,
  а не требование дословных слов. Источник и весь текущий текст доступны;
  тесты/ключи не передаются. Finding содержит sourcequote/currentlessonquote/
  конкретный контрпример в basis, адресную correction; model claim UNVERIFIED.
- До переноса в runtime: candidate role сохраняется отдельно с hash, negative
  полный fresh92 PDF и positive принятый H5 PDF без target hints. Один вызов на
  контроль, без нового author/editor. Проверить также эквивалентные формулировки
  и известные ложные coverage-претензии. Если не подтвердится — сохранить FAIL,
  не называть новой гарантией и не повторять model на той же неизменной задаче.
- Никакой regex для конкретного глагола/финансового документа, нового большого
  перечня требований, шестой роли или deterministic semantic validator. СтарыйV2
  immutable; активировать только отдельныйV3 после saved negative/positive proof.

### CHG-L93C — 11.11: исходный блок → связный урок и вопросы, ПРЕДЛОЖЕННЫЙ КОНТРОЛЬ

- После замечания владельца: задача вопроса к ясному блоку не требует повторного
  разбора всего документа. Actual simple author получает весь source и свободно
  строит уроки, затем независимый global review реконструирует их рамки. Это
  не тождественно генерации по уже выделенным смысловым блокам.
- Сверка CHG-H01/H03/L91/L92A/B: прежний model-authored outline уже терял
  условия; производная карта не становится нормативным источником. Поэтому
  в первом контроле выделить **точные оригинальные source IDs/диапазоны и
  родительский контекст**, без пересказа/новой нормы. Original/approval не менять;
  subset отмечен как model view с full document revision/hash, не новая
  фиктивно согласованная редакция. Нужные отсылки остаются зависимостями.
- Один ясный блок standards26 → один связный урок/3–4вопроса в одном author
  запросе. Source scope передаётся вместе с блоком и сохраняется в видимом
  названии теста; условие отдельного вопроса остаётся в его формулировке.
  Не строить обзор всех воображаемых случаев других разделов. Проверка:
  source fidelity, понятность, один лучший подтверждённый целиком ответ,
  достаточный видимый контекст, ошибочное действие/ключ; не искать дефект
  через придуманное компанией полномочие или буквальную синонимию.
- Это проверка учебного комплекта на выделенном блоке, не готовая автоматическая
  классификация любого документа и не три полных DEV курса. До runtime выбрать
  корректный existing source-unit/dependency путь по доказательству; старые
  paths/5role experiments и неудачи сохранить. Не объявлять новую формулировку
  исправлением без model output и независимой проверки.
- L93B negative не обнаружил preventive duty и вместо этого предложил schedule/
  acknowledgement additions; hypothesis FAIL, positive пока NOT_RUN после
  отрицательного результата. Не переносить этот role candidate в worker.
- Реализация прототипа: `simple_source_unit.py` выбирает только owned literal
  IDs, сохраняет full source fingerprint и approval, явно разделяет primary/
  supporting. Schema повторно использует `_course_format`, без нового смыслового
  валидатора. Unscoped reference context нельзя молча отбросить. 14focused tests
  PASS, включая actual ManagedLuna.prepare/shipped producer с synthetic key без
  сети. Это контрактная проверка, не доказательство качества вопросов.
- Unit01/02 не дошли до модели из-за provider GET timeout; unit03 остановлен до
  модели из-за ошибочного вызова helper в root harness. Все0calls сохранены
  отдельно, не считаются итерациями генерации. Unit04 собран новым frozen
  harness; exact реальный request/producer проверен локально **до** чтения
  credential. Область блока вручную выбрана в эксперименте; автоматическое
  выделение всего документа ещё не проверено.
- Результат C на13:18UTC: unit04 author34.0s12549in1680out дал4корректных
  вопроса, но оставил практическую отсылку без раскрытия. Unit05 ordinary editor
  без списка ошибок сам добавил необходимые действия/условия;40.406s14054in1986out.
  После полного independent чтения selected source/урока/4cards — LOCAL_UNIT_PASS.
  Итого2fresh calls26603input3666output/74.406s модельного времени. Все4keys и
  IDs сохранены; реальный diff в actual-course-comparison.json, поле changes=[]
  в prototype harness — placeholder, не production edit receipt. За metadata
  фиктивную неизменность не выдавать. Денежный managed расход/provider build UNKNOWN.
- Важно для оценки: аудитор сначала распространил I-category signature branch
  на все II-category передачи, но после сверки специального условия «при наличии
  сомнений» отозвал это как недоказанный существенный пропуск. Первая оценка и
  withdrawal сохранены. Дополнительного modelcall по недоказанному finding нет.
  Не переносить максимум предположений по отсылке как универсальные обязанности.
- H9/document-run-inventory-local93-after-unit05.json добавляет10control records/
  6fresh calls166425input21606output, включая неудачный prose control; unit01–03
  имеют0modelcalls и не маскируются как генерации. У unit05 итог в связанном
  independent-review.md; immutable inventory хранит ссылку SEE_INDEPENDENT_QA.
  Это дополнение к18recoveredruns/50stages, не восстановление всех прежних недель.
- Root повторно проверил30focused tests PASS1.52s. Новый source-unit path пока
  не выбран штатным worker: автоматическое разбиение/сборка и3полных DEVкурса
  остаются отдельными gates; production90 не менялся. Текущий вывод относится
  к пригодности простого source-unit author→editor подхода на одном ясном блоке.

### CHG-L93D — 11.11: автоматический source-unit author→editor, ПРЕДЛОЖЕНО до изменений

| Run intent | Input | Actual model target / reasoning | Operation and current result |
|---|---|---|---|
| source-unit93-plan-d | standards26 approved working source;packet9e09475c…;13nonblank blocks |gpt-6-luna/HIGH|1automatic-plan call planned; exact fixture+real prepare+producer preflight PASS; no old course/defect hints; H10/local-plan/d|
| source-unit93-plan-c | approved PDF instruction;packet1db4da1f…;229nonblank blocks |gpt-6-luna/HIGH|1automatic-plan call planned; same assembled preflight PASS; H10/local-plan/c|
| source-unit93-plan-b | approved cash instruction;packetef7a5425…;91nonblank blocks/10originalimages |gpt-6-luna/HIGH|1automatic-plan call planned; same assembled preflight PASS; H10/local-plan/b|
| source-unit93-plan-r1-d | same standards revision, full literal source +owned structural labels |gpt-6-luna/HIGH|1revised automatic-plan call planned; source_structure and unambiguous reference task, no old course/defect hints; H10/local-plan-r1/d|
| source-unit93-plan-r1-c | same approved PDF, source_structure |gpt-6-luna/HIGH|1revised automatic-plan call planned; H10/local-plan-r1/c|
| source-unit93-plan-r1-b | same approved cash instruction/images, source_structure |gpt-6-luna/HIGH|1automatic-plan call planned; first cash plan was NOT_RUN; H10/local-plan-r1/b|
| source-unit93-plan-r2-c | same approved PDF; literal source structure, compact required assignment vector |gpt-6-luna/HIGH|1plan call planned only after1000-block producer+prepare and current assembled3-stage tests; H10/local-plan-r2/c|
| source-unit93-plan-r2-b | same approved cash source/images; same compact assignment vector |gpt-6-luna/HIGH|1plan call planned; no earlier cash planning inference; H10/local-plan-r2/b|
| source-unit93-retained-plan-r3-c | exact complete saved R2PDF request/response unchanged |gpt-6-luna/HIGH prior result;0fresh calls|offline consumer normalization/revalidation; original failure/usage retained; H10/retained-plan-r3/c|
| source-unit93-plan-r3-b | same approved cash source/images, compact vector and benign-support normalization |gpt-6-luna/HIGH|1plan planned; R2b not called because consumer normalization changed; H10/local-plan-r3/b|

H10=.release-evidence/source-unit-engine93-20261111. LOCAL snapshot hashes bind
planner/unit/orchestrator/response registry to exact each preflight request.
Source revision/approval unchanged; no native jobs or business writes in controls.

- First source-only plans: standards1call14611in792out18.047s/6units; PDF1call
  32019in1861out/19units. Standards II unit omitted I-category procedure support
  while keeping only table heading. This is a real dependency-selection miss,
  not ambiguity in the original. Cash first-plan intent NOT_RUN after shared
  flaw,0calls. No author/full course wasted on this plan.
- Before revised planner edit: existing instruction requested only "confirmed"
  cross-reference dependencies, so clear textual references lacked an explicit
  task. Restore general unambiguous textual references and structural literal
  labels/table context; selected support must include target procedure/conditions,
  not just heading. Prefer meaningful original section boundaries; combine short
  related sections into one practical3–4question lesson, without arbitrary count
  or size cap. This is planner task correction, not a case-specific validator or
  new model stage. Preserve original failed plans and compare revised snapshot.
- Follow-up before next code change: revisedPDF plan contained23units and omitted
  only legal-basis SRC4 from primary/non-teaching accounting; known complete
  response saved,47379input2610output, not an unknown network outcome. Source
  content is clear; do not treat bookkeeping omission as semantic ambiguity.
  Revised standards5units includes actual I-procedure dependency,15630in950out.
- Integration decision BEFORE replacement: per-unit2N role loop is technically
  proven but can multiply protocol/context overhead on long documents. Replace
  unreleasedV3 loop with1plan→1batch author→1batch ordinary editor. Each lesson
  remains bound to its explicit literal primary/support selection; union source
  sent once, no rewritten normative outline. Preserve source-unit dependency/
  custody/provenance, editorial ambiguity retention, media/IDs, actual changes,
  owned stage_once/cold replay. Do not invoke old3critics or regenerate good units
  on retry. Prior per-unit prototype/tests retained as historical evidence, not
  claimed current dispatch.
- Planner producer contract will require a keyed assignment for EVERY source ID,
  instead of asking the model to remember every ID in free arrays. Canonical
  units/primary/support/non-teaching interface unchanged. This is closed JSON
  inventory custody, not a code-based semantic judge. Missing instructional
  meaning remains model/editor/independent QA responsibility. New full assembled
  seam test must pass for batched3-stage path before inference/DEV.
- Required per-source object schema was rejected locally by the unchanged512-node
  producer guard at1000blocks. No model call. Compact fixed-length source-order
  assignment vector passes real producer+prepare1000-block synthetic test; every
  position has exact input identity/index, non-teaching reason explicit. Guard
  untouched, no arbitrary source size cap or domain semantic regex. Canonical
  plan interface unchanged. All intermediate formats are unreleased snapshots.
- R2PDF known complete response:46615input2802output,229/229 assignments,
  20units, no foreign/unknown/primaryless units. It was rejected solely because
  supporting_refs repeated each unit's own primary refs. This redundancy changes
  no source or teaching assignment; do NOT spend another model call fixing it.
  Before correction: accept owned redundant support in wire, deterministically
  deduplicate/remove primary refs from support on decode (primary dominates),
  preserve exact raw/hash, retain strict canonical selection. No semantic claim
  relaxed, no foreign refs/primary coverage omitted. Offline re-evaluate the
  exact saved R2response through corrected consumer, not a new generation.
- Independent integration review also separated input selection from used-source
  provenance: candidate persists editor-proposed lesson_sources after checking
  each against that lesson's own selected primary/support; broader selection
  stays diagnostic scope. Model provenance is still unverified meaning, not
  automatic evidence of semantic completeness. No source/model regeneration.

- Owner explicitly requests automatic meaningful units/dependencies, lesson+cards,
  ordinary editorial correction,3fullDEV thenproduction. Prior CHG-H01/H03/L92A/B/
  L93A/B/C checked: lossy outline must not replace literal source; failed global
  prose hypothesis/worksheet/cascaded critics are not restored. Accepted C unit
  author→editor is the behavioral reference, not proof of automatic planning.
- Keep: current approved working source and decision custody, immutable source IDs,
  PracticalModelView, existing practical course schema, media markers, native
  stage_once owned journal/pending recovery, tenant guards, normal persistence/
  human approval/publication. OldV1/V2 jobs keep their frozen paths.
- Replace for newV3 jobs only: full-document author+3critics+scoped final editor
  with1source-unit plan selecting literal primary/supporting IDs; author then
  ordinary editor per unit; deterministic assembly with unique lesson/question
  IDs and actual change/provenance records. Plan wording is navigation only,
  never a rewritten normative source. All nonempty source blocks accounted as
  primary or explicitly reasoned non-teaching context; reusable support may recur.
- Parent headings/table headers/confirmed cross-reference targets stay literal
  dependencies; no hidden unsupported expansion. Course-level prior good content
  is not reauthored on resume; completed exact stages cold-replay without new
  inference. New policy/group/format requires full assembled native-transport
  zero-inference coverage before any model/API run.
- Ownership: bounded writer owns simple_source_unit_plan.py and its tests only;
  root owns source_unit extensions, orchestration, routing/response registry,
  transport seams, diagnostics/docs/release. Independent reviewer owns read-only
  source/dependency/semantic assessment. Production and client courses unchanged
  until exact DEV semantic/technical acceptance. Runtime tunables use existing
  runtime_settings mechanism; no new paid capacity/provider/billing settings.
- Saved proof: standards missing-location, PDF preventive-duty omission, cash
  obsolete history/example-duty/broad-option cases; unit04/05 exact accepted
  learning unit. New3fullcourses only after local assembled-path and saved source
  plan/unit results. Register every document/model/version run before inference.

### CHG-L93E — 11.11: план навигации не становится запретом чтения исходника, ПРЕДЛОЖЕНО

| Run intent | Source/model | Planned check |
|---|---|---|
| source-unit93-course-b | approved cash packetef7a5425… +retained automatic10-unit plan fromR3;gpt-6-luna/HIGH |2fresh calls author+ordinary editor, no old course or known-error hints; full literal source once, proposed map revisable; H10/local-course/b. Real producer/prepare+whole-controller synthetic preflight PASS before credential. First plan supplied from saved model result, NOT native checkpoint/cache proof.|

- Review found cash client-RKO unit lacks the common RKO paragraph in proposed
  support; mixed source block also contains client-PKO image and RKO material.
  All literal source is owned/present, but hard per-unit ref allowance prevents
  author/editor using a legitimate common rule from another proposed unit.
  This is the same conceptual error as treating a derived plan as normative truth.
- Keep automatic literal topic plan as guidance, source inventory and primary
  topic identity. Send complete approved literal source ONCE per batch. Permit
  author/editor to add needed owned supporting context, using full current source
  and actual proposed lesson_sources; do not constrain semantic references to
  imperfect model-proposed support edges. Foreign tenant/document/revision refs
  remain rejected. Question correctness/primary-topic faithfulness stay model and
  independent QA tasks, not inferred from a reference subset.
- Ordinary whole-course editor may relocate an original illustration to its
  correct lesson. Keep source-owned image addresses and course-wide preservation;
  per-lesson image-lock would block repair of a mixed-boundary association.
  Preserve lesson/question identities and actual change/provenance receipts.
- Before new DEV runs: real assembled3-stage regression for common rule reused
  across units, foreign-source negative and legitimate image relocation versus
  image drop/invention. Then one local cash batch author→editor using the same
  automatic plan, without known-error hints; inspect all content/images against
  source. No new planner critic, financial regex or repeated full planning call.
- Final media boundary preserves authored asset identities at least once across
  the course, validates destinations against current owned source, and permits
  relocation/caption correction/consolidation of duplicate copies. It does not
  assert image completeness or correct placement; independent course QA does.
  Current actual3-stage synthetic seam13PASS includes shared common-rule source,
  editor-proposed provenance, media relocation/drop/foreign and cold recovery.

### CHG-L93F — 11.11: не приравнивать число тем плана к полноте курса, ПРЕДЛОЖЕНО

| Run intent | Input/model | Planned check |
|---|---|---|
| source-unit93-retained-course-b | same approved cash packet, retained automatic plan +exact complete author response SHA-bound; gpt-6-luna/HIGH |1fresh ordinary editor call,0author regeneration; no known-error hints; H10/retained-course02/b. Exact real-source6L draft→editor producer/prepare preflight PASS without credentials/network. Original rejected author retained; reuse is NOT exact-request cache/native replay.|

- First cash author completed one known response30896input4585output with6lessons/
  18questions/9asset markers. The navigation plan proposed10units; consumer
  rejected solely because lesson inventory differed. This does not demonstrate
  missing teaching content. Do not regenerate the source/course to satisfy an
  unverified outline count. Retain raw, usage and original failure.
- Correct unreleased path: plan is proposed meaningful topic organization; author
  may combine related topics into coherent lessons, preserving source meaning.
  Editor compares complete approved source with actual draft, can add missing
  lessons/questions while retaining existing identities and good content.
  No automatic claim of coverage from lesson count or source-ref presence.
  Keep3–4questions per actual lesson, source/tenant/revision ownership, valid
  shape, actual provenance, original assets and owned recovery. Human approval
  remains separate. This removes a false semantic gate, not integrity checks.
- Evaluate the exact retained6-lesson draft, then send only the ordinary editor
  role the full source/current draft/proposed topic map without defect hints.
  One new editor call, no author regeneration or invented source correction.
  Independent full-course/image QA determines real omissions and usability.

### CHG-L93G — 11.11: источник раньше проверяемого курса, ПРОВЕРЯЕМАЯ ГИПОТЕЗА

| Run intent | Input/model | Planned check |
|---|---|---|
| source-unit93-source-first-editor-b | same approved source +same exact6L18Q author, proposed map;gpt-6-luna/HIGH |1ordinary editor call with source before candidate;0author regeneration/known-error hints; H10/retained-course03/b; exact producer/prepare on retained draft before credentials|

- Ordinary editor on retained6L18Q draft returned10L30Q, restored online-cash/
  outage/error operations and all10unique assets,37469input7978output/1freshcall.
  Independent QA still found example-derived accountant action and an unrelated
  duplicate cash-book image in outage lesson. Both outputs retained NO_GO.
- Code observation: sort_keys=True serializes current_learning_units before
  source_blocks; previous prose roles similarly put lessons before source.
  This is confirmed request order, NOT proven cause of semantic anchoring.
- Before change: serialize literal source first, then current approved context/
  proposed topic map, actual draft last. Ask the same ordinary editorial role
  to read source before candidate. No new critic, domain rule, field validator
  or additional runtime stage. Source/approval/reasoning unchanged.
- Controlled retained-source test: exact original6L18Q author and same full
  approved source, source-first editor without issue hints. One new editor call,
  not another author or course regeneration. Compare independently with prior
  editor output; do not call one pass proof of reliable detection. Only fresh
  full DEV courses can establish candidate acceptance.

### CHG-L93H — 11.11: отдельное редакторское чтение сохранённого результата, ПРЕДЛОЖЕННЫЙ ЭКСПЕРИМЕНТ

- Source-first G returned10L30Q37476in7895out146.547s; duplicate image fixed,
  accountant example-derived action remains and one listed-set answer omits
  seller name. Independent full review NO_GO; source-first order is useful input
  discipline, not proven semantic fix. Do not repeat same rewrite unchanged.
- Recheck priorH5/H6/L92/L93B: broad prose-only reviews and generic guides failed;
  they are not restored. Test existing typed editorial_review contract as ONE
  read-only independent QA role on the complete final course, including keys,
  explanations and image references, source before candidate, no issue hints.
  Unlike full reauthoring, its only output is concrete supported findings and
  addressable corrections. No new semantic validator or operative regex.
- One saved-current-cash control first. If it does not find the real defects,
  stop this role hypothesis; no unchanged retry and no integration/claim. If it
  works, feed its own findings to the existing ordinary editor, then independent
  content QA. Any runtime extra stage requires separate pre-entry/owned tests.
- Separate static diagnosis: native ApprovedEditorialDocument retains validated
  preparation (typed blocks/assets); simple projection drops origin types, while
  literal text still labels example/OCR/non-normative description. Local fixture
  omits full preparation, so cannot prove native metadata parity. This is a real
  projection gap, not proof of the model's internal error cause; kind=form alone
  is not an authority classification. H10/visual-source-provenance-review.md.

| Run intent | Input/model | Planned check |
|---|---|---|
| source-unit93-blind-editorial-qa-b | approved cash source +complete source-first10L30Q final, no supplied issue list;gpt-6-luna/HIGH |1read-only QA call via existing editorial_review schema; no author/editor regeneration; H10/blind-editorial-qa/b; no new runtime role until saved proof|

### CHG-L93I — 11.11: типизированное происхождение текста иллюстраций, ПРЕДЛОЖЕНО

| Run intent | Input/model | Planned check |
|---|---|---|
| source-unit93-origin-editor-b | same approved cash source +same6L18Q author; exact native immutable preparation restored from restricted readonly DEV, manifest0a1b5b3f…;gpt-6-luna/HIGH |1ordinary editor call, source-first typed origin, no issue-instance hints; no author regeneration/new critic; H10/retained-course04/b; producer/prepare beforecredentials|

- H blind read-only QA returned0findings despite independently demonstrated
  accountant action/incomplete key,43968input1459output/1call. Hypothesis FAIL;
  do not integrate that role or repeat same unchanged call. No new critic stage.
- Static confirmed gap: native resolve_pins/DirectSourceDocument retains validated
  ApprovedEditorialDocument.preparation with typed blocks/asset kind/OCR/description.
  The simple projection reparses working_text and discards those types. Non-scan
  OCR/description is appended to an existing source block. Literal example labels
  remain visible, so cause inside model is UNKNOWN; no claim OCR was absent.
- Before change: reuse authoritative validate_binding/PreparedSource.selected
  and approved raw→working spans to project literal model-view segments with
  origin document body / visual OCR / visual description / scanned-page text.
  Concatenation must equal current owned block exactly; no source rewrite or
  invented normative classification. Kind=form/screen is provenance, not a rule.
  Preserve original asset identities; exclude storage_key/provider secrets.
- NewV3 only: planner/author/editor receive typed source-origin segments, old
  jobs retain old byte requests. No source omission or per-case financial regex.
  Ambiguous mapping stays unclassified with a diagnostic, not falsely labelled;
  invalid/stale preparation binding fails custody as before. No extra model role.
- Local fixture currently reconstructs preparation=None, unlike native. First
  read immutable approved preparation from canonical SupabaseDEV under restricted
  lms_app READ_ONLY/tenant scope and validate exact cached revision/text binding.
  Then test real-source parity and retained-draft editor with typed context once,
  without manual source/course edits or known issue hints. No3freshfullcourses
  while these saved defects are unresolved; DEV rollout and production remain open.
- Readback narrowed to cash after bulk metadata exceeded the unchanged64KiB
  diagnostic-output limit (plain and compressed3source bulk); no model calls or
  business writes. One cash-only compressed READ_ONLY lms_app query succeeded,
  approval97abc070…/working3c73b32e…/manifest0a1b5b3f…; validate_binding matches
  exact original source,5selected parts,129prepared blocks,10assets. Private
  manifest stored locally, storage keys never projected/printed. Receipt
  approved-preparation-receipt-cash.json. No source or approval was changed.
- Pure native/local parity PASS: sourcepacketef7a5425… unchanged; every segment
  reconstructs exact working source.11275document-body chars,13247visualOCR,
  4970visual-description,1556unclassified (including whitespace/edited ranges);
  all10assets mapped. Types are provenance only, not normative judgments.
- Actual3-stage synthetic segment integration/legacyV1/V2 payload checks42PASS,
  baseline1004/2174PASS. No more source-model calls on rejected H reviewer role.
- Re-adjudication: source-first L7Q3 material wrong-key claim WITHDRAWN; stem
  does not demand exhaustive list and all keyed details are source-supported.
  Adding seller name/quantity is advisory precision. Separate unsupported
  accountant action still blocks local semantic GO. No call spent on withdrawn
  question finding. Preserve first independent assessment and withdrawal.

### Результаты L92C–F на 11.11, перед DEV

- C: H5PDF независимый review нашёл пропуск prevention, editor исправил;3fresh
  134323input/13543output,8L24Q, independent LOCALGO. Scoped merge отклонил
  незапрошенное изменение другого вопроса. H7cash suppliedQA→editor1fresh
  38616/7435 independent LOCALGO8L28Q/10media; самостоятельное обнаружение не
  подтверждено. H5cash3fresh110718/11745 и H5standards3fresh58107/7614 FAIL.
- D: H6 guide2fresh78646/10379+exactcachedcard failed; guide удалён. Не повторять
  общую формулировку как будто она была удачной защитой. Отрицательный контроль
  и точные прежние исходники сохранены.
- E: actual RED утечки key/explanation воспроизведён до изменения. H8standards
  3fresh68530/11184+exactcachedprose18538/1841; editor изменил толькоl3q2stem,
  independent полный4L15Q review LOCALGO. **Обнаружил explanation-review**, blind
  solver сам недостаток location НЕ нашёл. Нельзя причинно приписывать весь
  результат key-blind свойству или считать одну удачу стабильностью модели.
- F: quiet-review/UNDECIDABLE actual five-owned/cold replay RED1FAIL1PASS→GREEN,
  затем72focusedPASS3.00s и baseline1004/2174PASS. Stale/foreignsource/draft/target/
  refs и изменённый editor вопрос проверены. Независимый source-review принял
  consumer; его первое замечание о guideD отозвано после сверки отрицательного H6.
- Полная текущая suite7977PASS/1skip/7warnings91.74s. Все calls — Luna6/HIGH,
  local component через существующий managedDEVconnector; businesswrites0,
  managed monetary UNKNOWN. Старые cached usage не считается новым расходом.
  Точные requests/rawresponses/custody/source snapshots в H5–H8, перечисленных
  в `2026-11-11-engine-restoration.md`. Новые nativeDEV92/DeepSeek/prod ещё не
  пройдены. Не применять прежний semanticGO к новому dispatcher.

Ниже добавляется воспроизводимая выборка всех локально достижимых commits,
менявших `apps/api/app/modules/ai`, `source_editorial_review`, `documents`,
связанные model transport/checkpoints/Celery, V3 tests, engine plans/contracts.
Дата и subject скопированы из Git; это **инвентаризация**, а не выдуманная
ретроспективная приёмка каждого изменения. Одна запись соответствует одному
commit; составной commit может содержать несколько исправлений. Для недоступных
старых доказательств тесты, расход и runtime-результат остаются НЕИЗВЕСТНО.
Commits других ветвей включены и помечены отдельно, а не объявлены потерянными.

<!-- ENGINE_HISTORY_GENERATED_START -->
Выборка: **557 commits**, 2026-06-21–2026-11-11; HEAD `b71b89f6f46bf14eb1d251ff09329f388a81eba4`. Источник — только доступные локальные refs, без fetch/сетевых запросов.

`BASE90` — предок принятой исходной ревизии90; `DEV91_SOURCE` — предок b71, не предок90; `OTHER_REF` — доступен через другие refs, не предок текущего HEAD. **Ни один из этих признаков не означает, что конкретный алгоритм вызывается сейчас.**

Для каждой строки тесты/токены/самостоятельная смысловая приёмка: **НЕ ВОССТАНОВЛЕНЫ**; детальные известные результаты — в записях CHG-H/L и связанных журналах. Полные scoped file lists сохранены в локальном receipt `git-inventory.json`. Выборка расширена на model transport, checkpoints/Celery, V3 tests, планы и contracts; полный список pathspecs находится в этом receipt.

### Git 2026-11

| ID / дата | Изменение | Состояние исходников | Основные файлы |
|---|---|---|---|
| <a id="chg-b71b89f6f46b"></a>[CHG-b71b89f6f46b](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/b71b89f6f46bf14eb1d251ff09329f388a81eba4)<br>2026-11-11T13:34:24+05:00 | fix(ai): register simple editor stages in owned transport and critical journey | DEV91_SOURCE | `apps/api/app/modules/ai/v3/direct_luna_owned_stage.py`; `apps/api/tests/unit/test_v3_simple_owned_transport.py`; `docs/testing/GENERATION_ENGINE_ERRORS.md` |
| <a id="chg-fb0fecae16ec"></a>[CHG-fb0fecae16ec](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/fb0fecae16eca99272de10704958caa7211a1611)<br>2026-11-11T12:44:01+05:00 | feat(ai): generate directly from approved source with one curriculum review | DEV91_SOURCE | `apps/api/app/modules/ai/managed_luna_client.py`; `apps/api/app/modules/ai/router.py`; `apps/api/app/modules/ai/v3/practical_author_transport.py`; ещё 13 |
| <a id="chg-16504ca00e91"></a>[CHG-16504ca00e91](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/16504ca00e91d681cb4ea66711f500b2600b0118)<br>2026-11-11T06:58:09+05:00 | fix(ai): persist JSON custody and recover owned author finalization (0.11.90) | BASE90 | `apps/api/app/modules/ai/managed_luna_client.py`; `apps/api/app/modules/ai/v3/direct_luna_owned_stage.py`; `apps/api/app/modules/ai/v3/practical_author_transport.py`; ещё 3 |
| <a id="chg-a23b4f30c538"></a>[CHG-a23b4f30c538](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/a23b4f30c5384b0b714b21a4b1f7bea28b62960f)<br>2026-11-10T21:34:12+05:00 | fix(ai): preserve author custody and apply retained editorial observations | BASE90 | `apps/api/app/modules/ai/credential_content_guard.py`; `apps/api/app/modules/ai/direct_luna_responses_client.py`; `apps/api/app/modules/ai/llm_client.py`; ещё 19 |
| <a id="chg-de6234d05d40"></a>[CHG-de6234d05d40](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/de6234d05d4093b7b127b9d6d5f882eadc1ae895)<br>2026-11-10T16:53:20+05:00 | fix(ai): canonicalize source-editor labels without changing source | BASE90 | `apps/api/app/modules/ai/source_editorial_model.py`; `apps/api/app/modules/source_editorial_review/analysis.py`; `docs/testing/GENERATION_ENGINE_ERRORS.md` |
| <a id="chg-c71bd492ebdf"></a>[CHG-c71bd492ebdf](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/c71bd492ebdf08573dd4e4cad824bdf590a08d87)<br>2026-11-10T15:43:42+05:00 | fix(web): recover expired author reads without replacing sessions | BASE90 | `docs/testing/GENERATION_ENGINE_ERRORS.md` |
| <a id="chg-ec2922c0b0c3"></a>[CHG-ec2922c0b0c3](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/ec2922c0b0c3cb84b74cbcaef1be92aec0ae1d82)<br>2026-11-10T12:23:13+05:00 | docs(release): finalize 0.11.84 acceptance and rollback evidence | BASE90 | `docs/testing/GENERATION_ENGINE_ERRORS.md` |
| <a id="chg-e9f47df36f7c"></a>[CHG-e9f47df36f7c](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/e9f47df36f7cdee3d622be55c3da76e9259f2149)<br>2026-11-10T11:14:20+05:00 | fix(web): remove legacy methodologist menu and preserve contextual tools | BASE90 | `docs/testing/GENERATION_ENGINE_ERRORS.md` |
| <a id="chg-4a3ec6065edc"></a>[CHG-4a3ec6065edc](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/4a3ec6065edc7b24f27dde0ac9f09b3e46ded80d)<br>2026-11-10T04:15:40+05:00 | feat(ai): add source-bound focused editorial cycle | BASE90 | `apps/api/app/modules/ai/pipeline.py`; `apps/api/app/modules/ai/router.py`; `apps/api/app/modules/ai/v3/direct_luna_owned_stage.py`; ещё 32 |
| <a id="chg-cbb294d8eda5"></a>[CHG-cbb294d8eda5](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/cbb294d8eda502aff22f7de2c42f8aebecf1dae3)<br>2026-11-09T14:44:06+05:00 | fix(ai): retain verified fidelity from approved native sources | BASE90 | `apps/api/app/modules/ai/direct_source.py`; `docs/testing/GENERATION_ENGINE_ERRORS.md` |
| <a id="chg-d58b904066bf"></a>[CHG-d58b904066bf](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/d58b904066bf6ef908ec9c1df109160df3a58d49)<br>2026-11-09T14:04:10+05:00 | fix(ai): author from literal source with coherent current editorial review | BASE90 | `apps/api/app/modules/ai/router.py`; `apps/api/app/modules/ai/v3/practical_autonomous_editorial_cycle.py`; `apps/api/app/modules/ai/v3/practical_coherent_editorial_cycle.py`; ещё 14 |
| <a id="chg-947afed985d6"></a>[CHG-947afed985d6](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/947afed985d6ba844c90c12e144b34da84dc6539)<br>2026-11-09T11:57:53+05:00 | fix(ai): reconcile current findings and preserve reviewed assessment saves | BASE90 | `apps/api/app/modules/ai/assessment_schema.py`; `apps/api/app/modules/ai/pipeline.py`; `apps/api/app/modules/ai/v3/final_save_readback.py`; ещё 10 |
| <a id="chg-7bc6f1294b49"></a>[CHG-7bc6f1294b49](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/7bc6f1294b49fd19cb6d19b3d0e0994e860b0f4b)<br>2026-11-09T09:38:35+05:00 | fix(ai): complete missing model decisions and recover owned joint replies | BASE90 | `apps/api/app/modules/ai/llm_client.py`; `apps/api/app/modules/ai/managed_luna_client.py`; `apps/api/app/modules/ai/v3/pending_stage_transactions.py`; ещё 9 |
| <a id="chg-df91ad9eb966"></a>[CHG-df91ad9eb966](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/df91ad9eb96663ae6cd86a21e74850a91db3e749)<br>2026-11-09T07:59:53+05:00 | fix(ai): preserve operative lists and adjudicate exact current lesson text | BASE90 | `apps/api/app/modules/ai/v3/practical_compact_editorial_cycle.py`; `apps/api/app/modules/ai/v3/practical_source_semantic_cycle.py`; `apps/api/tests/unit/test_v3_joint_editorial_cycle.py`; ещё 4 |
| <a id="chg-c4604a379442"></a>[CHG-c4604a379442](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/c4604a379442cb79ccb11dd489325b1126501adf)<br>2026-11-09T05:49:01+05:00 | fix(ai): preserve source scope through model review and addressed repair | BASE90 | `apps/api/app/modules/ai/v3/practical_autonomous_editorial_cycle.py`; `apps/api/app/modules/ai/v3/practical_compact_editorial_cycle.py`; `apps/api/app/modules/ai/v3/practical_source_comparisons.py`; ещё 5 |
| <a id="chg-d9fc0c57c6fc"></a>[CHG-d9fc0c57c6fc](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/d9fc0c57c6fc5d63acabf5562b44fa29230acfe9)<br>2026-11-09T04:33:54+05:00 | fix(ai): bind addressed proof repair to current owned evidence | BASE90 | `apps/api/app/modules/ai/v3/practical_compact_editorial_cycle.py`; `apps/api/app/modules/ai/v3/practical_editorial_proof_correction.py`; `apps/api/app/modules/ai/v3/practical_editorial_verification.py`; ещё 2 |
| <a id="chg-7b17e42d138e"></a>[CHG-7b17e42d138e](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/7b17e42d138e180e80ccb4e873ffe372f1402d1f)<br>2026-11-09T04:15:16+05:00 | fix(ai): use coherent whole-course review and shared current target evidence | BASE90 | `apps/api/app/modules/ai/v3/practical_autonomous_editorial_cycle.py`; `apps/api/app/modules/ai/v3/practical_compact_editorial_cycle.py`; `apps/api/tests/unit/test_v3_joint_autonomous_cycle.py`; ещё 3 |
| <a id="chg-27391ca97848"></a>[CHG-27391ca97848](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/27391ca97848feae4822acbf9996e0651ddf46a9)<br>2026-11-09T03:25:32+05:00 | fix(ai): consolidate source and course observations before model repair | BASE90 | `apps/api/app/modules/ai/pipeline.py`; `apps/api/app/modules/ai/router.py`; `apps/api/app/modules/ai/v3/direct_luna_owned_stage.py`; ещё 18 |
| <a id="chg-1506f36895e8"></a>[CHG-1506f36895e8](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/1506f36895e849e548828cc5592427b114c78afa)<br>2026-11-09T02:31:15+05:00 | fix(ai): preserve proof decisions and deduplicate source questions | BASE90 | `apps/api/app/modules/ai/v3/practical_autonomous_editorial_cycle.py`; `apps/api/app/modules/ai/v3/practical_compact_editorial_cycle.py`; `apps/api/app/modules/ai/v3/practical_editorial_proof_correction.py`; ещё 3 |
| <a id="chg-d28d3cc43a12"></a>[CHG-d28d3cc43a12](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/d28d3cc43a1228768408b57915ba70032eff632e)<br>2026-11-09T01:58:36+05:00 | fix(ai): verify and repair current course through autonomous editorial review | BASE90 | `apps/api/app/modules/ai/llm_client.py`; `apps/api/app/modules/ai/pipeline.py`; `apps/api/app/modules/ai/router.py`; ещё 49 |
| <a id="chg-e6b8f5f81fab"></a>[CHG-e6b8f5f81fab](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/e6b8f5f81fab5609a0efb2313ed229a4f84557c9)<br>2026-11-08T12:30:44+05:00 | docs: record full production acceptance of both original documents | BASE90 | `docs/testing/GENERATION_ENGINE_ERRORS.md` |
| <a id="chg-466e0f902b70"></a>[CHG-466e0f902b70](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/466e0f902b70283cd3d3375cf216163e8d2b2ea5)<br>2026-11-08T10:49:38+05:00 | fix(source-review): honor audited response budget | BASE90 | `apps/api/app/modules/source_editorial_review/analysis.py`; `docs/testing/GENERATION_ENGINE_ERRORS.md` |
| <a id="chg-7797ae7dfe9d"></a>[CHG-7797ae7dfe9d](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/7797ae7dfe9d3c708d3db59c8261fa4a0a203970)<br>2026-11-07T15:56:26+05:00 | docs: close source preparation 0.11.82 acceptance | BASE90 | `docs/testing/GENERATION_ENGINE_ERRORS.md` |
| <a id="chg-ae11c4d3a962"></a>[CHG-ae11c4d3a962](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/ae11c4d3a962e35405580d801a01e1e74773a283)<br>2026-11-07T14:20:05+05:00 | fix(ai): match retained replay to practical worker stage identity | BASE90 | `apps/api/app/modules/ai/v3/pending_stage_transactions.py`; `apps/api/app/modules/ai/v3/retained_author_replay.py`; `apps/api/tests/unit/test_v3_practical_author_retained_wrapper.py`; ещё 1 |
| <a id="chg-87c423e811cc"></a>[CHG-87c423e811cc](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/87c423e811ccb7f21a14da5ecfbb5c1ae6eef54b)<br>2026-11-07T13:52:17+05:00 | fix(ai): recover retained author replies with stable question identities | BASE90 | `apps/api/app/modules/ai/job_service.py`; `apps/api/app/modules/ai/managed_luna_client.py`; `apps/api/app/modules/ai/router.py`; ещё 10 |
| <a id="chg-6eaeb3efa035"></a>[CHG-6eaeb3efa035](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/6eaeb3efa035469f2836ce1a693d418e26910c05)<br>2026-11-07T12:32:13+05:00 | fix(source): retain bounded preparation and semantic review progress | BASE90 | `apps/api/app/modules/source_editorial_review/analysis.py`; `apps/api/app/modules/source_editorial_review/continuation.py`; `apps/api/app/modules/source_editorial_review/domain.py`; ещё 3 |
| <a id="chg-debecceabca1"></a>[CHG-debecceabca1](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/debecceabca13bf389ac4e8c4690f0e3d1952520)<br>2026-11-07T11:14:05+05:00 | fix(source): require verified preparation for new review approvals | BASE90 | `apps/api/app/modules/source_editorial_review/analysis.py`; `apps/api/app/modules/source_editorial_review/service.py`; `docs/testing/GENERATION_ENGINE_ERRORS.md` |
| <a id="chg-b56381225ca2"></a>[CHG-b56381225ca2](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/b56381225ca24de8f4c406b0ae9ea0225925d3b6)<br>2026-11-07T11:01:35+05:00 | fix(source): verify image readings and recover completed visual replies | BASE90 | `apps/api/app/modules/ai/pipeline.py`; `apps/api/app/modules/source_editorial_review/analysis.py`; `docs/testing/GENERATION_ENGINE_ERRORS.md` |
| <a id="chg-60681e1ed4f6"></a>[CHG-60681e1ed4f6](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/60681e1ed4f6442d30f43b39cdfee3a5952ed377)<br>2026-11-07T10:12:39+05:00 | feat(source): bind document parts and illustrations to reviewed course editions | BASE90 | `apps/api/app/modules/ai/pipeline.py`; `apps/api/app/modules/ai/v3/practical_editorial_cycle.py`; `apps/api/app/modules/documents/cleanup.py`; ещё 6 |
| <a id="chg-20a53f9a234b"></a>[CHG-20a53f9a234b](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/20a53f9a234b96c4a0c37e7e48f884576ab97069)<br>2026-11-07T08:44:44+05:00 | Record production nine-format and Excel pair acceptance | BASE90 | `docs/testing/GENERATION_ENGINE_ERRORS.md` |
| <a id="chg-369f82a16726"></a>[CHG-369f82a16726](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/369f82a16726297ff6fd852aaeaeebc89955806f)<br>2026-11-07T08:23:06+05:00 | Preserve rejected review context during schema correction | BASE90 | `apps/api/app/modules/source_editorial_review/analysis.py`; `docs/testing/GENERATION_ENGINE_ERRORS.md` |
| <a id="chg-7b00f2270c0f"></a>[CHG-7b00f2270c0f](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/7b00f2270c0f3ce32fb99652be2584a1e37d553e)<br>2026-11-07T08:17:23+05:00 | Correct completed source review schema failures once | BASE90 | `apps/api/app/modules/source_editorial_review/analysis.py`; `docs/testing/GENERATION_ENGINE_ERRORS.md` |
| <a id="chg-f450993e7f61"></a>[CHG-f450993e7f61](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/f450993e7f61f50f7a6217cc21f8e60cd616aa87)<br>2026-11-07T07:54:58+05:00 | Fix source review response input echoes | BASE90 | `apps/api/app/modules/source_editorial_review/analysis.py`; `docs/testing/GENERATION_ENGINE_ERRORS.md` |
| <a id="chg-ebc80e21b610"></a>[CHG-ebc80e21b610](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/ebc80e21b610c364ce39a4679396d365d68dfb93)<br>2026-11-07T07:26:02+05:00 | Fix duplicate source review findings for table quotes | BASE90 | `apps/api/app/modules/source_editorial_review/analysis.py`; `docs/testing/GENERATION_ENGINE_ERRORS.md` |
| <a id="chg-fce7b71e2b2e"></a>[CHG-fce7b71e2b2e](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/fce7b71e2b2e6d3e2aa474d0559200eb686fa2a3)<br>2026-11-06T22:53:02+05:00 | docs(release): record production document format acceptance | BASE90 | `docs/testing/GENERATION_ENGINE_ERRORS.md` |
| <a id="chg-49902a0d45f5"></a>[CHG-49902a0d45f5](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/49902a0d45f55a736419acb8e1173d46613f63a8)<br>2026-11-06T21:44:53+05:00 | fix(source-review): retain unconfirmed findings for human review | BASE90 | `apps/api/app/modules/source_editorial_review/analysis.py`; `docs/testing/GENERATION_ENGINE_ERRORS.md` |
| <a id="chg-eb6585b176d5"></a>[CHG-eb6585b176d5](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/eb6585b176d5b9fb0a3f236217d88c59e2e63fc0)<br>2026-11-06T21:17:05+05:00 | fix(source-review): recover once from a completed invalid JSON response | BASE90 | `apps/api/app/modules/ai/managed_luna_client.py`; `apps/api/app/modules/source_editorial_review/analysis.py`; `docs/testing/GENERATION_ENGINE_ERRORS.md` |
| <a id="chg-54fc6927e976"></a>[CHG-54fc6927e976](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/54fc6927e9766bdf1d283d8fa94ca18b6019c158)<br>2026-11-06T20:44:56+05:00 | Require evidence for material source clues and preserve layout edits | BASE90 | `apps/api/app/modules/source_editorial_review/analysis.py`; `apps/api/app/modules/source_editorial_review/domain.py`; `docs/testing/GENERATION_ENGINE_ERRORS.md` |
| <a id="chg-76b199bf2d57"></a>[CHG-76b199bf2d57](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/76b199bf2d578851be347987ae3a795410f82ef4)<br>2026-11-06T20:09:21+05:00 | Separate semantic review clues from cosmetic source edits | BASE90 | `apps/api/app/modules/source_editorial_review/analysis.py` |
| <a id="chg-9d6c88639a10"></a>[CHG-9d6c88639a10](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/9d6c88639a1036ea85b0b602c8590895ac02866e)<br>2026-11-06T20:05:12+05:00 | Preserve actionable document review failure codes and stage | BASE90 | `apps/api/app/modules/source_editorial_review/analysis.py`; `apps/api/app/modules/source_editorial_review/service.py` |
| <a id="chg-668b5f2a25b1"></a>[CHG-668b5f2a25b1](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/668b5f2a25b16eff8d9abcedcca24efc3b33395e)<br>2026-11-06T19:37:18+05:00 | Enable PowerPoint source review and pause new SCORM imports | BASE90 | `apps/api/app/modules/ai/direct_source.py`; `apps/api/app/modules/ai/ingestion.py`; `apps/api/app/modules/ai/pptx_source.py`; ещё 2 |
| <a id="chg-8df0de136544"></a>[CHG-8df0de136544](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/8df0de13654445664f4cf4f0d0f3df495fad5f63)<br>2026-11-06T19:17:31+05:00 | Align course document upload formats with the review API | BASE90 | `apps/api/app/modules/documents/router.py` |
| <a id="chg-f0cc2d261740"></a>[CHG-f0cc2d261740](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/f0cc2d2617406d022e9a2c672199357f41018ea3)<br>2026-11-06T18:59:41+05:00 | Preserve source review request identity across rollout | BASE90 | `apps/api/app/modules/source_editorial_review/service.py` |
| <a id="chg-c357b84bac5d"></a>[CHG-c357b84bac5d](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/c357b84bac5d6e41af0096f5341d168c48ed98f8)<br>2026-11-06T18:49:29+05:00 | Clarify the document-based course creation flow | BASE90 | `apps/api/app/modules/ai/direct_source.py`; `apps/api/app/modules/ai/pipeline.py`; `apps/api/app/modules/documents/schemas.py`; ещё 3 |
| <a id="chg-d6601f9314b1"></a>[CHG-d6601f9314b1](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/d6601f9314b13b247d0aa0052d5cd2f144223ebb)<br>2026-11-06T18:39:08+05:00 | Prepare database-managed DeepSeek generation limits | OTHER_REF | `apps/api/app/modules/ai/llm_client.py`; `apps/api/app/modules/ai/v3/provider_profile.py`; `apps/api/tests/unit/test_v3_native_cooperative_deadline.py`; ещё 1 |
| <a id="chg-91f894d75258"></a>[CHG-91f894d75258](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/91f894d75258a77d958737352b0e371bdea7af72)<br>2026-11-06T18:22:28+05:00 | Remove development models from KZ production generation | BASE90 | `apps/api/app/modules/ai/llm_client.py`; `apps/api/app/modules/source_editorial_review/analysis.py` |
| <a id="chg-caf25257764e"></a>[CHG-caf25257764e](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/caf25257764e3c03c28e4dcdfebab0786527c5b2)<br>2026-11-06T12:19:54+05:00 | Separate policy ambiguities from safe source corrections | BASE90 | `apps/api/app/modules/source_editorial_review/analysis.py`; `apps/api/app/modules/source_editorial_review/domain.py`; `apps/api/app/modules/source_editorial_review/service.py` |
| <a id="chg-31f82041b4c9"></a>[CHG-31f82041b4c9](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/31f82041b4c90dc86e3d56ad2c058e888dabe36a)<br>2026-11-06T11:34:04+05:00 | Keep legacy source and correction contracts independent of editorial storage | BASE90 | `apps/api/app/modules/source_editorial_review/domain.py`; `apps/api/app/modules/source_editorial_review/service.py` |
| <a id="chg-93d8d3443d56"></a>[CHG-93d8d3443d56](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/93d8d3443d566908f7b1f6ca997a252088645f1c)<br>2026-11-06T11:26:36+05:00 | Validate source review page coverage and claim typing | BASE90 | `apps/api/app/modules/source_editorial_review/analysis.py` |
| <a id="chg-bad2df0228ef"></a>[CHG-bad2df0228ef](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/bad2df0228efa3117ccbba46ce3c35203e52db88)<br>2026-11-06T11:24:55+05:00 | Add human approval of source documents before course generation | BASE90 | `apps/api/app/modules/ai/direct_source.py`; `apps/api/app/modules/ai/evidence_engine/application.py`; `apps/api/app/modules/ai/pipeline.py`; ещё 9 |
| <a id="chg-991b5a4ce379"></a>[CHG-991b5a4ce379](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/991b5a4ce379b1a1f69211260151cc65f24145e2)<br>2026-11-06T05:42:50+05:00 | Increase the managed DeepSeek budget for new editorial jobs | BASE90 | `apps/api/app/modules/ai/llm_client.py`; `apps/api/app/modules/ai/pipeline.py`; `apps/api/app/modules/ai/router.py`; ещё 5 |
| <a id="chg-b426dfde8144"></a>[CHG-b426dfde8144](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/b426dfde81441abf88914ea4beed9607a020ab54)<br>2026-11-05T22:18:43+05:00 | Stabilize editorial stage request recovery across JSONB round trips | BASE90 | `apps/api/app/modules/ai/pipeline.py`; `apps/api/app/modules/ai/router.py`; `apps/api/app/modules/ai/v3/practical_editorial_cycle.py`; ещё 10 |
| <a id="chg-c4a65ae460be"></a>[CHG-c4a65ae460be](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/c4a65ae460bed54bc0bda19788b33c23b6bc47a6)<br>2026-11-05T21:43:21+05:00 | feat(ai): route fresh courses through the coherent editorial engine | BASE90 | `apps/api/app/modules/ai/pipeline.py`; `apps/api/app/modules/ai/router.py`; `apps/api/app/modules/ai/v3/revision_policy.py`; ещё 4 |
| <a id="chg-12d335771a29"></a>[CHG-12d335771a29](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/12d335771a29f23e16d17733271a8b805eeb9b9b)<br>2026-11-05T20:50:56+05:00 | fix(ai): retain rejected stages without a false provider outcome | BASE90 | `apps/api/app/modules/ai/job_service.py`; `apps/api/app/modules/ai/router.py`; `apps/api/app/modules/ai/schemas.py`; ещё 2 |
| <a id="chg-c450f1af16c3"></a>[CHG-c450f1af16c3](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/c450f1af16c3887185a84bddf3d8d410007e2d6e)<br>2026-11-05T19:15:34+05:00 | fix(ai): select P31 on managed DEV Luna route | BASE90 | `apps/api/app/modules/ai/pipeline.py`; `apps/api/app/modules/ai/router.py`; `apps/api/app/modules/ai/v3/revision_policy.py`; ещё 3 |
| <a id="chg-0a95a0e265f7"></a>[CHG-0a95a0e265f7](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/0a95a0e265f7158141771dead443013ba70264ff)<br>2026-11-05T18:33:40+05:00 | feat(web): integrate workspace design with editorial draft review | BASE90 | `docs/testing/GENERATION_ENGINE_ERRORS.md` |
| <a id="chg-a416116cd068"></a>[CHG-a416116cd068](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/a416116cd0681481036a220d5ef3316145e26537)<br>2026-11-05T18:06:01+05:00 | feat(ai): integrate coherent editorial course workflow | BASE90 | `apps/api/app/modules/ai/pipeline.py`; `apps/api/app/modules/ai/router.py`; `apps/api/app/modules/ai/v3/direct_luna_owned_stage.py`; ещё 16 |
| <a id="chg-002d7908f693"></a>[CHG-002d7908f693](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/002d7908f693d2000009ce223875e53d7cb9cf31)<br>2026-11-05T16:46:02+05:00 | fix(ai): reconcile P30 source and review contracts | BASE90 | `apps/api/app/modules/ai/v3/practical_curriculum.py`; `apps/api/app/modules/ai/v3/practical_source_core.py`; `apps/api/app/modules/ai/v3/practical_source_core_cycle.py`; ещё 4 |
| <a id="chg-e1b5b945f53d"></a>[CHG-e1b5b945f53d](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/e1b5b945f53d5360868927e13f326a6c0df5e968)<br>2026-11-05T15:53:24+05:00 | fix(ai): preserve P30 drafts for explicit editorial review | BASE90 | `apps/api/app/modules/ai/v3/practical_draft_review.py`; `apps/api/app/modules/ai/v3/practical_service.py`; `apps/api/app/modules/ai/v3/practical_source_core.py`; ещё 2 |
| <a id="chg-e9c9571d626d"></a>[CHG-e9c9571d626d](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/e9c9571d626d814e11fd25cf6ee583251644d759)<br>2026-11-05T12:52:42+05:00 | feat(ai): freeze opt-in source-backed P30 for external audit | BASE90 | `apps/api/app/modules/ai/router.py`; `apps/api/app/modules/ai/v3/direct_luna_owned_stage.py`; `apps/api/app/modules/ai/v3/practical_cycle.py`; ещё 13 |
| <a id="chg-906b5a115a38"></a>[CHG-906b5a115a38](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/906b5a115a385771c8cd394ffed112081f5cd08d)<br>2026-11-05T07:47:56+05:00 | fix(ai): separate explanation review and representative coverage | BASE90 | `apps/api/app/modules/ai/v3/practical_arbitration.py`; `apps/api/app/modules/ai/v3/practical_atomic_audit.py`; `apps/api/app/modules/ai/v3/practical_curriculum.py`; ещё 12 |
| <a id="chg-29ece9767232"></a>[CHG-29ece9767232](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/29ece9767232b2707b4ab3fb7dc575df137c4ca4)<br>2026-11-05T04:36:00+05:00 | fix(ai): plan source decisions before scoped curriculum review | BASE90 | `apps/api/app/modules/ai/v3/direct_luna_owned_stage.py`; `apps/api/app/modules/ai/v3/practical_atomic_audit.py`; `apps/api/app/modules/ai/v3/practical_curriculum.py`; ещё 12 |
| <a id="chg-8f765bd7118e"></a>[CHG-8f765bd7118e](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/8f765bd7118e579a9070dd02cd1ccbc697ce22f9)<br>2026-11-05T02:08:21+05:00 | fix(ai): preserve review domains without granting repair authority | BASE90 | `apps/api/app/modules/ai/v3/practical_arbitration.py`; `apps/api/app/modules/ai/v3/practical_cycle.py`; `apps/api/app/modules/ai/v3/practical_lesson_cycle.py`; ещё 9 |
| <a id="chg-19a649222761"></a>[CHG-19a649222761](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/19a6492227615ed6c340630185bdcc3b87e47001)<br>2026-11-05T01:12:11+05:00 | fix(ai): verify source child coverage and preserve review domains | BASE90 | `apps/api/app/modules/ai/v3/adapter.py`; `apps/api/app/modules/ai/v3/practical_atomic_audit.py`; `apps/api/app/modules/ai/v3/practical_audit_spans.py`; ещё 9 |
| <a id="chg-f7bfe2721d01"></a>[CHG-f7bfe2721d01](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/f7bfe2721d012602ce024c07d3485a961a4cfa85)<br>2026-11-04T22:33:35+05:00 | feat(ai): isolate temporary ASUS DeepSeek profile in DEV QA | BASE90 | `apps/api/app/modules/ai/llm_client.py`; `apps/api/app/modules/ai/pipeline.py`; `apps/api/app/modules/ai/v3/local_deepseek_dev.py`; ещё 1 |
| <a id="chg-7b1ec626b2f6"></a>[CHG-7b1ec626b2f6](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/7b1ec626b2f66d8089b226c47b0e6a68a0ac5ae2)<br>2026-11-04T21:31:29+05:00 | fix(ai): isolate review holds and simulate validator transitions | BASE90 | `apps/api/app/modules/ai/v3/practical_arbitration.py`; `apps/api/app/modules/ai/v3/practical_atomic_audit.py`; `apps/api/app/modules/ai/v3/practical_cycle.py`; ещё 10 |
| <a id="chg-5467e5aeaca9"></a>[CHG-5467e5aeaca9](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/5467e5aeaca9171323e8bae04c981211ca41cf82)<br>2026-11-04T19:39:35+05:00 | fix(ai): distinguish taught content from assessed decisions | BASE90 | `apps/api/app/modules/ai/v3/practical_arbitration.py`; `apps/api/app/modules/ai/v3/practical_cycle.py`; `apps/api/app/modules/ai/v3/practical_lesson_cycle.py`; ещё 7 |
| <a id="chg-a33073109d15"></a>[CHG-a33073109d15](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/a33073109d159a5d4838bd70d873c75728909a8d)<br>2026-11-04T18:50:45+05:00 | fix(ai): preserve owned question context and source provenance | BASE90 | `apps/api/app/modules/ai/v3/direct_luna_owned_stage.py`; `apps/api/app/modules/ai/v3/practical_cycle.py`; `apps/api/app/modules/ai/v3/practical_lesson_cycle.py`; ещё 9 |
| <a id="chg-f7c105b6c165"></a>[CHG-f7c105b6c165](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/f7c105b6c16508578462d70481ebd96eae033848)<br>2026-11-04T16:15:10+05:00 | fix(ai): construct mutually exclusive practical answer options for fresh courses | BASE90 | `apps/api/app/modules/ai/v3/practical_cycle.py`; `apps/api/app/modules/ai/v3/practical_lesson_cycle.py`; `apps/api/app/modules/ai/v3/practical_service.py`; ещё 5 |
| <a id="chg-0da671551066"></a>[CHG-0da671551066](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/0da67155106684a079934b4d753366a72e450b9b)<br>2026-11-04T15:22:56+05:00 | fix(ai): bind audit owners and verify native final source | BASE90 | `apps/api/app/modules/ai/pipeline.py`; `apps/api/app/modules/ai/router.py`; `apps/api/app/modules/ai/v3/practical_atomic_audit.py`; ещё 8 |
| <a id="chg-a1177116880d"></a>[CHG-a1177116880d](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/a1177116880d0ac281291b4135ae55fe12137707)<br>2026-11-04T13:30:41+05:00 | fix(ai): preserve fresh delivery saves and review question bank once | BASE90 | `apps/api/app/modules/ai/delivery_ownership.py`; `apps/api/app/modules/ai/job_service.py`; `apps/api/app/modules/ai/v3/final_save_owned_checkpoint.py`; ещё 12 |
| <a id="chg-e87c4f04154b"></a>[CHG-e87c4f04154b](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/e87c4f04154bb19e0d885cde48c7f2859d97bc31)<br>2026-11-04T12:21:36+05:00 | fix(ai): preserve source conditions when constructing practical cases | BASE90 | `apps/api/app/modules/ai/v3/practical_cycle.py`; `apps/api/app/modules/ai/v3/practical_lesson_cycle.py`; `apps/api/app/modules/ai/v3/practical_service.py`; ещё 4 |
| <a id="chg-64b1b37c7cc6"></a>[CHG-64b1b37c7cc6](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/64b1b37c7cc6e938e978d85b74063e72df48c97d)<br>2026-11-04T11:10:27+05:00 | fix(ai): check source counterexamples before accepting answers | BASE90 | `apps/api/app/modules/ai/v3/practical_arbitration.py`; `apps/api/app/modules/ai/v3/practical_cycle.py`; `apps/api/app/modules/ai/v3/practical_lesson_cycle.py`; ещё 8 |
| <a id="chg-3a72122558a8"></a>[CHG-3a72122558a8](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/3a72122558a8453495272fc3c6246487a9f383f2)<br>2026-11-04T10:08:23+05:00 | fix(ai): separate answer validity from course assessment review | BASE90 | `apps/api/app/modules/ai/v3/practical_arbitration.py`; `apps/api/app/modules/ai/v3/practical_atomic_audit.py`; `apps/api/app/modules/ai/v3/practical_cycle.py`; ещё 11 |
| <a id="chg-dc8846baf6a6"></a>[CHG-dc8846baf6a6](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/dc8846baf6a6850e7c707693ea0b0da66787ea85)<br>2026-11-04T09:01:09+05:00 | fix(ai): separate standalone question scope and owned prose evidence | BASE90 | `apps/api/app/modules/ai/v3/practical_arbitration.py`; `apps/api/app/modules/ai/v3/practical_atomic_audit.py`; `apps/api/app/modules/ai/v3/practical_cycle.py`; ещё 12 |
| <a id="chg-ce3dd4dd9ab2"></a>[CHG-ce3dd4dd9ab2](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/ce3dd4dd9ab264b9411684854e1d3f551c127235)<br>2026-11-04T07:33:31+05:00 | fix(ai): adjudicate course feedback before scoped repairs | BASE90 | `apps/api/app/modules/ai/v3/direct_luna_owned_stage.py`; `apps/api/app/modules/ai/v3/practical_arbitration.py`; `apps/api/app/modules/ai/v3/practical_cycle.py`; ещё 10 |
| <a id="chg-2370a35a48a6"></a>[CHG-2370a35a48a6](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/2370a35a48a68fff5ec477f08d62f7ca603fa120)<br>2026-11-04T05:25:13+05:00 | fix(ai): review coherent lessons and audit atomic source coverage | BASE90 | `apps/api/app/modules/ai/v3/practical_atomic_audit.py`; `apps/api/app/modules/ai/v3/practical_cycle.py`; `apps/api/app/modules/ai/v3/practical_lesson_cycle.py`; ещё 10 |
| <a id="chg-9b0d1960f4df"></a>[CHG-9b0d1960f4df](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/9b0d1960f4df48b7a18196da88b082b0e7801da4)<br>2026-11-04T04:19:40+05:00 | fix(ai): use compact independent editor with explicit answerability | BASE90 | `apps/api/app/modules/ai/v3/practical_cycle.py`; `apps/api/app/modules/ai/v3/practical_review.py`; `apps/api/app/modules/ai/v3/practical_service.py`; ещё 6 |
| <a id="chg-5c5bbb0a4297"></a>[CHG-5c5bbb0a4297](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/5c5bbb0a429779fa95c374bc403a9f77290a7145)<br>2026-11-04T03:33:29+05:00 | fix(ai): preserve authored question scope and cross-clause applicability | BASE90 | `apps/api/app/modules/ai/pipeline.py`; `apps/api/app/modules/ai/v3/practical_applicability.py`; `apps/api/app/modules/ai/v3/practical_cycle.py`; ещё 9 |
| <a id="chg-57d2e1f7dda6"></a>[CHG-57d2e1f7dda6](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/57d2e1f7dda6006dab294f37e3e5d5a7f3f3c304)<br>2026-11-04T02:48:58+05:00 | fix(ai): preserve audit negatives and scope assessment repairs | BASE90 | `apps/api/app/modules/ai/v3/practical_cycle.py`; `apps/api/app/modules/ai/v3/practical_fidelity.py`; `apps/api/app/modules/ai/v3/practical_patch.py`; ещё 9 |
| <a id="chg-8a6d466060d2"></a>[CHG-8a6d466060d2](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/8a6d466060d2313c8394f330a74b7e2b1f2915ab)<br>2026-11-04T01:57:00+05:00 | fix(ai): bind source-first practical reading and managed model custody | BASE90 | `apps/api/app/modules/ai/managed_luna_client.py`; `apps/api/app/modules/ai/router.py`; `apps/api/app/modules/ai/v3/direct_luna_owned_stage.py`; ещё 16 |
| <a id="chg-55bb7d5b45fa"></a>[CHG-55bb7d5b45fa](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/55bb7d5b45faddf501b5e98fb960b2e990b845c5)<br>2026-11-04T00:43:08+05:00 | Keep practical checkpoint requests stable across JSON readback | BASE90 | `apps/api/app/modules/ai/v3/practical_audit_units.py`; `apps/api/app/modules/ai/v3/practical_cycle.py`; `apps/api/app/modules/ai/v3/practical_patch.py`; ещё 6 |
| <a id="chg-c4a5c4c1e7be"></a>[CHG-c4a5c4c1e7be](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/c4a5c4c1e7be04932c68324cf879a671752a256e)<br>2026-11-04T00:23:59+05:00 | Implement coherent practical V3 courses with scoped source review | BASE90 | `apps/api/app/modules/ai/direct_luna_responses_factory.py`; `apps/api/app/modules/ai/managed_luna_client.py`; `apps/api/app/modules/ai/pipeline.py`; ещё 35 |
| <a id="chg-65bd0f6bda7a"></a>[CHG-65bd0f6bda7a](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/65bd0f6bda7a3c95a433ad2759c250165a728e9a)<br>2026-11-03T10:00:55+05:00 | fix(ai): retain lesson quality holds across course aggregation | BASE90 | `apps/api/app/modules/ai/v3/service.py`; `apps/api/tests/unit/test_v3_option_repair_convergence.py`; `apps/api/tests/unit/test_v3_structural_hold_course_integration.py` |
| <a id="chg-5ba7a900716d"></a>[CHG-5ba7a900716d](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/5ba7a900716dfe0bebe8bd20bd6e7d6df2b8d489)<br>2026-11-03T09:46:52+05:00 | fix(ai): preserve quality holds and bound fresh native claims | BASE90 | `apps/api/app/modules/ai/pipeline.py`; `apps/api/app/modules/ai/v3/option_repair.py`; `apps/api/app/modules/ai/v3/pending_stage_journal.py`; ещё 7 |
| <a id="chg-8eda63724094"></a>[CHG-8eda63724094](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/8eda637240946dcc904102e4f2a5456d824b4b75)<br>2026-11-03T08:38:38+05:00 | feat(ai): integrate source-grounded V3 with typed recovery and retained source evidence | BASE90 | `apps/api/app/core/celery_app.py`; `apps/api/app/modules/ai/application_evidence.py`; `apps/api/app/modules/ai/assessment_components.py`; ещё 304 |
| <a id="chg-bbfeb83c3069"></a>[CHG-bbfeb83c3069](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/bbfeb83c30690c01d5c19c1c1f5479d513670220)<br>2026-11-03T07:32:41+05:00 | fix(ai): bind direct response custody to the actual HTTPX wire encoder | BASE90 | `apps/api/app/modules/ai/direct_luna_responses_client.py` |
| <a id="chg-bf72e293c7ca"></a>[CHG-bf72e293c7ca](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/bf72e293c7caedc6e4c07790c467c25859899778)<br>2026-11-03T07:19:36+05:00 | fix(ai): bind review methods to typed result buckets before checkpoint completion | BASE90 | `apps/api/app/modules/ai/direct_luna_responses_client.py`; `apps/api/app/modules/ai/managed_response_rejection.py`; `apps/api/app/modules/ai/v3/batch_review_response_schema.py`; ещё 12 |
| <a id="chg-4e7b896239e9"></a>[CHG-4e7b896239e9](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/4e7b896239e9db00adfc27f2247d50fe477981c5)<br>2026-11-03T06:25:28+05:00 | fix(ai): type batch review artifacts and preserve legacy request identities | BASE90 | `apps/api/app/modules/ai/v3/batch_review_response_schema.py`; `apps/api/app/modules/ai/v3/batched_review.py`; `apps/api/app/modules/ai/v3/direct_luna_owned_stage.py`; ещё 11 |
| <a id="chg-20fa1df89c07"></a>[CHG-20fa1df89c07](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/20fa1df89c07bc894e8c8c9c560a5b93034bda8d)<br>2026-11-03T04:55:20+05:00 | Batch source-bound V3 reviews with blind-key separation and exact repair reuse | BASE90 | `apps/api/app/modules/ai/pipeline.py`; `apps/api/app/modules/ai/v3/batched_review.py`; `apps/api/app/modules/ai/v3/engine.py`; ещё 12 |
| <a id="chg-7f0f763a6b45"></a>[CHG-7f0f763a6b45](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/7f0f763a6b45a0d3e981d4f7afb1a02fda4a8669)<br>2026-11-03T04:08:43+05:00 | Bind V3 model schemas, atomic provider profile and rejected artifact custody | BASE90 | `apps/api/app/modules/ai/llm_client.py`; `apps/api/app/modules/ai/managed_luna_client.py`; `apps/api/app/modules/ai/managed_response_rejection.py`; ещё 21 |
| <a id="chg-e75e5fe81283"></a>[CHG-e75e5fe81283](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/e75e5fe81283c18718d22452115b10ba3cd86a20)<br>2026-11-03T02:24:58+05:00 | fix(ai): enforce typed lesson author contract and retain rejected responses privately | BASE90 | `apps/api/app/modules/ai/managed_luna_client.py`; `apps/api/app/modules/ai/managed_response_rejection.py`; `apps/api/app/modules/ai/v3/author_response_schema.py`; ещё 8 |
| <a id="chg-704aebcfe45a"></a>[CHG-704aebcfe45a](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/704aebcfe45a9f6776c5fda6660adea57f5a4383)<br>2026-11-03T01:24:36+05:00 | fix(dev): bound TLS broker health reads and verify reconnect | BASE90 | `apps/api/app/core/celery_app.py` |
| <a id="chg-37ddf59662c9"></a>[CHG-37ddf59662c9](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/37ddf59662c964d5982a4c1a62a16243c23f9e05)<br>2026-11-03T00:48:55+05:00 | fix(ai): bind confirmed references to literal source planning views | BASE90 | `apps/api/app/modules/ai/job_service.py`; `apps/api/app/modules/ai/pipeline.py`; `apps/api/app/modules/ai/v3/engine.py`; ещё 6 |
| <a id="chg-0b7ad8cfec10"></a>[CHG-0b7ad8cfec10](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/0b7ad8cfec109d26974adbb002452e8724e9bfa2)<br>2026-11-02T23:45:55+05:00 | fix(ai): preserve completed extraction work and align provider quality | BASE90 | `apps/api/app/modules/ai/managed_luna_client.py`; `apps/api/app/modules/ai/pipeline.py`; `apps/api/app/modules/ai/router.py`; ещё 9 |
| <a id="chg-749d14b9f99b"></a>[CHG-749d14b9f99b](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/749d14b9f99b0b8a8fc677b55d33b3312463525e)<br>2026-11-02T22:13:36+05:00 | feat(ai): add isolated managed Luna QA with owned recovery | BASE90 | `apps/api/app/modules/ai/direct_luna_responses_factory.py`; `apps/api/app/modules/ai/managed_luna_client.py`; `apps/api/app/modules/ai/pipeline.py`; ещё 9 |
| <a id="chg-1e13989543df"></a>[CHG-1e13989543df](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/1e13989543dfbfcc7ca0f675d80783c5e7b92e40)<br>2026-11-02T20:55:33+05:00 | fix(web): reconcile ambiguous generation dispatch without duplicate submissions | BASE90 | `docs/plans/2026-10-30_generation-engine-quality.md` |
| <a id="chg-614e7f03fc6a"></a>[CHG-614e7f03fc6a](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/614e7f03fc6a34a3509e00edbebabe971bea5492)<br>2026-11-02T20:38:22+05:00 | fix(ai): retain admitted jobs when broker publish outcome is unknown | OTHER_REF | `apps/api/app/modules/ai/job_service.py`; `apps/api/app/modules/ai/router.py` |
| <a id="chg-2726742d6faf"></a>[CHG-2726742d6faf](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/2726742d6faf98c39e1fcee634c91bd90c26a1bd)<br>2026-11-02T20:38:22+05:00 | fix(ai): retain admitted jobs when broker publish outcome is unknown | BASE90 | `apps/api/app/modules/ai/job_service.py`; `apps/api/app/modules/ai/router.py` |
| <a id="chg-a4f81b771694"></a>[CHG-a4f81b771694](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/a4f81b771694ca28948762bebe09e2c8b833a4c9)<br>2026-11-02T20:22:30+05:00 | fix(ai): yield direct generation before exhausting delivery budget | BASE90 | `apps/api/app/modules/ai/direct_luna_responses_client.py`; `apps/api/app/modules/ai/pipeline.py`; `apps/api/app/modules/ai/tasks.py`; ещё 4 |
| <a id="chg-24225328a860"></a>[CHG-24225328a860](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/24225328a8601772aa186a2b6eed215feb36a04c)<br>2026-11-02T20:22:30+05:00 | fix(ai): yield direct generation before exhausting delivery budget | OTHER_REF | `apps/api/app/modules/ai/direct_luna_responses_client.py`; `apps/api/app/modules/ai/pipeline.py`; `apps/api/app/modules/ai/tasks.py`; ещё 4 |
| <a id="chg-5120635f2424"></a>[CHG-5120635f2424](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/5120635f2424d83662a50c94815a5236e4142206)<br>2026-11-02T19:09:29+05:00 | fix(ai): fail closed on absent viewer identity without breaking progress stream | BASE90 | `apps/api/app/modules/ai/router.py`; `apps/api/tests/unit/test_v3_abandon_unknown.py` |
| <a id="chg-fa7f4369a64e"></a>[CHG-fa7f4369a64e](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/fa7f4369a64e5efd4b2157cfab8c985af76b8f7f)<br>2026-11-02T18:54:06+05:00 | fix(ai): retain unknown claims while explicitly abandoning owned generation | BASE90 | `apps/api/app/modules/ai/job_service.py`; `apps/api/app/modules/ai/router.py`; `apps/api/app/modules/ai/schemas.py`; ещё 1 |
| <a id="chg-15b335803ab7"></a>[CHG-15b335803ab7](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/15b335803ab77bcc8ad8377a27e8289aafc340d8)<br>2026-11-02T18:54:06+05:00 | fix(ai): retain unknown claims while explicitly abandoning owned generation | OTHER_REF | `apps/api/app/modules/ai/job_service.py`; `apps/api/app/modules/ai/router.py`; `apps/api/app/modules/ai/schemas.py`; ещё 1 |
| <a id="chg-db2230b126a5"></a>[CHG-db2230b126a5](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/db2230b126a5c412e93f4585cd2bf2f25abf178e)<br>2026-11-02T18:25:58+05:00 | fix(ai): fence scoped lesson and question revisions by persisted policy | BASE90 | `apps/api/app/modules/ai/pipeline.py`; `apps/api/app/modules/ai/router.py`; `apps/api/app/modules/ai/v3/engine.py`; ещё 11 |
| <a id="chg-1bc4cfcb49b4"></a>[CHG-1bc4cfcb49b4](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/1bc4cfcb49b4fb6dd1790bd349d0f6e81ca50457)<br>2026-11-02T18:25:58+05:00 | fix(ai): fence scoped lesson and question revisions by persisted policy | OTHER_REF | `apps/api/app/modules/ai/pipeline.py`; `apps/api/app/modules/ai/router.py`; `apps/api/app/modules/ai/v3/engine.py`; ещё 11 |
| <a id="chg-6e119ac6c2f3"></a>[CHG-6e119ac6c2f3](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/6e119ac6c2f3cbed3940b2fdc1d2370a758fd145)<br>2026-11-02T16:26:47+05:00 | fix: bind asynchronous generation refunds to their charge month | BASE90 | `apps/api/app/modules/ai/budget.py`; `apps/api/app/modules/ai/job_service.py` |
| <a id="chg-46b9cbe832eb"></a>[CHG-46b9cbe832eb](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/46b9cbe832eb035a8705320fc3b18c77b8fad579)<br>2026-11-02T16:26:47+05:00 | fix: bind asynchronous generation refunds to their charge month | OTHER_REF | `apps/api/app/modules/ai/budget.py`; `apps/api/app/modules/ai/job_service.py` |
| <a id="chg-c239594f3567"></a>[CHG-c239594f3567](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/c239594f35674b1b9122f1b5ecd87981c1614bfa)<br>2026-11-02T15:33:12+05:00 | fix: retain owned Luna rejection receipts without repeating requests | BASE90 | `apps/api/app/modules/ai/direct_luna_responses_client.py`; `apps/api/app/modules/ai/v3/pending_rejection_receipt.py`; `apps/api/app/modules/ai/v3/pending_stage_journal.py` |
| <a id="chg-1834ba297311"></a>[CHG-1834ba297311](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/1834ba297311f1b3b3d9bdd38ff3c8fa8a1d9287)<br>2026-11-02T15:33:12+05:00 | fix: retain owned Luna rejection receipts without repeating requests | OTHER_REF | `apps/api/app/modules/ai/direct_luna_responses_client.py`; `apps/api/app/modules/ai/v3/pending_rejection_receipt.py`; `apps/api/app/modules/ai/v3/pending_stage_journal.py` |
| <a id="chg-b40ac801c006"></a>[CHG-b40ac801c006](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/b40ac801c0068287e22b02b4713a88b6cf7ad604)<br>2026-11-02T15:02:24+05:00 | fix: classify rejected Luna responses without leaking provider text | OTHER_REF | `apps/api/app/modules/ai/direct_luna_responses_client.py` |
| <a id="chg-a66ac373501d"></a>[CHG-a66ac373501d](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/a66ac373501d2824dc11b731d4dd712b3e0bbc86)<br>2026-11-02T15:02:24+05:00 | fix: classify rejected Luna responses without leaking provider text | BASE90 | `apps/api/app/modules/ai/direct_luna_responses_client.py` |
| <a id="chg-4a5974242566"></a>[CHG-4a5974242566](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/4a597424256608ffff42a070df503c48cf9a57fa)<br>2026-11-02T10:29:36+05:00 | Align direct Luna test fixtures with response contract | BASE90 | `apps/api/tests/unit/test_v3_diversity_direct_journal.py`; `apps/api/tests/unit/test_v3_diversity_repair_selection.py`; `apps/api/tests/unit/test_v3_diversity_variant_author.py`; ещё 1 |
| <a id="chg-b7d4d78ce142"></a>[CHG-b7d4d78ce142](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/b7d4d78ce1425c99e1f3f1a22e9625785c0498f2)<br>2026-11-02T10:12:34+05:00 | Record sanitized Luna stage diagnostics | BASE90 | `apps/api/app/modules/ai/direct_luna_responses_client.py`; `apps/api/app/modules/ai/v3/direct_luna_owned_stage.py`; `apps/api/app/modules/ai/v3/direct_usage_metadata.py`; ещё 3 |
| <a id="chg-d0569ebfa7b3"></a>[CHG-d0569ebfa7b3](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/d0569ebfa7b3b3df43ffcd6c28a35fc3cbe35564)<br>2026-11-02T06:07:36+05:00 | fix(ai): flag exact cross-lesson duplicates | BASE90 | `apps/api/app/modules/ai/v3/exact_duplicate_review.py`; `apps/api/app/modules/ai/v3/service.py`; `apps/api/tests/unit/test_v3_diversity_service_binding.py`; ещё 2 |
| <a id="chg-81ffa9eda628"></a>[CHG-81ffa9eda628](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/81ffa9eda628d6d4869160bdf96a03473b5d4ab2)<br>2026-11-02T05:17:34+05:00 | fix(ai): preserve direct QA source and final-save custody | BASE90 | `apps/api/app/modules/ai/pipeline.py`; `apps/api/app/modules/ai/v3/adapter.py`; `apps/api/app/modules/ai/v3/assessment_projection.py`; ещё 49 |
| <a id="chg-0e58ecb9b450"></a>[CHG-0e58ecb9b450](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/0e58ecb9b45051bffd5b0f39d8372bda3a549b0a)<br>2026-11-02T02:14:29+05:00 | fix: validate direct QA answer explanations | BASE90 | `apps/api/app/modules/ai/pipeline.py`; `apps/api/app/modules/ai/v3/case_repair_gate.py`; `apps/api/app/modules/ai/v3/engine.py`; ещё 8 |
| <a id="chg-d3cfa50f9e86"></a>[CHG-d3cfa50f9e86](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/d3cfa50f9e86fc5ad41ce0736a611ffb082a39e7)<br>2026-11-02T01:21:40+05:00 | feat: add guarded direct Luna DEV generation | BASE90 | `apps/api/app/modules/ai/direct_luna_api.py`; `apps/api/app/modules/ai/direct_luna_responses_client.py`; `apps/api/app/modules/ai/direct_luna_responses_contract.py`; ещё 10 |
| <a id="chg-26ca44d10c2d"></a>[CHG-26ca44d10c2d](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/26ca44d10c2d66ecd3dd549c0781f1e0a4d18e56)<br>2026-11-02T00:32:23+05:00 | fix: secure DEV Luna acceptance and CI contracts | BASE90 | `apps/api/app/modules/ai/qa_luna_dev_route.py` |
| <a id="chg-05a1126f13aa"></a>[CHG-05a1126f13aa](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/05a1126f13aa995cd1c2e784da33ef1ac8e19d92)<br>2026-11-02T00:13:35+05:00 | feat: harden DEV course generation and learning workspace | BASE90 | `apps/api/app/modules/ai/job_service.py`; `apps/api/app/modules/ai/pipeline.py`; `apps/api/app/modules/ai/router.py`; ещё 10 |
| <a id="chg-4148c53bac8f"></a>[CHG-4148c53bac8f](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/4148c53bac8fb22d5b49de03a9d157c84f067ce0)<br>2026-11-01T14:36:26+05:00 | Fix V3 regression test quality checks | BASE90 | `apps/api/tests/unit/test_v3_case_citation_custody.py`; `apps/api/tests/unit/test_v3_citation_expansion.py`; `apps/api/tests/unit/test_v3_compatibility_recheck.py`; ещё 1 |
| <a id="chg-276540aefca7"></a>[CHG-276540aefca7](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/276540aefca71b39afce65fdb3ca9346e6d9dfe5)<br>2026-11-01T14:31:34+05:00 | Fix source-grounded V3 review and checkpoint custody | BASE90 | `apps/api/app/modules/ai/v3/case_repair_gate.py`; `apps/api/app/modules/ai/v3/citation_expansion.py`; `apps/api/app/modules/ai/v3/compatibility_recheck.py`; ещё 8 |
| <a id="chg-a55965e24d42"></a>[CHG-a55965e24d42](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/a55965e24d4210c8cf523e05a40beb46d0e43218)<br>2026-11-01T11:45:04+05:00 | Prepare V3 generation and source evidence for DEV | BASE90 | `apps/api/app/modules/ai/direct_source.py`; `apps/api/app/modules/ai/llm_client.py`; `apps/api/app/modules/ai/pipeline.py`; ещё 47 |
### Git 2026-10

| ID / дата | Изменение | Состояние исходников | Основные файлы |
|---|---|---|---|
| <a id="chg-a7564f1c33bd"></a>[CHG-a7564f1c33bd](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/a7564f1c33bdf9996e00308f2a1a8a5e6945c552)<br>2026-10-31T14:17:51+05:00 | fix(courses): fail-closed snapshot hash, strict authoritative revision and multi-doc check, parent course touch | BASE90 | `apps/api/tests/unit/test_v3_generation_engine.py` |
| <a id="chg-4f852a62ee2c"></a>[CHG-4f852a62ee2c](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/4f852a62ee2ce7a37e1a4364cba35218b8df2ab3)<br>2026-10-31T14:02:52+05:00 | fix(courses): enforce mandatory content hash, revision pinning, and exact defect resolutions | BASE90 | `apps/api/tests/unit/test_v3_generation_engine.py` |
| <a id="chg-23f545d3c062"></a>[CHG-23f545d3c062](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/23f545d3c0621afe9aa339368ad8865c55e7ff4a)<br>2026-10-31T13:39:27+05:00 | fix(ai-v3): bind source hold resolution to content hash and defect acknowledgment, enforce strict revision presence, and add ASGI test suite | BASE90 | `apps/api/app/modules/ai/v3/service.py`; `apps/api/tests/unit/test_v3_generation_engine.py` |
| <a id="chg-71da34cc6c99"></a>[CHG-71da34cc6c99](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/71da34cc6c999e00ece72d9bba2efd6f08c26bd7)<br>2026-10-31T13:00:29+05:00 | fix(ai-v3): verify chunk-level revision, connect methodologist hold resolution endpoint, and close critic schema fallback | BASE90 | `apps/api/app/modules/ai/v3/service.py`; `apps/api/tests/unit/test_v3_generation_engine.py` |
| <a id="chg-d3305630b12b"></a>[CHG-d3305630b12b](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/d3305630b12b5eacc3a54f508d7b82f0866e39df)<br>2026-10-31T12:33:58+05:00 | fix(ai-v3): unify unicode space normalization, verify source revision, isolate multi-doc provenance, and enforce strict critic scales | BASE90 | `apps/api/app/modules/ai/v3/service.py`; `apps/api/app/modules/ai/v3/validator.py`; `apps/api/tests/unit/test_v3_generation_engine.py` |
| <a id="chg-2f8637795b3c"></a>[CHG-2f8637795b3c](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/2f8637795b3cd2a0198640af7ef43fe9f7eff18b)<br>2026-10-31T12:18:45+05:00 | fix(ai-v3): unify critic schema with prompt, ground exact character coordinates, and resolve multi-doc quote ownership | BASE90 | `apps/api/app/modules/ai/v3/engine.py`; `apps/api/app/modules/ai/v3/models.py`; `apps/api/app/modules/ai/v3/service.py`; ещё 1 |
| <a id="chg-755f4eaa8ebf"></a>[CHG-755f4eaa8ebf](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/755f4eaa8ebf4a424dfef75d700e6e4140814932)<br>2026-10-31T11:51:28+05:00 | fix(ai-v3): isolate chunk content from metadata, ground quotes against corpus, enforce strict critic schema and hierarchy resolution | BASE90 | `apps/api/app/modules/ai/v3/service.py`; `apps/api/tests/unit/test_v3_generation_engine.py` |
| <a id="chg-ea7e39570103"></a>[CHG-ea7e39570103](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/ea7e39570103eadc314d9deb38087f020f780216)<br>2026-10-31T11:33:20+05:00 | fix(ai-v3): enforce strict critic schema, quote grounding against full_text, collision-free ID sanitization, and compound references | BASE90 | `apps/api/app/modules/ai/v3/service.py`; `apps/api/tests/unit/test_v3_generation_engine.py` |
| <a id="chg-a915ea50977b"></a>[CHG-a915ea50977b](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/a915ea50977b2d4518cebb49dbdff5992c0445a9)<br>2026-10-31T11:20:56+05:00 | fix(ai-v3): implement transitive dependency closure, boundary-safe reference resolution, and critic defect propagation | BASE90 | `apps/api/app/modules/ai/v3/engine.py`; `apps/api/app/modules/ai/v3/models.py`; `apps/api/app/modules/ai/v3/service.py`; ещё 1 |
| <a id="chg-c748f11687eb"></a>[CHG-c748f11687eb](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/c748f11687ebf011c68d1ad2663c04c53b708a87)<br>2026-10-31T10:42:57+05:00 | fix(ai-v3): implement collision-safe curriculum groups, dependency closures, honest audit report, and review propagation | BASE90 | `apps/api/app/modules/ai/pipeline.py`; `apps/api/app/modules/ai/v3/adapter.py`; `apps/api/app/modules/ai/v3/engine.py`; ещё 3 |
| <a id="chg-cefe945d30d3"></a>[CHG-cefe945d30d3](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/cefe945d30d376a2e4b2f1683847efa7d24ed05e)<br>2026-10-31T10:04:29+05:00 | fix(ai-v3): enforce strict full-quote grounding, general curriculum grouping, and honest needs_review status | BASE90 | `apps/api/app/modules/ai/v3/service.py`; `apps/api/app/modules/ai/v3/validator.py`; `apps/api/tests/unit/test_v3_generation_engine.py` |
| <a id="chg-82c26a7e9f87"></a>[CHG-82c26a7e9f87](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/82c26a7e9f8792ec232539037dd4d8ddadbccc19)<br>2026-10-31T09:17:39+05:00 | fix(ai-v3): implement independent quality validator, eliminate length bias shortcut, and fix domain contradictions | BASE90 | `apps/api/app/modules/ai/v3/adapter.py`; `apps/api/app/modules/ai/v3/models.py`; `apps/api/app/modules/ai/v3/service.py`; ещё 2 |
| <a id="chg-db4d85a0b8d1"></a>[CHG-db4d85a0b8d1](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/db4d85a0b8d1156ea1b60ea665456ffcd47dc62c)<br>2026-10-30T20:34:09+05:00 | feat(ai-v3): polish branch context in stems, distractor length constraints, and verification tools | BASE90 | `apps/api/app/modules/ai/v3/models.py`; `apps/api/app/modules/ai/v3/prompts.py` |
| <a id="chg-cad9cdb2832e"></a>[CHG-cad9cdb2832e](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/cad9cdb2832e762c89bde2f770d65cd73aa1325b)<br>2026-10-30T19:44:29+05:00 | test(ai-v3): add end-to-end service integration and adapter unit tests | BASE90 | `apps/api/tests/unit/test_v3_generation_engine.py` |
| <a id="chg-08349a329a22"></a>[CHG-08349a329a22](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/08349a329a2204b4888d186b1ce72f7f24f3d6ef)<br>2026-10-30T19:26:01+05:00 | feat(ai-v3): integrate V3 course co-generation engine into production pipeline and DB persistence | BASE90 | `apps/api/app/modules/ai/assessment_schema.py`; `apps/api/app/modules/ai/generation_engine.py`; `apps/api/app/modules/ai/job_service.py`; ещё 5 |
| <a id="chg-9fc86e07d7f2"></a>[CHG-9fc86e07d7f2](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/9fc86e07d7f234cc9cdc561f8282dff412ce319c)<br>2026-10-30T18:25:24+05:00 | feat(ai-v3): implement universal course didactic and multi-variant assessment bank architecture | BASE90 | `apps/api/app/modules/ai/v3/engine.py`; `apps/api/app/modules/ai/v3/models.py`; `apps/api/app/modules/ai/v3/prompts.py`; ещё 1 |
| <a id="chg-f41c9aabffd0"></a>[CHG-f41c9aabffd0](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/f41c9aabffd08c2958c35950efee67cfdde78f4a)<br>2026-10-30T17:52:47+05:00 | feat(ai): implement core contracts, prompts, and pipeline for V3 course co-generation engine | BASE90 | `apps/api/app/modules/ai/v3/engine.py`; `apps/api/app/modules/ai/v3/models.py`; `apps/api/app/modules/ai/v3/prompts.py`; ещё 1 |
| <a id="chg-463e03882741"></a>[CHG-463e03882741](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/463e038827412715a5f567ba4474c7d987b08ffb)<br>2026-10-30T10:09:28+05:00 | fix(ai): sanitize internal source/condition prefixes from student-facing question prompts | BASE90 | `apps/api/app/modules/ai/evidence_engine/application.py`; `scripts/dev/run_generation_quality.py` |
| <a id="chg-ee589ae48524"></a>[CHG-ee589ae48524](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/ee589ae48524d036822dfcf37728f71bd5d65925)<br>2026-10-30T09:53:36+05:00 | fix(dev): wrap parser exceptions in AllProvidersFailedError during replay | BASE90 | `scripts/dev/generation_quality_api.py` |
| <a id="chg-ab6da7eea3dd"></a>[CHG-ab6da7eea3dd](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/ab6da7eea3dd796343d0d935429be31ea8e541d9)<br>2026-10-30T09:47:17+05:00 | fix(ai): resolve bidirectional source offset mapping and clause-level ambiguity | BASE90 | `apps/api/app/modules/ai/lesson_cycle.py` |
| <a id="chg-0c5039299964"></a>[CHG-0c5039299964](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/0c5039299964214bb0de31558274a9b9e297d698)<br>2026-10-30T09:36:21+05:00 | fix(ai): accept fused nominalization of negated source verbs in surface review | BASE90 | `apps/api/app/modules/ai/evidence_engine/provider_engine.py` |
| <a id="chg-6460f010a319"></a>[CHG-6460f010a319](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/6460f010a31945db6ffb11e993ecabcb3c22304e)<br>2026-10-30T09:01:34+05:00 | fix(ai): resolve bullet-list teaching proofs, answer-only realizations, and quality API timeout | BASE90 | `apps/api/app/modules/ai/final_teaching_eligibility.py`; `apps/api/app/modules/ai/lesson_cycle.py`; `scripts/dev/generation_quality_api.py` |
| <a id="chg-0ad011ccbc81"></a>[CHG-0ad011ccbc81](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/0ad011ccbc81c64f69cf6181ec9511270596889d)<br>2026-10-30T08:18:40+05:00 | fix(ai): resolve lesson/quiz generation bottlenecks and apply P1-P8 quality pipeline improvements | BASE90 | `apps/api/app/modules/ai/component_surface_comparison.py`; `apps/api/app/modules/ai/conditional_connective.py`; `apps/api/app/modules/ai/evidence_engine/application.py`; ещё 12 |
| <a id="chg-5dd36ad0901a"></a>[CHG-5dd36ad0901a](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/5dd36ad0901a17afba37ea21269f8c44ba316d11)<br>2026-10-30T05:32:41+05:00 | Restore validated lesson realizations without repeated inference | BASE90 | `apps/api/app/modules/ai/evidence_engine/application.py`; `apps/api/app/modules/ai/lesson_surface_review.py`; `apps/api/app/modules/ai/worker_lesson_cycle.py`; ещё 2 |
| <a id="chg-0f073bbe6ae6"></a>[CHG-0f073bbe6ae6](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/0f073bbe6ae6d8593dae7373ca891db87c8fce9d)<br>2026-10-30T02:38:50+05:00 | Protect generation delivery ownership and timeouts | BASE90 | `apps/api/app/modules/ai/delivery_ownership.py`; `apps/api/app/modules/ai/direct_source.py`; `apps/api/app/modules/ai/job_service.py`; ещё 6 |
| <a id="chg-58416b23c0ac"></a>[CHG-58416b23c0ac](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/58416b23c0ac971f24c8aaa8389b73039f699d98)<br>2026-10-29T18:56:57+05:00 | Remove legacy implicit document converter endpoint | BASE90 | `apps/api/app/modules/ai/converter_remote.py` |
| <a id="chg-a76f8c695843"></a>[CHG-a76f8c695843](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/a76f8c6958438256953594bfd7e3a6f800dcf02a)<br>2026-10-29T18:21:03+05:00 | Support isolated VM development worker identity | BASE90 | `apps/api/app/modules/ai/qa_luna_dev_route.py`; `apps/api/app/modules/ai/worker_lesson_cycle.py` |
| <a id="chg-18694e3d7b94"></a>[CHG-18694e3d7b94](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/18694e3d7b94b6968f01bd5e55bd9e2627f7986f)<br>2026-10-29T16:57:11+05:00 | Fix durable worker question inventory checkpoints | BASE90 | `apps/api/app/modules/ai/worker_lesson_cycle.py` |
| <a id="chg-f2b90fb54f62"></a>[CHG-f2b90fb54f62](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/f2b90fb54f62d63f3e33883eb8199a6bbbc22591)<br>2026-10-29T16:16:02+05:00 | Add QA-only source review for converter boundaries | BASE90 | `apps/api/app/modules/ai/direct_source.py`; `apps/api/app/modules/ai/evidence_engine/application.py`; `apps/api/app/modules/ai/ingestion.py`; ещё 2 |
| <a id="chg-4603cc4794b1"></a>[CHG-4603cc4794b1](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/4603cc4794b142ff18d403bbc48bb17efc534210)<br>2026-10-29T14:52:07+05:00 | Prepare source-grounded generation candidate for DEV | BASE90 | `apps/api/app/modules/ai/application_evidence.py`; `apps/api/app/modules/ai/assessment_components.py`; `apps/api/app/modules/ai/assessment_counter_context.py`; ещё 127 |
| <a id="chg-4afaff38a761"></a>[CHG-4afaff38a761](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/4afaff38a761c148a47e9f05d7bb7cef8876289f)<br>2026-10-21T12:11:17+05:00 | fix(ai): isolate disputed assessment targets and retain visible coverage gaps | BASE90 | `apps/api/app/modules/ai/source_assessment_plan.py`; `apps/api/app/modules/ai/worker_lesson_cycle.py`; `docs/product/contract-modules/lesson-cycle/IMPACT_ADDENDUM_V13.md` |
| <a id="chg-3f89306f0857"></a>[CHG-3f89306f0857](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/3f89306f0857c62505a468231fed3a51fcc2a414)<br>2026-10-21T11:27:18+05:00 | fix(deps): clear blocking security audits for DEV lesson cycle | BASE90 | `docs/product/contract-modules/lesson-cycle/IMPACT_ADDENDUM_DEPENDENCIES_V1.md` |
| <a id="chg-dc363386c75a"></a>[CHG-dc363386c75a](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/dc363386c75a0368448c6823dc40b19857b369d8)<br>2026-10-21T11:18:33+05:00 | feat(ai): add source-planned lesson cycles behind isolated DEV gate | BASE90 | `apps/api/app/modules/ai/evidence_engine/application.py`; `apps/api/app/modules/ai/lesson_cycle.py`; `apps/api/app/modules/ai/pipeline.py`; ещё 6 |
| <a id="chg-386478de30ff"></a>[CHG-386478de30ff](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/386478de30ffed5ca2d2c81d062f91e0055807cf)<br>2026-10-20T22:31:16+05:00 | fix(ai): keep embedded alternative conditions with their deadlines | BASE90 | `apps/api/app/modules/ai/evidence_engine/provider_engine.py`; `docs/plans/2026-10-19_lombard-generation-quality.md` |
| <a id="chg-1a27d4b8acb2"></a>[CHG-1a27d4b8acb2](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/1a27d4b8acb2bcb3a2cc77019a5b73e8c3038b60)<br>2026-10-20T22:24:22+05:00 | fix(ai): preserve mixed document teaching order and conditional layout | BASE90 | `apps/api/app/modules/ai/evidence_engine/application.py`; `apps/api/app/modules/ai/evidence_engine/engine.py`; `apps/api/app/modules/ai/evidence_engine/provider_engine.py`; ещё 2 |
| <a id="chg-9165794b2070"></a>[CHG-9165794b2070](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/9165794b207099c50f83c3c71f7a57e6e6bd7ecd)<br>2026-10-20T21:46:26+05:00 | fix(ai): bind joint requirements and schedule questions to source contracts | BASE90 | `apps/api/app/modules/ai/evidence_engine/assessment_axes.py`; `apps/api/app/modules/ai/evidence_engine/operational_requirements.py`; `apps/api/app/modules/ai/evidence_engine/operational_schedule.py`; ещё 3 |
| <a id="chg-f20aac91461e"></a>[CHG-f20aac91461e](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/f20aac91461ec315ecb2096f9432ee57ec85ad93)<br>2026-10-20T20:51:51+05:00 | fix(ai): preserve independently reviewed option subsets after repair | BASE90 | `apps/api/app/modules/ai/evidence_engine/quality.py`; `apps/api/app/modules/ai/evidence_engine/semantic_assessment.py`; `docs/plans/2026-10-19_lombard-generation-quality.md` |
| <a id="chg-01f56336dc08"></a>[CHG-01f56336dc08](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/01f56336dc0899f67599139cf514bc2970795b60)<br>2026-10-20T19:50:00+05:00 | fix(ai): preserve conditional signature scope and reject empty recovery | BASE90 | `apps/api/app/modules/ai/evidence_engine/assessment_axes.py`; `apps/api/app/modules/ai/evidence_engine/quality.py`; `apps/api/app/modules/ai/evidence_engine/semantic_assessment.py`; ещё 2 |
| <a id="chg-665207f6d6a9"></a>[CHG-665207f6d6a9](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/665207f6d6a983aef7fb7d9539f3521d875f36e9)<br>2026-10-20T19:23:24+05:00 | fix(web): avoid promising nonexistent generation checkpoints | BASE90 | `docs/plans/2026-10-19_lombard-generation-quality.md` |
| <a id="chg-3667e29fc35e"></a>[CHG-3667e29fc35e](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/3667e29fc35e50fded24db6bccf533ce86240cd4)<br>2026-10-20T19:12:23+05:00 | fix(ai): bound complete course audits with sufficient execution time | BASE90 | `apps/api/app/core/celery_app.py`; `apps/api/app/modules/ai/job_service.py`; `docs/plans/2026-10-19_lombard-generation-quality.md` |
| <a id="chg-dea939c0a507"></a>[CHG-dea939c0a507](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/dea939c0a5076454b834b30daea1612c40bbf504)<br>2026-10-20T18:37:00+05:00 | fix(ai): close PDF response scopes and preserve readable lesson headings | BASE90 | `apps/api/app/modules/ai/evidence_engine/application.py`; `apps/api/app/modules/ai/evidence_engine/assessment_axes.py`; `apps/api/app/modules/ai/evidence_engine/provider_engine.py`; ещё 3 |
| <a id="chg-b1541a55b63f"></a>[CHG-b1541a55b63f](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/b1541a55b63f73502e9f7c4d577689dfbb3c66d5)<br>2026-10-20T17:38:12+05:00 | fix(ai): bind normative questions to complete source response contracts | BASE90 | `apps/api/app/modules/ai/evidence_engine/assessment_axes.py`; `apps/api/app/modules/ai/evidence_engine/operational_approval.py`; `apps/api/app/modules/ai/evidence_engine/quality.py`; ещё 2 |
| <a id="chg-237a9521ca96"></a>[CHG-237a9521ca96](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/237a9521ca9699c66b707dcd6c717bc438403088)<br>2026-10-20T16:48:42+05:00 | fix(ai): keep compound assessment stems neutral | BASE90 | `apps/api/app/modules/ai/evidence_engine/assessment_axes.py`; `apps/api/app/modules/ai/evidence_engine/quality.py`; `docs/plans/2026-10-19_lombard-generation-quality.md` |
| <a id="chg-c8ca2f827736"></a>[CHG-c8ca2f827736](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/c8ca2f8277362e41eeaddb17de8f8f4e2bd59d45)<br>2026-10-20T16:38:39+05:00 | fix(ai): preserve normative scope and source-owned assessment contrasts | BASE90 | `apps/api/app/modules/ai/evidence_engine/assessment_axes.py`; `apps/api/app/modules/ai/evidence_engine/provider_engine.py`; `apps/api/app/modules/ai/evidence_engine/quality.py`; ещё 2 |
| <a id="chg-57c7822dac3e"></a>[CHG-57c7822dac3e](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/57c7822dac3e68755bde784f9a8a9f4b45ea5785)<br>2026-10-20T15:58:56+05:00 | fix(web): identify saved partial generation as terminal result | BASE90 | `docs/plans/2026-10-19_lombard-generation-quality.md` |
| <a id="chg-b49c11be8aee"></a>[CHG-b49c11be8aee](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/b49c11be8aee32f3fbb8a9c3c55185574919a0ea)<br>2026-10-20T15:50:07+05:00 | fix(ai): audit constraint logic with bounded reasoning and scoped actions | BASE90 | `apps/api/app/modules/ai/evidence_engine/assessment_axes.py`; `apps/api/app/modules/ai/evidence_engine/quality.py`; `apps/api/app/modules/ai/evidence_engine/semantic_assessment.py`; ещё 2 |
| <a id="chg-fe4f6cf8220b"></a>[CHG-fe4f6cf8220b](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/fe4f6cf8220bd8bd8726052df0fac1ad910bd803)<br>2026-10-20T15:02:32+05:00 | fix(ai): preserve prohibition scope and reject unproven capability errors | BASE90 | `apps/api/app/modules/ai/evidence_engine/provider_engine.py`; `apps/api/app/modules/ai/evidence_engine/quality.py`; `apps/api/app/modules/ai/evidence_engine/semantic_assessment.py`; ещё 1 |
| <a id="chg-8ff668196b8b"></a>[CHG-8ff668196b8b](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/8ff668196b8b97507b671e0eb0a9ee49ce35c496)<br>2026-10-20T14:17:43+05:00 | fix(ai): preserve normative qualifications and bounded repair budget | BASE90 | `apps/api/app/modules/ai/evidence_engine/provider_engine.py`; `apps/api/app/modules/ai/evidence_engine/quality.py`; `apps/api/app/modules/ai/evidence_engine/semantic_assessment.py`; ещё 1 |
| <a id="chg-0a9d8aa824c7"></a>[CHG-0a9d8aa824c7](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/0a9d8aa824c78422839017f7969389878cda0038)<br>2026-10-20T13:40:28+05:00 | fix(ai): admit source-owned assessment shapes before review | BASE90 | `apps/api/app/modules/ai/evidence_engine/operational_approval.py`; `apps/api/app/modules/ai/evidence_engine/quality.py`; `apps/api/app/modules/ai/evidence_engine/semantic_assessment.py`; ещё 1 |
| <a id="chg-6ca1e16feb54"></a>[CHG-6ca1e16feb54](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/6ca1e16feb54c7a6d88bd6c0f9660d2b379b9dee)<br>2026-10-20T12:56:44+05:00 | fix(ai): recover invalid operational answer shapes before review | BASE90 | `apps/api/app/modules/ai/evidence_engine/quality.py`; `apps/api/app/modules/ai/evidence_engine/semantic_assessment.py`; `docs/plans/2026-10-19_lombard-generation-quality.md` |
| <a id="chg-eeb740af1764"></a>[CHG-eeb740af1764](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/eeb740af176445eca8728a8c6446360844355494)<br>2026-10-20T12:16:55+05:00 | fix(ai): preserve operational answer domains through independent review | BASE90 | `apps/api/app/modules/ai/evidence_engine/assessment_axes.py`; `apps/api/app/modules/ai/evidence_engine/quality.py`; `apps/api/app/modules/ai/evidence_engine/semantic_assessment.py`; ещё 1 |
| <a id="chg-0338f3b90728"></a>[CHG-0338f3b90728](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/0338f3b907288b1ed098921489c56a07a5577d1e)<br>2026-10-20T11:34:41+05:00 | fix(ai): assess full source duties and control responsibilities | BASE90 | `apps/api/app/modules/ai/evidence_engine/assessment_axes.py`; `apps/api/app/modules/ai/evidence_engine/operational_control.py`; `apps/api/app/modules/ai/evidence_engine/quality.py`; ещё 1 |
| <a id="chg-959624145592"></a>[CHG-959624145592](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/959624145592e643e3a10069e0ec7753217c7f5b)<br>2026-10-20T10:29:37+05:00 | fix(ai): preserve scoped decisions and teaching source order | BASE90 | `apps/api/app/modules/ai/evidence_engine/assessment_axes.py`; `apps/api/app/modules/ai/evidence_engine/operational_approval.py`; `apps/api/app/modules/ai/evidence_engine/operational_steps.py`; ещё 4 |
| <a id="chg-5784e285dab2"></a>[CHG-5784e285dab2](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/5784e285dab24a72600c0db0e6f85fd95dc81593)<br>2026-10-20T09:46:38+05:00 | fix(ai): focus source-owned duties and retain governing context | BASE90 | `apps/api/app/modules/ai/evidence_engine/assessment_axes.py`; `apps/api/app/modules/ai/evidence_engine/provider_engine.py`; `apps/api/app/modules/ai/evidence_engine/quality.py`; ещё 2 |
| <a id="chg-d616ff9ee336"></a>[CHG-d616ff9ee336](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/d616ff9ee336b18ecb8ba717f7d3dcffa0eeba8d)<br>2026-10-20T08:55:37+05:00 | fix(ai): account for every explicit source list child | BASE90 | `apps/api/app/modules/ai/evidence_engine/assessment_axes.py`; `apps/api/app/modules/ai/evidence_engine/quality.py`; `docs/plans/2026-10-19_lombard-generation-quality.md` |
| <a id="chg-fa363d609227"></a>[CHG-fa363d609227](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/fa363d6092274c7ab6946f8e3e0b939fd4d64376)<br>2026-10-20T08:32:00+05:00 | fix(ai): preserve original document structure and complete assessment targets | BASE90 | `apps/api/app/modules/ai/evidence_engine/application.py`; `apps/api/app/modules/ai/evidence_engine/assessment_axes.py`; `apps/api/app/modules/ai/evidence_engine/engine.py`; ещё 11 |
| <a id="chg-7ea58c268b8a"></a>[CHG-7ea58c268b8a](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/7ea58c268b8ac5d8303f635788f1c5af006d842f)<br>2026-10-20T06:45:40+05:00 | fix(ocr): corroborate scanned list boundaries and add private DEV transport | BASE90 | `docs/plans/2026-10-19_lombard-generation-quality.md` |
| <a id="chg-c0fd90aa901e"></a>[CHG-c0fd90aa901e](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/c0fd90aa901e95e5cce2d19577cfc52e1c865349)<br>2026-10-19T21:03:57+05:00 | fix(ai): preserve operational scope and assessment alternatives | BASE90 | `apps/api/app/modules/ai/evidence_engine/assessment_axes.py`; `apps/api/app/modules/ai/evidence_engine/models.py`; `apps/api/app/modules/ai/evidence_engine/quality.py`; ещё 1 |
| <a id="chg-fb9a8343fc04"></a>[CHG-fb9a8343fc04](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/fb9a8343fc04d6ebc4e79c954ebc95c5aac7232a)<br>2026-10-19T20:31:31+05:00 | fix(ai): complete source rule coverage and preserve writing scope | BASE90 | `apps/api/app/modules/ai/evidence_engine/assessment_axes.py`; `apps/api/app/modules/ai/evidence_engine/operational_approval.py`; `apps/api/app/modules/ai/evidence_engine/operational_coverage.py`; ещё 8 |
| <a id="chg-cdb7a6cba2db"></a>[CHG-cdb7a6cba2db](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/cdb7a6cba2db081b50e4294953d8db047134f44b)<br>2026-10-19T19:02:32+05:00 | fix(ai): preserve operational rule scope and explicit coverage | BASE90 | `apps/api/app/modules/ai/evidence_engine/assessment_axes.py`; `apps/api/app/modules/ai/evidence_engine/operational_steps.py`; `apps/api/app/modules/ai/evidence_engine/quality.py`; ещё 3 |
| <a id="chg-498769c35882"></a>[CHG-498769c35882](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/498769c35882a2ed09cd6774ef0450c2fc089d7c)<br>2026-10-19T17:44:38+05:00 | docs(qa): require clean original-document production acceptance after release | BASE90 | `docs/plans/2026-10-19_lombard-generation-quality.md` |
| <a id="chg-7ae2a22ce87c"></a>[CHG-7ae2a22ce87c](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/7ae2a22ce87c1be58dd319565d6aa87ff707ff5e)<br>2026-10-19T17:42:09+05:00 | docs(ai): record adaptive assessment DEV results and remove stale quota copy | BASE90 | `docs/plans/2026-10-19_lombard-generation-quality.md` |
| <a id="chg-7b536d07859e"></a>[CHG-7b536d07859e](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/7b536d07859e8f7745604945d66dfb9e5d1fd255)<br>2026-10-19T17:27:13+05:00 | fix(ai): bind regeneration worker transactions to tenant context | BASE90 | `apps/api/app/modules/ai/router.py`; `docs/plans/2026-10-19_lombard-generation-quality.md` |
| <a id="chg-402986228aab"></a>[CHG-402986228aab](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/402986228aabee7408665df559f591c7a3ef565c)<br>2026-10-19T17:04:35+05:00 | fix(ai): normalize quiz identity before guarded regeneration | BASE90 | `apps/api/app/modules/ai/router.py`; `docs/plans/2026-10-19_lombard-generation-quality.md` |
| <a id="chg-597ce7200306"></a>[CHG-597ce7200306](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/597ce7200306d75c397c5831c395ab0b77acd7de)<br>2026-10-19T16:54:30+05:00 | test(ai): assert reviewed regeneration delegation instead of legacy prompt count | BASE90 | `docs/plans/2026-10-19_lombard-generation-quality.md` |
| <a id="chg-2c1228c917ac"></a>[CHG-2c1228c917ac](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/2c1228c917ac543d508f3265cbccfe568e77cd74)<br>2026-10-19T16:47:41+05:00 | fix(ai): use adaptive reviewed tests in lesson regeneration | BASE90 | `apps/api/app/modules/ai/regeneration_assessment.py`; `apps/api/app/modules/ai/router.py`; `docs/plans/2026-10-19_lombard-generation-quality.md` |
| <a id="chg-aa91160665b4"></a>[CHG-aa91160665b4](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/aa91160665b43ffdae486368d5eff40bd0e2ea60)<br>2026-10-19T16:27:08+05:00 | fix(ai): repair ambiguous assessment ranges with exact option feedback | BASE90 | `apps/api/app/modules/ai/evidence_engine/quality.py`; `apps/api/app/modules/ai/evidence_engine/semantic_assessment.py`; `docs/plans/2026-10-19_lombard-generation-quality.md` |
| <a id="chg-7081c95584a9"></a>[CHG-7081c95584a9](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/7081c95584a9f598f291cbf6354317e4e2b80882)<br>2026-10-19T16:03:27+05:00 | fix(ai): scope adaptive questions to complete source conditions | BASE90 | `apps/api/app/modules/ai/evidence_engine/assessment_axes.py`; `apps/api/app/modules/ai/evidence_engine/engine.py`; `apps/api/app/modules/ai/evidence_engine/quality.py`; ещё 1 |
| <a id="chg-1552d6146c50"></a>[CHG-1552d6146c50](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/1552d6146c502e52c7c1cac782aba0c0817993d8)<br>2026-10-19T15:09:59+05:00 | fix(ai): preserve numeric rules and audit source-sized assessment batches | BASE90 | `apps/api/app/modules/ai/evidence_engine/provider_engine.py`; `apps/api/app/modules/ai/evidence_engine/quality.py`; `apps/api/app/modules/ai/evidence_engine/semantic_assessment.py`; ещё 1 |
| <a id="chg-23dece3f8aa6"></a>[CHG-23dece3f8aa6](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/23dece3f8aa686e180ba55d9bf08c7ac5d507840)<br>2026-10-19T14:34:05+05:00 | fix(ai): size source-grounded assessments by independent rule targets | BASE90 | `apps/api/app/modules/ai/converter_remote.py`; `apps/api/app/modules/ai/evidence_engine/application.py`; `apps/api/app/modules/ai/evidence_engine/assessment_axes.py`; ещё 6 |
| <a id="chg-8099de660657"></a>[CHG-8099de660657](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/8099de6606578db158ae8c25d3e6c612d8765397)<br>2026-10-19T13:11:50+05:00 | docs(quality): satisfy journal release contract and record navigation proof | BASE90 | `docs/plans/2026-10-19_lombard-generation-quality.md` |
| <a id="chg-32e3afa2f3af"></a>[CHG-32e3afa2f3af](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/32e3afa2f3af51f55fbb47aabb6ccb17fdd4dac5)<br>2026-10-19T13:08:29+05:00 | fix(ai): preserve operational source rules and readable course review | BASE90 | `apps/api/app/modules/ai/evidence_engine/application.py`; `apps/api/app/modules/ai/evidence_engine/assessment_axes.py`; `apps/api/app/modules/ai/evidence_engine/provider_engine.py`; ещё 3 |
| <a id="chg-c34007c6ddb5"></a>[CHG-c34007c6ddb5](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/c34007c6ddb5b3813c32fb6b8eb494d66e7c39d9)<br>2026-10-19T08:16:53+05:00 | feat(dev): integrate four reviewed runtime and staff improvements | BASE90 | `apps/api/app/modules/ai/llm_client.py`; `apps/api/app/modules/ai/pipeline.py`; `apps/api/app/modules/ai/reviewer.py`; ещё 1 |
| <a id="chg-46cecca6811a"></a>[CHG-46cecca6811a](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/46cecca6811a5c6340b38fad409135e8a55fc2d4)<br>2026-10-18T18:19:46+05:00 | merge: validate loop-safe cabinet60 worker on preserved DEV | BASE90 | merge/path history |
| <a id="chg-ab9cb5d403b9"></a>[CHG-ab9cb5d403b9](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/ab9cb5d403b9ee723fd28d4df371479634b9f204)<br>2026-10-18T18:19:24+05:00 | fix(worker): isolate short-lived task loops from API connection pooling | BASE90 | `apps/api/app/core/celery_app.py` |
| <a id="chg-af97f8b1ecd4"></a>[CHG-af97f8b1ecd4](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/af97f8b1ecd4e4ff28df0459289f3f9f92cc5b92)<br>2026-10-18T17:36:10+05:00 | fix(cabinet): consolidate reviewed workflow and course-quality repairs | BASE90 | `apps/api/app/modules/ai/evidence_engine/application.py`; `apps/api/app/modules/ai/evidence_engine/assessment_axes.py`; `apps/api/app/modules/ai/evidence_engine/semantic_assessment.py`; ещё 1 |
| <a id="chg-8d8f39818e38"></a>[CHG-8d8f39818e38](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/8d8f39818e3802a9ea7f06ec05055e0a192366c0)<br>2026-10-18T06:08:59+05:00 | fix(ai): reject unsupported temporal distractor assumptions | BASE90 | `apps/api/app/modules/ai/evidence_engine/semantic_assessment.py` |
| <a id="chg-f82759267a72"></a>[CHG-f82759267a72](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/f82759267a72082c178e9154d2acf25b00efbce4)<br>2026-10-18T05:50:48+05:00 | fix(ai): preserve explicit prohibitions in assessment selection | BASE90 | `apps/api/app/modules/ai/evidence_engine/assessment_axes.py` |
| <a id="chg-e1f95b386ad7"></a>[CHG-e1f95b386ad7](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/e1f95b386ad74ce9fe790bd75417f5e198fb47a4)<br>2026-10-18T05:38:41+05:00 | fix(ai): separate saved assessment review drafts from active generation | BASE90 | `apps/api/app/modules/ai/router.py` |
| <a id="chg-65a4a76fff07"></a>[CHG-65a4a76fff07](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/65a4a76fff072576be356c76a34a0c067c6c468a)<br>2026-10-18T05:20:50+05:00 | fix(ai): preserve reviewed operational counterfactual questions | BASE90 | `apps/api/app/modules/ai/evidence_engine/semantic_assessment.py` |
| <a id="chg-6caa02932855"></a>[CHG-6caa02932855](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/6caa029328554db05c882f9294b74fa44c5441b3)<br>2026-10-18T05:04:17+05:00 | fix(ai): prioritize operational assessment targets and audit critical gaps | BASE90 | `apps/api/app/modules/ai/evidence_engine/application.py`; `apps/api/app/modules/ai/evidence_engine/assessment_axes.py`; `apps/api/app/modules/ai/evidence_engine/semantic_assessment.py` |
| <a id="chg-61ae049c7b92"></a>[CHG-61ae049c7b92](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/61ae049c7b920ecc4488eb2500500108aa34fd27)<br>2026-10-16T17:01:43+05:00 | fix(ai): make evidence profile caps honor audited runtime settings | BASE90 | `apps/api/app/modules/ai/llm_client.py` |
| <a id="chg-24cf9aef03b5"></a>[CHG-24cf9aef03b5](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/24cf9aef03b592c8dfb52a2faacd1cea29d34519)<br>2026-10-16T16:52:58+05:00 | feat(admin): add audited hot runtime settings and scoped AI policies | BASE90 | `apps/api/app/modules/ai/llm_client.py`; `apps/api/app/modules/ai/pipeline.py`; `apps/api/app/modules/ai/reviewer.py`; ещё 1 |
| <a id="chg-c7d4cf3a6aea"></a>[CHG-c7d4cf3a6aea](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/c7d4cf3a6aea8cfacc5edee9514358ccc8819e62)<br>2026-10-16T14:59:52+05:00 | fix(ai): give assignment reserve its own bounded response budget | BASE90 | `apps/api/app/modules/ai/llm_client.py` |
| <a id="chg-a5e7e90b5ffb"></a>[CHG-a5e7e90b5ffb](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/a5e7e90b5ffb64b36dcfc692ab0eefa359ea60e2)<br>2026-10-16T04:23:17+05:00 | fix(ai): scope managed evidence reasoning to document answers | BASE90 | `apps/api/app/modules/ai/llm_client.py` |
| <a id="chg-18cc41e3a8f9"></a>[CHG-18cc41e3a8f9](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/18cc41e3a8f9a72be85a0977e82bad11e484f6f3)<br>2026-10-15T12:22:55+05:00 | feat(ai): install dormant official Codex CLI reserve with manual control | BASE90 | `apps/api/app/modules/ai/llm_client.py`; `infra/codex-reserve/.dockerignore`; `infra/codex-reserve/Dockerfile`; ещё 5 |
| <a id="chg-77f0b0651691"></a>[CHG-77f0b0651691](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/77f0b06516917426b0f5983787f803c9e4c575c4)<br>2026-10-15T08:26:37+05:00 | fix: preserve assignment fallback within bounded deadline | BASE90 | `apps/api/app/modules/ai/llm_client.py` |
| <a id="chg-92a32fefec1f"></a>[CHG-92a32fefec1f](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/92a32fefec1f9d6ac431d2c983f5d744e2fcf785)<br>2026-10-14T17:54:27+05:00 | feat(ai): persist private lesson dialogue with safe scoped recall | BASE90 | `apps/api/app/modules/ai/dialogue_models.py`; `apps/api/app/modules/ai/lesson_dialogue.py`; `apps/api/app/modules/ai/router.py`; ещё 1 |
| <a id="chg-3fe3c39acbd2"></a>[CHG-3fe3c39acbd2](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/3fe3c39acbd256d7e4fa65b91a0c22ce429c295f)<br>2026-10-14T11:32:12+05:00 | fix(ai): acknowledge valid marker-only lesson proposals | BASE90 | `apps/api/app/modules/ai/router.py` |
| <a id="chg-8a0677fc0830"></a>[CHG-8a0677fc0830](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/8a0677fc08303ca7f1cc93d88e5161911d447f2b)<br>2026-10-14T10:57:36+05:00 | release: prepare 0.11.49 assistant dialogue and source downloads | BASE90 | `apps/api/app/modules/ai/router.py` |
| <a id="chg-5e400ac302de"></a>[CHG-5e400ac302de](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/5e400ac302de6a45749ed158058759b333bfd103)<br>2026-10-14T10:46:24+05:00 | feat(ai): add correction source downloads and bounded dialogue history | BASE90 | `apps/api/app/modules/ai/router.py`; `apps/api/app/modules/ai/schemas.py` |
| <a id="chg-b06ee33cb4e8"></a>[CHG-b06ee33cb4e8](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/b06ee33cb4e882188e21f1a3a537fdab6cba910d)<br>2026-10-12T20:45:10+05:00 | fix: preserve PDF table facts and complete multiformat workflow usability | BASE90 | `apps/api/app/modules/ai/ingestion.py`; `apps/api/app/modules/ai/pdf_table_layout.py` |
| <a id="chg-97f4efd2834c"></a>[CHG-97f4efd2834c](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/97f4efd2834c9d6bb0056f848b79cb7ecbf85816)<br>2026-10-12T13:47:49+05:00 | fix(ai): separate source capacity estimates and preserve table identity | BASE90 | `apps/api/app/modules/ai/evidence_engine/provider_engine.py`; `apps/api/app/modules/ai/router.py`; `apps/api/app/modules/ai/source_analysis.py` |
| <a id="chg-422588f01b88"></a>[CHG-422588f01b88](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/422588f01b8835f727d2f18228757d4e990e5f0c)<br>2026-10-12T12:59:31+05:00 | fix(ai): preserve operational sources and repair source-bound assessments | BASE90 | `apps/api/app/modules/ai/document_passport.py`; `apps/api/app/modules/ai/evidence_engine/application.py`; `apps/api/app/modules/ai/evidence_engine/assessment_axes.py`; ещё 4 |
| <a id="chg-c453658aa30b"></a>[CHG-c453658aa30b](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/c453658aa30b1826d9395f976c6355d3bc760de9)<br>2026-10-10T18:43:38+05:00 | fix(ai): bind postfix prohibition assessment to source-owned question | BASE90 | `apps/api/app/modules/ai/evidence_engine/assessment_axes.py` |
| <a id="chg-d1bc925704c1"></a>[CHG-d1bc925704c1](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/d1bc925704c19d6a92e4b123bcaf404d157c37bf)<br>2026-10-10T17:44:51+05:00 | fix(ai): repair source-bound learner presentation | OTHER_REF | `apps/api/app/modules/ai/evidence_engine/application.py`; `apps/api/app/modules/ai/evidence_engine/assessment_axes.py`; `apps/api/app/modules/ai/evidence_engine/provider_engine.py`; ещё 1 |
| <a id="chg-5f4b890b20ef"></a>[CHG-5f4b890b20ef](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/5f4b890b20ef878edbc0a5d2ce5d72d7b642084e)<br>2026-10-10T17:44:51+05:00 | fix(ai): repair source-bound learner presentation | BASE90 | `apps/api/app/modules/ai/evidence_engine/application.py`; `apps/api/app/modules/ai/evidence_engine/assessment_axes.py`; `apps/api/app/modules/ai/evidence_engine/provider_engine.py`; ещё 1 |
| <a id="chg-d41d8c423289"></a>[CHG-d41d8c423289](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/d41d8c4232894aa4178008bd1a837dc9e3ccb4cf)<br>2026-10-06T07:17:51+05:00 | fix(workbench): align correction provenance with generated facts | BASE90 | `apps/api/app/modules/ai/evidence_engine/application.py`; `apps/api/app/modules/ai/evidence_engine/engine.py` |
| <a id="chg-e9509fdaf427"></a>[CHG-e9509fdaf427](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/e9509fdaf427c32280d480db505f6f0876a4857c)<br>2026-10-05T09:06:30+05:00 | fix(ai): guard assessment answer-length shortcuts and localize document workbench | BASE90 | `apps/api/app/modules/ai/evidence_engine/adapters.py`; `apps/api/app/modules/ai/evidence_engine/application.py`; `apps/api/app/modules/ai/evidence_engine/assessment_axes.py`; ещё 3 |
| <a id="chg-b7478d3b4320"></a>[CHG-b7478d3b4320](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/b7478d3b4320cafe09f0bce4e28fce7cf06b701c)<br>2026-10-04T14:13:41+05:00 | feat(workbench): add human-confirmed document draft plans | BASE90 | `apps/api/app/modules/ai/job_service.py`; `apps/api/app/modules/ai/router.py` |
| <a id="chg-301564b76a61"></a>[CHG-301564b76a61](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/301564b76a61e546b4a8036cd71c5048024efe72)<br>2026-10-04T09:05:19+05:00 | feat(workbench): add bounded free-text assignment interpretation | BASE90 | `apps/api/app/modules/ai/budget.py` |
### Git 2026-09

| ID / дата | Изменение | Состояние исходников | Основные файлы |
|---|---|---|---|
| <a id="chg-c5c8d21677ad"></a>[CHG-c5c8d21677ad](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/c5c8d21677adad0919044c98fda3c643dcd40a8b)<br>2026-09-29T21:25:10+05:00 | fix(ai): enforce tenant-aware provider routing | BASE90 | `apps/api/app/modules/ai/router.py` |
| <a id="chg-2d68b4d52a43"></a>[CHG-2d68b4d52a43](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/2d68b4d52a43b1233dd2579376d6ea6165bc77ee)<br>2026-09-28T11:35:21+05:00 | feat(source): add actuality review workflow | BASE90 | `apps/api/app/core/celery_app.py` |
| <a id="chg-66576b1a4ab3"></a>[CHG-66576b1a4ab3](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/66576b1a4ab33f201956aae0e3798aed26d0023b)<br>2026-09-26T10:48:53+05:00 | fix(ai): classify exact assessment claims | BASE90 | `apps/api/app/modules/ai/evidence_engine/assessment_axes.py` |
| <a id="chg-546ca47a7da2"></a>[CHG-546ca47a7da2](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/546ca47a7da213e7db2b00831be8a0680aa29796)<br>2026-09-26T09:37:15+05:00 | fix(ai): close corporate stage one acceptance gaps | BASE90 | `apps/api/app/modules/ai/evidence_engine/assessment_axes.py`; `apps/api/app/modules/ai/evidence_engine/semantic_assessment.py` |
| <a id="chg-9e2f039f0d44"></a>[CHG-9e2f039f0d44](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/9e2f039f0d44f61e975ed2d7eba3093468a215ee)<br>2026-09-25T14:23:19+05:00 | fix(ai): preserve valid courses after bounded omissions | BASE90 | `apps/api/app/modules/ai/evidence_engine/application.py`; `apps/api/app/modules/ai/evidence_engine/assessment_coverage.py`; `apps/api/app/modules/ai/evidence_engine/semantic_assessment.py` |
| <a id="chg-86714a3ff2f1"></a>[CHG-86714a3ff2f1](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/86714a3ff2f1245e6836ac51fbb3118aa36afa0a)<br>2026-09-25T11:55:50+05:00 | refactor(ai): retire legacy assessment engine | BASE90 | `apps/api/app/modules/ai/assessment.py`; `apps/api/app/modules/ai/assessment_audit.py`; `apps/api/app/modules/ai/assessment_completion.py`; ещё 4 |
| <a id="chg-ed6650857d97"></a>[CHG-ed6650857d97](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/ed6650857d9746d291c0d1f70d371d75fe82866e)<br>2026-09-23T16:57:10+05:00 | fix(ai): diversify tabular lessons and assessments | BASE90 | `apps/api/app/modules/ai/evidence_engine/application.py`; `apps/api/app/modules/ai/evidence_engine/provider_engine.py`; `apps/api/app/modules/ai/evidence_engine/semantic_assessment.py` |
| <a id="chg-cdb8977c5298"></a>[CHG-cdb8977c5298](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/cdb8977c5298265ef5e03cff27d431dfc481f350)<br>2026-09-23T16:17:06+05:00 | fix(ai): make evidence v2 the sole course generator | BASE90 | `apps/api/app/modules/ai/evidence_engine/application.py`; `apps/api/app/modules/ai/evidence_engine/engine.py`; `apps/api/app/modules/ai/generation_engine.py`; ещё 4 |
| <a id="chg-7e346cf4f213"></a>[CHG-7e346cf4f213](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/7e346cf4f2135d04faa5f614cc9a9dee7dbea689)<br>2026-09-23T13:59:04+05:00 | Expand source-owned course quality corpus | BASE90 | `apps/api/app/modules/ai/evidence_engine/provider_engine.py` |
| <a id="chg-d91a1474a310"></a>[CHG-d91a1474a310](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/d91a1474a310f1eb16a31b86e8b638ea8ab19733)<br>2026-09-23T12:55:05+05:00 | Improve source-bound course and assessment quality | BASE90 | `apps/api/app/modules/ai/evidence_engine/assessment_axes.py`; `apps/api/app/modules/ai/evidence_engine/models.py`; `apps/api/app/modules/ai/evidence_engine/provider_engine.py` |
| <a id="chg-8e051fde6c4a"></a>[CHG-8e051fde6c4a](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/8e051fde6c4ae1b3df0d7b5beb26adafaf6f8fa4)<br>2026-09-23T11:49:53+05:00 | test(ai): validate backward course quality with local GLM | BASE90 | `apps/api/app/modules/ai/document_passport.py`; `apps/api/app/modules/ai/evidence_engine/application.py`; `apps/api/app/modules/ai/evidence_engine/provider_engine.py`; ещё 2 |
| <a id="chg-6ec5e6157a85"></a>[CHG-6ec5e6157a85](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/6ec5e6157a85d34be8ccaf1fe16546f5f00fa9ea)<br>2026-09-23T09:43:35+05:00 | test(ai): add backward course-quality corpus and source density fixes | BASE90 | `apps/api/app/modules/ai/document_passport.py`; `apps/api/app/modules/ai/evidence_engine/application.py` |
| <a id="chg-7a69d405718d"></a>[CHG-7a69d405718d](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/7a69d405718da5d0b6e74b5fc599cd83ddab18da)<br>2026-09-22T23:08:45+05:00 | release: improve tenant workflows and assessment quality | BASE90 | `apps/api/app/modules/ai/assessment.py`; `apps/api/app/modules/ai/router.py` |
| <a id="chg-6dfaaf6ebc64"></a>[CHG-6dfaaf6ebc64](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/6dfaaf6ebc64c16b81f9a5b2831e530e4dbaab6d)<br>2026-09-22T15:19:49+05:00 | release: improve course quality and privileged quiz preview | BASE90 | `apps/api/app/modules/ai/architect.py`; `apps/api/app/modules/ai/direct_source.py`; `apps/api/app/modules/ai/structure_quality.py`; ещё 1 |
| <a id="chg-657946c7b3ec"></a>[CHG-657946c7b3ec](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/657946c7b3ec4b97034c38ecc1708ed354e2b814)<br>2026-09-19T21:02:52+05:00 | fix(ai): bound lesson assessment quality | BASE90 | `apps/api/app/modules/ai/evidence_engine/assessment_axes.py`; `apps/api/app/modules/ai/evidence_engine/assessment_coverage.py`; `apps/api/app/modules/ai/evidence_engine/semantic_assessment.py` |
| <a id="chg-3e2e21d3a212"></a>[CHG-3e2e21d3a212](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/3e2e21d3a212ec786f74422f2fba331b6cf0b90b)<br>2026-09-19T17:47:04+05:00 | fix(ai): satisfy strict assessment typing | BASE90 | `apps/api/app/modules/ai/evidence_engine/assessment_axes.py`; `apps/api/app/modules/ai/evidence_engine/semantic_assessment.py` |
| <a id="chg-098b622e75b9"></a>[CHG-098b622e75b9](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/098b622e75b9a24f4423d3d98c280f84434ab15f)<br>2026-09-19T17:40:24+05:00 | feat(ai): close source-owned assessment quality loop | BASE90 | `apps/api/app/modules/ai/evidence_engine/application.py`; `apps/api/app/modules/ai/evidence_engine/assessment_axes.py`; `apps/api/app/modules/ai/evidence_engine/engine.py`; ещё 3 |
| <a id="chg-7661aba31613"></a>[CHG-7661aba31613](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/7661aba31613c1d64fcc8f5a05ca4abc6f573efa)<br>2026-09-19T13:19:55+05:00 | feat(ai): release grounded assessments 0.7.3 | BASE90 | `apps/api/app/modules/ai/evidence_engine/application.py`; `apps/api/app/modules/ai/evidence_engine/assessment_axes.py`; `apps/api/app/modules/ai/evidence_engine/assessment_coverage.py`; ещё 9 |
| <a id="chg-46fccaec609f"></a>[CHG-46fccaec609f](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/46fccaec609fec852d4f384ea3ae8ed58fb6d3f2)<br>2026-09-18T10:43:39+05:00 | fix(ai): keep evidence courses proportional and grounded | BASE90 | `apps/api/app/modules/ai/document_passport.py`; `apps/api/app/modules/ai/evidence_engine/application.py`; `apps/api/app/modules/ai/evidence_engine/engine.py`; ещё 5 |
| <a id="chg-21a26a8d46c0"></a>[CHG-21a26a8d46c0](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/21a26a8d46c01f2150cd9cc97a0aa74ae27c16de)<br>2026-09-17T19:34:33+05:00 | fix(ci): enforce Python quality tooling for hierarchy release | BASE90 | `apps/api/app/modules/ai/audience_advisor.py` |
| <a id="chg-998a588c12ba"></a>[CHG-998a588c12ba](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/998a588c12ba40a4ed583d4144155ac4286c0f75)<br>2026-09-17T18:27:47+05:00 | feat: project hierarchy through training records | BASE90 | `apps/api/app/modules/ai/audience_advisor.py` |
| <a id="chg-96dc96ad06c3"></a>[CHG-96dc96ad06c3](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/96dc96ad06c337064f6aad7e93c2975cd1f67d7a)<br>2026-09-17T18:22:40+05:00 | feat: apply organization hierarchy to audience and qualifications | BASE90 | `apps/api/app/modules/ai/audience_advisor.py` |
| <a id="chg-371d86e6a094"></a>[CHG-371d86e6a094](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/371d86e6a094d114a83f9922dd3f3f9602736b9a)<br>2026-09-16T12:12:39+05:00 | fix(ai): preserve plain-text course structure | BASE90 | `apps/api/app/modules/ai/evidence_engine/application.py`; `apps/api/app/modules/ai/evidence_engine/engine.py` |
| <a id="chg-015d766746dc"></a>[CHG-015d766746dc](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/015d766746dc8d7469af1543e6338ff95e2430f8)<br>2026-09-16T11:04:47+05:00 | fix(ai): harden automatic course recovery | BASE90 | `apps/api/app/modules/ai/assessment.py`; `apps/api/app/modules/ai/direct_source.py` |
| <a id="chg-6b1c58b66d9c"></a>[CHG-6b1c58b66d9c](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/6b1c58b66d9c2dd130582b88bef6d5475bf02428)<br>2026-09-16T10:12:11+05:00 | fix(ai): recover useful course structure and quizzes | BASE90 | `apps/api/app/modules/ai/assessment.py`; `apps/api/app/modules/ai/direct_source.py` |
| <a id="chg-5cf0a8204190"></a>[CHG-5cf0a8204190](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/5cf0a820419022c03a41284951ee18b2dd984298)<br>2026-09-16T08:46:27+05:00 | fix(ai): harden synthetic evidence journey | BASE90 | `apps/api/app/modules/ai/evidence_engine/provider_engine.py`; `apps/api/app/modules/ai/evidence_engine/quality.py` |
| <a id="chg-90d65615b877"></a>[CHG-90d65615b877](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/90d65615b8776b6dd2bce6ce7d7a52a06700b8c8)<br>2026-09-15T13:53:17+05:00 | fix(ai): cover marketplace noun comparisons | BASE90 | `apps/api/app/modules/ai/lesson_quality.py` |
| <a id="chg-7d0606370f22"></a>[CHG-7d0606370f22](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/7d0606370f223579a149c9eb23f94eb9aeb58c47)<br>2026-09-15T13:21:34+05:00 | fix(ai): enforce evidence v2 quality gate | BASE90 | `apps/api/app/modules/ai/assessment.py`; `apps/api/app/modules/ai/evidence_engine/application.py`; `apps/api/app/modules/ai/evidence_engine/engine.py`; ещё 3 |
| <a id="chg-68e7b1454556"></a>[CHG-68e7b1454556](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/68e7b1454556c84bcd2dc8a202507fd96c366a58)<br>2026-09-15T11:36:52+05:00 | fix(ai): reject ambiguous assessment choices | BASE90 | `apps/api/app/modules/ai/assessment.py`; `apps/api/app/modules/ai/lesson_quality.py` |
| <a id="chg-7f8f1098d544"></a>[CHG-7f8f1098d544](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/7f8f1098d5440d352ca97bc881e00407535470e1)<br>2026-09-15T09:08:29+05:00 | fix(ci): remove obsolete mypy suppression | BASE90 | `apps/api/app/modules/ai/job_service.py` |
| <a id="chg-baa8a919afc0"></a>[CHG-baa8a919afc0](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/baa8a919afc0e31666c87a8cbc1a882230b23526)<br>2026-09-15T09:01:26+05:00 | feat(ai): release evidence-first course generation v2 | BASE90 | `apps/api/app/modules/ai/direct_source.py`; `apps/api/app/modules/ai/evidence_engine/application.py`; `apps/api/app/modules/ai/evidence_engine/provider_engine.py`; ещё 17 |
| <a id="chg-6eff95aa9dd7"></a>[CHG-6eff95aa9dd7](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/6eff95aa9dd78812c9dfbae7efee6e5c1f1a81cb)<br>2026-09-15T00:00:30+05:00 | experiment: define V2 publishability gate | BASE90 | `apps/api/app/modules/ai/evidence_engine/__init__.py`; `apps/api/app/modules/ai/evidence_engine/engine.py`; `apps/api/app/modules/ai/evidence_engine/provider_engine.py`; ещё 3 |
| <a id="chg-73f1f3abe185"></a>[CHG-73f1f3abe185](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/73f1f3abe1859a11082ff1723e6432e115688f33)<br>2026-09-14T22:56:56+05:00 | experiment: add provider-backed V2 simulation | BASE90 | `apps/api/app/modules/ai/evidence_engine/__init__.py`; `apps/api/app/modules/ai/evidence_engine/adapters.py`; `apps/api/app/modules/ai/evidence_engine/engine.py`; ещё 4 |
| <a id="chg-e2e882f59056"></a>[CHG-e2e882f59056](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/e2e882f59056cd3645c3f424067739311f923375)<br>2026-09-14T21:57:20+05:00 | experiment: add evidence-first course engine v2 | BASE90 | `apps/api/app/modules/ai/evidence_engine/__init__.py`; `apps/api/app/modules/ai/evidence_engine/adapters.py`; `apps/api/app/modules/ai/evidence_engine/engine.py`; ещё 1 |
| <a id="chg-e089324100ed"></a>[CHG-e089324100ed](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/e089324100ed531f88094ad42d23772146d650da)<br>2026-09-14T17:40:30+05:00 | fix(ai): keep generated questions within lesson scope | BASE90 | `apps/api/app/modules/ai/assessment.py` |
| <a id="chg-bfc30307a1fc"></a>[CHG-bfc30307a1fc](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/bfc30307a1fcc1713d4fd270aad34f8da525d361)<br>2026-09-14T15:58:37+05:00 | fix(ai): bind comparison courses to entity scope | BASE90 | `apps/api/app/modules/ai/assessment.py`; `apps/api/app/modules/ai/assessment_audit.py`; `apps/api/app/modules/ai/direct_source.py`; ещё 2 |
| <a id="chg-9ae9656ec031"></a>[CHG-9ae9656ec031](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/9ae9656ec031de01db40bb8651ec9bd7c0718883)<br>2026-09-14T13:02:40+05:00 | fix: bind generated course facts to source rows | BASE90 | `apps/api/app/modules/ai/assessment.py`; `apps/api/app/modules/ai/assessment_audit.py`; `apps/api/app/modules/ai/assessment_completion.py`; ещё 3 |
| <a id="chg-a09ebed1d9e8"></a>[CHG-a09ebed1d9e8](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/a09ebed1d9e856346e41d37ca8c324c91dd5119a)<br>2026-09-14T10:47:31+05:00 | fix(ai): audit assessments blindly and complete uncovered topics once | BASE90 | `apps/api/app/modules/ai/assessment.py`; `apps/api/app/modules/ai/assessment_audit.py`; `apps/api/app/modules/ai/assessment_completion.py`; ещё 4 |
| <a id="chg-4a3914fa7b25"></a>[CHG-4a3914fa7b25](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/4a3914fa7b25423c7abf17c3fec3d11843f674a6)<br>2026-09-14T07:40:45+05:00 | fix(ai): improve source-grounded generation and explicit draft quality in 0.5.42 | BASE90 | `apps/api/app/modules/ai/assessment.py`; `apps/api/app/modules/ai/direct_source.py`; `apps/api/app/modules/ai/lesson_quality.py`; ещё 4 |
| <a id="chg-ae81b12a845e"></a>[CHG-ae81b12a845e](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/ae81b12a845e21845bf505a6257e4f1f99d84cdb)<br>2026-09-14T05:57:02+05:00 | fix(ai): resume after provider exhaustion | BASE90 | `apps/api/app/modules/ai/pipeline.py` |
| <a id="chg-30df7307aad3"></a>[CHG-30df7307aad3](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/30df7307aad3cbbe903ce1ea008a3c71448bafa9)<br>2026-09-14T05:24:45+05:00 | fix(ai): retain grounded lesson content | BASE90 | `apps/api/app/modules/ai/direct_source.py`; `apps/api/app/modules/ai/lesson_quality.py` |
| <a id="chg-55c34fb5cfb8"></a>[CHG-55c34fb5cfb8](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/55c34fb5cfb82d84b34b2e3523a5a424f8ea91cd)<br>2026-09-14T04:44:33+05:00 | fix(ai): compact verbose source summaries | BASE90 | `apps/api/app/modules/ai/source_topic_map.py` |
| <a id="chg-fc5d9eb88665"></a>[CHG-fc5d9eb88665](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/fc5d9eb886651a526570b2aba6f3a639c800b6f1)<br>2026-09-14T04:30:21+05:00 | fix(ai): bound source maps by size | BASE90 | `apps/api/app/modules/ai/source_topic_map.py` |
| <a id="chg-7b6259a6405c"></a>[CHG-7b6259a6405c](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/7b6259a6405cd4bcf16d203d4508858bc304a92b)<br>2026-09-14T04:03:23+05:00 | fix(ai): retry transient provider connections | BASE90 | `apps/api/app/modules/ai/llm_client.py` |
| <a id="chg-d60eadd7b976"></a>[CHG-d60eadd7b976](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/d60eadd7b9769ad02afe022f9a61f05776da005a)<br>2026-09-14T03:31:45+05:00 | fix(ai): align saved course with accepted lessons | BASE90 | `apps/api/app/modules/ai/pipeline.py` |
| <a id="chg-610212ada74e"></a>[CHG-610212ada74e](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/610212ada74e7d0774d16efb43941f800cdc5252)<br>2026-09-14T02:43:16+05:00 | fix(ai): preserve checkpoint identity after omissions | BASE90 | `apps/api/app/modules/ai/direct_source.py`; `apps/api/app/modules/ai/generation_checkpoint.py`; `apps/api/app/modules/ai/pipeline.py`; ещё 1 |
| <a id="chg-b0a428cbd223"></a>[CHG-b0a428cbd223](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/b0a428cbd223356935f12359fbfe237731f351a7)<br>2026-09-14T01:58:02+05:00 | fix(ai): rebudget grounded source on quality retry | BASE90 | `apps/api/app/modules/ai/direct_source.py` |
| <a id="chg-f3f888fbdba1"></a>[CHG-f3f888fbdba1](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/f3f888fbdba1338d347be8a3cc7d539562a277d1)<br>2026-09-14T01:35:44+05:00 | fix(ai): accept detailed source topic maps | BASE90 | `apps/api/app/modules/ai/source_topic_map.py` |
| <a id="chg-dd4e26576844"></a>[CHG-dd4e26576844](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/dd4e265768442f43ac157b6b89dad6ab3528c529)<br>2026-09-14T01:10:33+05:00 | fix(ai): fit oversized OCR source excerpts | BASE90 | `apps/api/app/modules/ai/direct_source.py` |
| <a id="chg-c041e5ed0e7a"></a>[CHG-c041e5ed0e7a](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/c041e5ed0e7a0cce34dbafc561b770564491bbf3)<br>2026-09-14T00:38:18+05:00 | fix(ai): omit exhausted lessons without padding | BASE90 | `apps/api/app/modules/ai/direct_source.py`; `apps/api/app/modules/ai/pipeline.py` |
| <a id="chg-4a78d699b52a"></a>[CHG-4a78d699b52a](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/4a78d699b52a2e29a3d22c3780018b3ac1cbd29e)<br>2026-09-14T00:03:04+05:00 | fix(ai): trust approved lesson title heading | BASE90 | `apps/api/app/modules/ai/lesson_quality.py` |
| <a id="chg-8821bd3e4563"></a>[CHG-8821bd3e4563](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/8821bd3e4563437623bbc42047d1188bdbce752b)<br>2026-09-13T23:18:02+05:00 | fix(ai): preserve multi-source language admission | BASE90 | `apps/api/app/modules/ai/router.py` |
| <a id="chg-341577578612"></a>[CHG-341577578612](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/341577578612fa0d082df89aea2881e0f79dda8a)<br>2026-09-13T23:11:08+05:00 | fix(ai): queue large sources without duplicate conversion | BASE90 | `apps/api/app/modules/ai/router.py`; `apps/api/app/modules/ai/source_analysis.py` |
| <a id="chg-00fd0d9b8e31"></a>[CHG-00fd0d9b8e31](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/00fd0d9b8e316585da2fafc72eeed622b15c6d1b)<br>2026-09-13T20:09:31+05:00 | fix(ai): recognize flattened worksheet assessments | BASE90 | `apps/api/app/modules/ai/assessment.py` |
| <a id="chg-ae716dddacd5"></a>[CHG-ae716dddacd5](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/ae716dddacd52a192c2e849fcfaa086a91d9959d)<br>2026-09-13T19:35:27+05:00 | fix(ai): drop invalid structured questions without retries | BASE90 | `apps/api/app/modules/ai/assessment.py` |
| <a id="chg-3c5dae7779f1"></a>[CHG-3c5dae7779f1](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/3c5dae7779f1893175a763761327b0fdfac79429)<br>2026-09-13T19:14:25+05:00 | fix(ai): reject contextless structured questions | BASE90 | `apps/api/app/modules/ai/assessment.py` |
| <a id="chg-af8e48e34b17"></a>[CHG-af8e48e34b17](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/af8e48e34b17297c98c66cd432f8a86778900505)<br>2026-09-13T18:56:08+05:00 | fix(ai): keep course when a lesson has no valid quiz | BASE90 | `apps/api/app/modules/ai/assessment.py` |
| <a id="chg-5010879f4fa9"></a>[CHG-5010879f4fa9](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/5010879f4fa9cf95b274fd528fce93b625d255f8)<br>2026-09-13T18:35:00+05:00 | fix(ai): drop weak questions without quota padding | BASE90 | `apps/api/app/modules/ai/assessment.py` |
| <a id="chg-e811cce43339"></a>[CHG-e811cce43339](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/e811cce43339e62caa147e62c1bd061d28328096)<br>2026-09-13T17:43:46+05:00 | fix(ai): drop qualified assessment paraphrases | BASE90 | `apps/api/app/modules/ai/assessment.py` |
| <a id="chg-d7f313efa4e9"></a>[CHG-d7f313efa4e9](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/d7f313efa4e9f048f1fee85bf43b0cacd880a327)<br>2026-09-13T17:12:13+05:00 | fix(ai): drop cross-row assessment paraphrases | BASE90 | `apps/api/app/modules/ai/assessment.py` |
| <a id="chg-6dfc61106361"></a>[CHG-6dfc61106361](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/6dfc61106361a01af38d27f07d801d24816ebf07)<br>2026-09-13T16:21:50+05:00 | fix(ai): prefer unique assessment facts | BASE90 | `apps/api/app/modules/ai/assessment.py` |
| <a id="chg-cabea07799c9"></a>[CHG-cabea07799c9](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/cabea07799c927e7f61042a3e67e4f6c31fa1a26)<br>2026-09-13T15:31:46+05:00 | fix(ai): prefer question quality over padding | BASE90 | `apps/api/app/modules/ai/assessment.py` |
| <a id="chg-741f17d6096e"></a>[CHG-741f17d6096e](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/741f17d6096ee8546be34a8d496b8c8f07444f3e)<br>2026-09-13T14:25:10+05:00 | fix: make document embeddings resilient | BASE90 | `apps/api/app/modules/ai/ingestion.py`; `apps/api/app/modules/ai/llm_client.py`; `apps/api/app/modules/documents/operations.py` |
| <a id="chg-6f84a3865d89"></a>[CHG-6f84a3865d89](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/6f84a3865d89c397959664553822274f486b1240)<br>2026-09-13T13:02:45+05:00 | fix(ai): ground spreadsheet assessments and show indexing progress | BASE90 | `apps/api/app/modules/ai/assessment.py`; `apps/api/app/modules/ai/pipeline.py` |
| <a id="chg-954863eed86e"></a>[CHG-954863eed86e](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/954863eed86ed315c65486a156559a9530937121)<br>2026-09-13T11:07:07+05:00 | fix(ci): preserve Python quality baseline | BASE90 | `apps/api/app/modules/ai/assessment.py` |
| <a id="chg-a6d7c86dcd40"></a>[CHG-a6d7c86dcd40](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/a6d7c86dcd40d5277c7f2161aa02ad70b9c0c4a3)<br>2026-09-13T11:02:41+05:00 | fix(ai): revalidate resumed assessments | BASE90 | `apps/api/app/modules/ai/assessment.py` |
| <a id="chg-76c51c99fd5c"></a>[CHG-76c51c99fd5c](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/76c51c99fd5c695ae18181885f2dfbcf085729ab)<br>2026-09-13T08:59:40+05:00 | fix(ai): keep structured assessments deterministic | BASE90 | `apps/api/app/modules/ai/direct_source.py` |
| <a id="chg-1283f2fa0f35"></a>[CHG-1283f2fa0f35](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/1283f2fa0f350b9f904ce3ed3a2aa69b5e059fd9)<br>2026-09-13T08:22:45+05:00 | fix(ai): harden generated course assessment quality | BASE90 | `apps/api/app/modules/ai/assessment.py`; `apps/api/app/modules/ai/direct_source.py`; `apps/api/app/modules/ai/pipeline.py` |
| <a id="chg-766dd3846354"></a>[CHG-766dd3846354](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/766dd3846354435dcd44077256315ce636cd805a)<br>2026-09-12T22:15:22+05:00 | fix(ai): harden large workbook embeddings | BASE90 | `apps/api/app/modules/ai/llm_client.py` |
| <a id="chg-7ddecd886a75"></a>[CHG-7ddecd886a75](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/7ddecd886a7554d78d7a4579fefd2e94138deed5)<br>2026-09-12T21:03:24+05:00 | fix(ai): reject low-quality generated questions | BASE90 | `apps/api/app/modules/ai/assessment.py` |
| <a id="chg-81fcc979d81f"></a>[CHG-81fcc979d81f](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/81fcc979d81f6b3d9b798a3fdaf11472830b89fc)<br>2026-09-12T18:00:57+05:00 | fix(ai): route Qwen fallback privately | BASE90 | `apps/api/app/modules/ai/llm_client.py` |
| <a id="chg-040335520946"></a>[CHG-040335520946](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/0403355209468ce123e9ff7c0c2cff8759ef5757)<br>2026-09-12T15:42:43+05:00 | fix(ai): tolerate legacy job projections | BASE90 | `apps/api/app/modules/ai/router.py` |
| <a id="chg-63ed5fd82945"></a>[CHG-63ed5fd82945](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/63ed5fd829459abae19705ba3338bfc946e030f5)<br>2026-09-12T15:38:38+05:00 | feat(ai): report exact generation progress | BASE90 | `apps/api/app/modules/ai/ingestion.py`; `apps/api/app/modules/ai/llm_client.py`; `apps/api/app/modules/ai/pipeline.py`; ещё 3 |
| <a id="chg-817205c72b05"></a>[CHG-817205c72b05](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/817205c72b0520c8a6e6e1fde4e5ebd6eed30972)<br>2026-09-12T13:43:11+05:00 | fix(ai): preserve wide spreadsheet course structure | BASE90 | `apps/api/app/modules/ai/assessment.py`; `apps/api/app/modules/ai/direct_source.py`; `apps/api/app/modules/ai/ingestion.py` |
| <a id="chg-b322fa9c212b"></a>[CHG-b322fa9c212b](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/b322fa9c212bdbb8912e0b60f2d77d26bccab4fe)<br>2026-09-12T10:49:16+05:00 | fix(ai): enforce document-scoped source roles | BASE90 | `apps/api/app/modules/ai/direct_source.py`; `apps/api/app/modules/ai/document_passport.py` |
| <a id="chg-59f0a2c82a9d"></a>[CHG-59f0a2c82a9d](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/59f0a2c82a9dbe932c77c7f7993de3b174c65ad6)<br>2026-09-12T04:41:23+05:00 | fix(ai): generate grounded adaptive spreadsheet courses | BASE90 | `apps/api/app/modules/ai/direct_source.py`; `apps/api/app/modules/ai/lesson_quality.py` |
| <a id="chg-5450b92c7376"></a>[CHG-5450b92c7376](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/5450b92c73767fec24db780175970864ac114247)<br>2026-09-12T03:39:40+05:00 | fix(ai): guide grounded lesson repair | BASE90 | `apps/api/app/modules/ai/direct_source.py` |
| <a id="chg-762fb4505113"></a>[CHG-762fb4505113](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/762fb4505113a25d2cbe04d5777a697f79fffe66)<br>2026-09-12T03:22:37+05:00 | fix(ai): validate emphasized sales commands | BASE90 | `apps/api/app/modules/ai/lesson_quality.py` |
| <a id="chg-939def24b97c"></a>[CHG-939def24b97c](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/939def24b97ce78c178bc30220854b908610a249)<br>2026-09-12T03:16:59+05:00 | fix(ai): detect markdown sales commands | BASE90 | `apps/api/app/modules/ai/lesson_quality.py` |
| <a id="chg-eb83eec2774f"></a>[CHG-eb83eec2774f](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/eb83eec2774fce62ac3149a5b7fc25d79a44d93f)<br>2026-09-12T03:11:35+05:00 | fix(ai): distinguish sales commands from offer terms | BASE90 | `apps/api/app/modules/ai/lesson_quality.py` |
| <a id="chg-5abb020ad59f"></a>[CHG-5abb020ad59f](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/5abb020ad59f0df18b0550e3be546d4dc78fee8b)<br>2026-09-12T03:01:22+05:00 | fix(ai): block direct unstated sales recommendations | BASE90 | `apps/api/app/modules/ai/lesson_quality.py` |
| <a id="chg-887f45c04f41"></a>[CHG-887f45c04f41](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/887f45c04f41423488bd9ad4754e11fb34dc2240)<br>2026-09-12T02:53:20+05:00 | fix(ai): reject unstated sales advice in lessons | BASE90 | `apps/api/app/modules/ai/direct_source.py`; `apps/api/app/modules/ai/lesson_quality.py` |
| <a id="chg-27b2b3a2607a"></a>[CHG-27b2b3a2607a](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/27b2b3a2607a23adf0f6e5939e8884b25aca6c83)<br>2026-09-12T02:46:36+05:00 | fix(ai): retry grounded lesson quality repair | BASE90 | `apps/api/app/modules/ai/direct_source.py` |
| <a id="chg-0316f2f152ba"></a>[CHG-0316f2f152ba](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/0316f2f152babfad2bfaeb958ef870d4a92b9105)<br>2026-09-12T02:31:17+05:00 | fix(ai): preserve lesson-relevant assessment facts | BASE90 | `apps/api/app/modules/ai/assessment.py` |
| <a id="chg-0d46901b875d"></a>[CHG-0d46901b875d](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/0d46901b875d7a20a1f13dfa5d4905b317446843)<br>2026-09-12T02:15:22+05:00 | fix(ai): exhaust table facts before model fallback | BASE90 | `apps/api/app/modules/ai/assessment.py` |
| <a id="chg-12a264e334e1"></a>[CHG-12a264e334e1](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/12a264e334e15fd693f837cbd1d54bd3e3f0b536)<br>2026-09-12T01:56:24+05:00 | fix(ai): cover common relationship grammar | BASE90 | `apps/api/app/modules/ai/lesson_quality.py` |
| <a id="chg-ddf35bf25015"></a>[CHG-ddf35bf25015](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/ddf35bf250154ae70d4c71d22179b7bfdc192b09)<br>2026-09-12T01:49:24+05:00 | fix(ai): preserve linked claims and dotted evidence | BASE90 | `apps/api/app/modules/ai/lesson_quality.py` |
| <a id="chg-44c0238749d3"></a>[CHG-44c0238749d3](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/44c0238749d36d66c8366b57dc64420710685d69)<br>2026-09-12T01:41:28+05:00 | fix(ai): bind source claims to exact operators | BASE90 | `apps/api/app/modules/ai/assessment.py`; `apps/api/app/modules/ai/lesson_quality.py` |
| <a id="chg-68e04d1ff093"></a>[CHG-68e04d1ff093](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/68e04d1ff093183ddc836a886b751839097ff1c5)<br>2026-09-12T01:33:16+05:00 | fix(ai): preserve relationship direction in quality gate | BASE90 | `apps/api/app/modules/ai/assessment.py`; `apps/api/app/modules/ai/lesson_quality.py` |
| <a id="chg-22612a9ef1be"></a>[CHG-22612a9ef1be](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/22612a9ef1be5cd7bab4a9f2f743f5264237809d)<br>2026-09-12T01:25:55+05:00 | fix(ai): bind course evidence to stable lesson identity | BASE90 | `apps/api/app/modules/ai/assessment.py`; `apps/api/app/modules/ai/direct_source.py`; `apps/api/app/modules/ai/lesson_quality.py` |
| <a id="chg-7ee394decfd9"></a>[CHG-7ee394decfd9](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/7ee394decfd99bf9b8b098ad871e3a28dfefe218)<br>2026-09-12T01:11:18+05:00 | fix(ai): align acceptance with exact lesson evidence | BASE90 | `apps/api/app/modules/ai/assessment.py`; `apps/api/app/modules/ai/lesson_quality.py` |
| <a id="chg-1defea1f0f2b"></a>[CHG-1defea1f0f2b](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/1defea1f0f2b207c2169a8d8208686b0fa29a96f)<br>2026-09-12T00:56:55+05:00 | fix(ai): keep table scope and claims source-local | BASE90 | `apps/api/app/modules/ai/assessment.py`; `apps/api/app/modules/ai/lesson_quality.py` |
| <a id="chg-61753c64067a"></a>[CHG-61753c64067a](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/61753c64067a4db19fb44badeec99d1816c8ff7f)<br>2026-09-12T00:48:38+05:00 | fix(ai): close structured-course acceptance gaps | BASE90 | `apps/api/app/modules/ai/assessment.py`; `apps/api/app/modules/ai/lesson_quality.py` |
| <a id="chg-d31e51f1f1f2"></a>[CHG-d31e51f1f1f2](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/d31e51f1f1f2f0929e0aefbed2ef42ba233b3e0c)<br>2026-09-12T00:40:27+05:00 | fix(ai): parse converted workbook tables reliably | BASE90 | `apps/api/app/modules/ai/assessment.py`; `apps/api/app/modules/ai/lesson_quality.py` |
| <a id="chg-54e1d9a545e9"></a>[CHG-54e1d9a545e9](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/54e1d9a545e99e9d6ee541aeb2db37e49dc784e5)<br>2026-09-12T00:20:30+05:00 | fix(ai): validate vertical table courses end to end | BASE90 | `apps/api/app/modules/ai/assessment.py`; `apps/api/app/modules/ai/direct_source.py`; `apps/api/app/modules/ai/lesson_quality.py` |
| <a id="chg-e638c162629e"></a>[CHG-e638c162629e](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/e638c162629e413125f67eb32ff4a5b86170454a)<br>2026-09-11T23:58:05+05:00 | fix(ai): preserve repeated attributes by subject | BASE90 | `apps/api/app/modules/ai/assessment.py` |
| <a id="chg-d2110463fd20"></a>[CHG-d2110463fd20](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/d2110463fd202aafeaf7060d2c006e6134b8ba53)<br>2026-09-11T23:44:00+05:00 | fix(ai): ground partial-table quiz alternatives | BASE90 | `apps/api/app/modules/ai/assessment.py` |
| <a id="chg-63312a48cc5d"></a>[CHG-63312a48cc5d](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/63312a48cc5dd7bca325ad2f3961138b7e9e128d)<br>2026-09-11T23:26:08+05:00 | fix(ai): accept grounded style attributes | BASE90 | `apps/api/app/modules/ai/assessment.py` |
| <a id="chg-ec6f8573262d"></a>[CHG-ec6f8573262d](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/ec6f8573262d39dbc7c9318a3e3c75e0438e1525)<br>2026-09-11T23:11:45+05:00 | fix(ai): map indexed rows to lesson tables | BASE90 | `apps/api/app/modules/ai/assessment.py` |
| <a id="chg-20311ac1153c"></a>[CHG-20311ac1153c](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/20311ac1153c0ee86012f540a4f86a14a07ea283)<br>2026-09-11T22:57:31+05:00 | fix(ai): keep table quizzes source-only in all profiles | BASE90 | `apps/api/app/modules/ai/assessment.py` |
| <a id="chg-a3d80d317898"></a>[CHG-a3d80d317898](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/a3d80d317898e3efef8558b8fc4d4c739b62ceb5)<br>2026-09-11T22:41:44+05:00 | fix(ai): build grounded quizzes from structured tables | BASE90 | `apps/api/app/modules/ai/assessment.py` |
| <a id="chg-7c270b9baf03"></a>[CHG-7c270b9baf03](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/7c270b9baf03467108f8f7c17800971dbba8e2dc)<br>2026-09-11T22:03:46+05:00 | fix(ai): align distractor gate with client failure pattern | BASE90 | `apps/api/app/modules/ai/assessment.py` |
| <a id="chg-4605c8aabf2a"></a>[CHG-4605c8aabf2a](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/4605c8aabf2a2916048aef0fee9185e4920e5a93)<br>2026-09-11T21:45:47+05:00 | fix(ai): reject generic action-only distractors | BASE90 | `apps/api/app/modules/ai/assessment.py` |
| <a id="chg-129b91aedd21"></a>[CHG-129b91aedd21](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/129b91aedd21d056ba64baf6e7e8ab4d077ad087)<br>2026-09-11T21:29:15+05:00 | fix(ai): prioritize lesson-specific source evidence | BASE90 | `apps/api/app/modules/ai/assessment.py` |
| <a id="chg-8498421c615b"></a>[CHG-8498421c615b](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/8498421c615bc5d3be34bd4e4d2306ef014c6fbd)<br>2026-09-11T21:09:16+05:00 | fix(ai): prevent repeated facts across course quizzes | BASE90 | `apps/api/app/modules/ai/assessment.py` |
| <a id="chg-56411472292f"></a>[CHG-56411472292f](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/56411472292f7a01146ab6191032fd982a6fdaec)<br>2026-09-11T20:45:48+05:00 | fix(ai): ground course assessments in source evidence | BASE90 | `apps/api/app/modules/ai/assessment.py`; `apps/api/app/modules/ai/direct_source.py`; `apps/api/app/modules/ai/lesson_quality.py` |
| <a id="chg-e987f8d74253"></a>[CHG-e987f8d74253](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/e987f8d74253024c2f9991de96982ab4e9dea32e)<br>2026-09-11T20:16:50+05:00 | fix(ai): reject presentation-driven quiz questions | BASE90 | `apps/api/app/modules/ai/assessment.py` |
| <a id="chg-0920e4abebc0"></a>[CHG-0920e4abebc0](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/0920e4abebc045fc0649ed5443d4a08fe148cff9)<br>2026-09-11T19:56:29+05:00 | fix(ai): reject supporting-sheet course drift | BASE90 | `apps/api/app/modules/ai/assessment.py`; `apps/api/app/modules/ai/direct_source.py` |
| <a id="chg-dc7f71190e53"></a>[CHG-dc7f71190e53](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/dc7f71190e53650ff1e851c1f02d5a28381293c6)<br>2026-09-11T19:30:47+05:00 | fix(ai): reject low-information answer variants | BASE90 | `apps/api/app/modules/ai/assessment.py` |
| <a id="chg-cbfcdc7c78dc"></a>[CHG-cbfcdc7c78dc](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/cbfcdc7c78dc1bc570eb1f009ec2643e25b02b4f)<br>2026-09-11T19:09:09+05:00 | fix(ai): canonicalize passport worksheet grounding | BASE90 | `apps/api/app/modules/ai/direct_source.py` |
| <a id="chg-1863091cc717"></a>[CHG-1863091cc717](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/1863091cc71781924bf06a2933c5c56d538e571c)<br>2026-09-11T19:03:25+05:00 | fix(ai): ground lessons in primary source sections | BASE90 | `apps/api/app/modules/ai/direct_source.py` |
| <a id="chg-ad13dbed867f"></a>[CHG-ad13dbed867f](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/ad13dbed867f8b748f3db2b3082f18028f45a40f)<br>2026-09-11T18:50:11+05:00 | fix(ai): accept document passport section labels | BASE90 | `apps/api/app/modules/ai/direct_source.py` |
| <a id="chg-0f63e8da11b5"></a>[CHG-0f63e8da11b5](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/0f63e8da11b5a2622934dd6dbd3a09a136f818f9)<br>2026-09-11T18:11:44+05:00 | fix(ai): satisfy course quality release gate | BASE90 | `apps/api/app/modules/ai/direct_source.py`; `apps/api/app/modules/ai/document_passport.py`; `apps/api/app/modules/ai/ingestion.py`; ещё 1 |
| <a id="chg-358764aea776"></a>[CHG-358764aea776](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/358764aea776bb7399bfc3c0fce409ee29411b05)<br>2026-09-11T17:56:13+05:00 | feat(ai): add document passport quality gates | BASE90 | `apps/api/app/modules/ai/direct_source.py`; `apps/api/app/modules/ai/document_passport.py`; `apps/api/app/modules/ai/ingestion.py`; ещё 5 |
| <a id="chg-b3e396d7859c"></a>[CHG-b3e396d7859c](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/b3e396d7859cfb1990a4f9e0236119c09f89996e)<br>2026-09-11T11:55:04+05:00 | chore(ai): satisfy Python quality gate | BASE90 | `apps/api/app/modules/ai/job_service.py`; `apps/api/app/modules/ai/tasks.py` |
| <a id="chg-3aaf8bf0a9e8"></a>[CHG-3aaf8bf0a9e8](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/3aaf8bf0a9e83ee526bfe9bb5af1b6792a26008a)<br>2026-09-11T11:48:40+05:00 | fix(ai): resume course generation after soft timeout | BASE90 | `apps/api/app/modules/ai/job_service.py`; `apps/api/app/modules/ai/router.py`; `apps/api/app/modules/ai/tasks.py` |
| <a id="chg-6cc3e5e5a4fe"></a>[CHG-6cc3e5e5a4fe](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/6cc3e5e5a4fe7b5458517d23d6d51e0dc893c8f6)<br>2026-09-11T10:42:11+05:00 | fix(ai): preserve cancellation compatibility | BASE90 | `apps/api/app/modules/ai/router.py` |
| <a id="chg-c7fd68b02f3b"></a>[CHG-c7fd68b02f3b](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/c7fd68b02f3b7e9216ebc89b76dcd4960bff65c3)<br>2026-09-11T10:35:37+05:00 | fix(ai): satisfy release quality and save compatibility | BASE90 | `apps/api/app/modules/ai/job_service.py`; `apps/api/app/modules/ai/pipeline.py`; `apps/api/app/modules/ai/router.py`; ещё 1 |
| <a id="chg-e8a3f7ffeb89"></a>[CHG-e8a3f7ffeb89](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/e8a3f7ffeb89190c1ad19fea0bcd8dfaae6f45cb)<br>2026-09-11T10:25:31+05:00 | feat(ai): make course generation adaptive and resumable (0.5.0) | BASE90 | `apps/api/app/models/ai_generation_checkpoint.py`; `apps/api/app/modules/ai/architect.py`; `apps/api/app/modules/ai/assessment.py`; ещё 11 |
| <a id="chg-56f07a4bcbb9"></a>[CHG-56f07a4bcbb9](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/56f07a4bcbb96a32542a5cadf5243c6f5ad4cb47)<br>2026-09-10T18:35:16+05:00 | fix(ai): bound large Excel topic maps (0.4.4) | BASE90 | `apps/api/app/modules/ai/source_topic_map.py` |
| <a id="chg-849b6a28cc91"></a>[CHG-849b6a28cc91](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/849b6a28cc9105f5d02cf5602b7bf6b53935f834)<br>2026-09-10T16:54:34+05:00 | fix(ai): ground quiz answers in exact lesson evidence (0.4.3) | BASE90 | `apps/api/app/modules/ai/assessment.py` |
| <a id="chg-cf719ec996dc"></a>[CHG-cf719ec996dc](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/cf719ec996dcb6389bdb12800924e0a0aae048fa)<br>2026-09-10T15:49:33+05:00 | fix(ai): release 0.4.2 resilient full-source Excel generation | BASE90 | `apps/api/app/modules/ai/direct_source.py`; `apps/api/app/modules/ai/llm_client.py`; `apps/api/app/modules/ai/pipeline.py`; ещё 2 |
| <a id="chg-3c0519310d2c"></a>[CHG-3c0519310d2c](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/3c0519310d2c435de740eb5aad098b07bf012b1f)<br>2026-09-10T13:16:21+05:00 | fix(ai): bound one repair for overlong source map summaries | BASE90 | `apps/api/app/modules/ai/source_topic_map.py` |
| <a id="chg-808b768af806"></a>[CHG-808b768af806](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/808b768af806eac1c48b70435b3351dd8cddfa75)<br>2026-09-10T13:08:29+05:00 | fix(ai): deduplicate topic-map metadata for large Excel sources | BASE90 | `apps/api/app/modules/ai/source_topic_map.py` |
| <a id="chg-2c76e84235b3"></a>[CHG-2c76e84235b3](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/2c76e84235b3b5ce6af0d4a48be847443714bce0)<br>2026-09-10T12:07:42+05:00 | feat(ai): prepare 0.4.0 tenant providers and resilient course generation | BASE90 | `apps/api/app/modules/ai/assessment.py`; `apps/api/app/modules/ai/direct_source.py`; `apps/api/app/modules/ai/ingestion.py`; ещё 6 |
| <a id="chg-7a130815cfc6"></a>[CHG-7a130815cfc6](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/7a130815cfc6c47d7846db66598639c424915274)<br>2026-09-07T14:02:11+05:00 | fix(ai): parse apply marker before public redaction | BASE90 | `apps/api/app/modules/ai/router.py` |
| <a id="chg-b753ce45f637"></a>[CHG-b753ce45f637](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/b753ce45f63708a88b7dfe1c776e7993e59e31c6)<br>2026-09-07T12:55:23+05:00 | feat(admin): manage generation model routing | BASE90 | `apps/api/app/modules/ai/llm_client.py` |
| <a id="chg-9b2fad9056e2"></a>[CHG-9b2fad9056e2](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/9b2fad9056e2e6f64728b99a4c31a14bfb271d7d)<br>2026-09-07T12:00:39+05:00 | fix(ai): enforce owner-selected provider order | BASE90 | `apps/api/app/modules/ai/llm_client.py` |
| <a id="chg-1de7ed7ec6fc"></a>[CHG-1de7ed7ec6fc](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/1de7ed7ec6fc9ec4a1cf411fc9d7218c75482914)<br>2026-09-07T10:50:38+05:00 | feat(ai): prepare owner-selected provider chain | BASE90 | `apps/api/app/modules/ai/llm_client.py` |
| <a id="chg-e7beec59743a"></a>[CHG-e7beec59743a](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/e7beec59743a9690bb0762e3e098a701b09bd344)<br>2026-09-07T09:23:58+05:00 | fix(documents): persist shared indexing summaries | BASE90 | `apps/api/app/modules/ai/ingestion.py` |
| <a id="chg-9d7c60248280"></a>[CHG-9d7c60248280](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/9d7c60248280fb0b17cb124dd1c979d107b4d703)<br>2026-09-06T21:24:30+05:00 | fix(ai): make generation cancellation transactional | BASE90 | `apps/api/app/modules/ai/assessment.py`; `apps/api/app/modules/ai/job_service.py`; `apps/api/app/modules/ai/pipeline.py`; ещё 1 |
| <a id="chg-3442a2126165"></a>[CHG-3442a2126165](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/3442a2126165c7db69414431cb6508c5d8bb34c6)<br>2026-09-05T18:01:22+05:00 | feat(learning): add deadline reporting and opt-in recurring reminders | BASE90 | `apps/api/app/core/celery_app.py` |
| <a id="chg-8b6e7fb19a67"></a>[CHG-8b6e7fb19a67](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/8b6e7fb19a6792078d7399b3f139ceef8256b4e2)<br>2026-09-05T09:41:53+05:00 | fix(ai): constrain tenant assistant disclosures | BASE90 | `apps/api/app/modules/ai/assistant_policy.py`; `apps/api/app/modules/ai/router.py`; `apps/api/app/modules/ai/schemas.py` |
| <a id="chg-68e2c6083dda"></a>[CHG-68e2c6083dda](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/68e2c6083dda176ba3a46150a5db1f977963c5e0)<br>2026-09-03T12:50:52+05:00 | Harden course approval tenant workflow | BASE90 | `apps/api/app/core/celery_app.py` |
| <a id="chg-131afcbcacbf"></a>[CHG-131afcbcacbf](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/131afcbcacbf7302a1a62d8cf0b8eb081581ea32)<br>2026-09-02T17:34:27+05:00 | fix(ops): bound recovery scheduler interval | BASE90 | `apps/api/app/core/celery_app.py` |
| <a id="chg-115d7e23a71e"></a>[CHG-115d7e23a71e](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/115d7e23a71e1728d3d6fc798832bf90b4a6e41d)<br>2026-09-02T17:21:31+05:00 | fix(ops): schedule learning recovery in release worker | BASE90 | `apps/api/app/core/celery_app.py` |
| <a id="chg-30c02dcd1b96"></a>[CHG-30c02dcd1b96](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/30c02dcd1b96235eba98bcbf39a78025df79ee30)<br>2026-09-01T07:19:43+05:00 | feat(documents): expose YouTube source and provenance | BASE90 | `apps/api/app/modules/documents/schemas.py`; `apps/api/app/modules/documents/service.py` |
### Git 2026-08

| ID / дата | Изменение | Состояние исходников | Основные файлы |
|---|---|---|---|
| <a id="chg-d63bf52f46fb"></a>[CHG-d63bf52f46fb](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/d63bf52f46fbf70687fced0f2b481df5ce49a4aa)<br>2026-08-31T22:31:29+05:00 | fix(ai): preserve course source references | BASE90 | `apps/api/app/modules/ai/writer.py` |
| <a id="chg-b76ce5dc5145"></a>[CHG-b76ce5dc5145](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/b76ce5dc51450d1899cb569a9bbe0981ee15b5c8)<br>2026-08-31T22:05:28+05:00 | fix(ai): retry rejected focused assessments | BASE90 | `apps/api/app/modules/ai/assessment.py` |
| <a id="chg-7db785093a27"></a>[CHG-7db785093a27](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/7db785093a2703e739d609162a5cbca221938ccc)<br>2026-08-31T21:37:29+05:00 | fix(ai): recover assessments from focused evidence | BASE90 | `apps/api/app/modules/ai/assessment.py` |
| <a id="chg-de817fb82ae7"></a>[CHG-de817fb82ae7](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/de817fb82ae740d3273d5fbbba889e70434735ad)<br>2026-08-31T21:06:09+05:00 | fix(ai): recover questions across assessment retries | BASE90 | `apps/api/app/modules/ai/assessment.py` |
| <a id="chg-58e37f115e71"></a>[CHG-58e37f115e71](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/58e37f115e7174a01fb591c837a0dff328654c56)<br>2026-08-31T20:33:09+05:00 | fix(ai): recover valid assessment questions | BASE90 | `apps/api/app/modules/ai/assessment.py` |
| <a id="chg-dbdba7c4c4e8"></a>[CHG-dbdba7c4c4e8](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/dbdba7c4c4e861a9775ad1e4ab495bb4bbe57ee0)<br>2026-08-31T20:04:31+05:00 | fix(ci): satisfy assessment release gates | BASE90 | `apps/api/app/modules/ai/assessment.py` |
| <a id="chg-8706febac6a9"></a>[CHG-8706febac6a9](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/8706febac6a9e26921afe84f18d16ef0e42c5d44)<br>2026-08-31T19:53:05+05:00 | feat(ai): require review for generated assessments | BASE90 | `apps/api/app/modules/ai/assessment.py`; `apps/api/app/modules/ai/pipeline.py` |
| <a id="chg-b741bce711c7"></a>[CHG-b741bce711c7](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/b741bce711c72df203c9e4994dcd584987efc189)<br>2026-08-31T12:38:52+05:00 | fix(youtube): reuse analyzed transcript | BASE90 | `docs/plans/2026-08-31_youtube-source-cache-course-regeneration-plan.md` |
| <a id="chg-88d327ed1aa4"></a>[CHG-88d327ed1aa4](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/88d327ed1aa43e3549d47cb27b3119d7e2680d67)<br>2026-08-31T00:35:10+05:00 | fix(ai): enforce generated course size budget | BASE90 | `apps/api/app/modules/ai/architect.py`; `apps/api/app/modules/ai/pipeline.py`; `apps/api/app/modules/ai/router.py`; ещё 1 |
| <a id="chg-1cc8fb0fba5a"></a>[CHG-1cc8fb0fba5a](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/1cc8fb0fba5a392fa2339c6d862ac59e25ded3da)<br>2026-08-30T23:56:59+05:00 | fix(ai): tolerate partial job response fixtures | BASE90 | `apps/api/app/modules/ai/router.py` |
| <a id="chg-685247f7de85"></a>[CHG-685247f7de85](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/685247f7de85b352750a59ef0aebd00d2535a701)<br>2026-08-30T23:50:29+05:00 | fix(ai): restore active course generation | BASE90 | `apps/api/app/modules/ai/router.py`; `apps/api/app/modules/ai/schemas.py` |
| <a id="chg-9173d8f1fefc"></a>[CHG-9173d8f1fefc](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/9173d8f1fefcf1f2fb1ab67d446913a7322c7836)<br>2026-08-30T20:37:22+05:00 | fix(ci): align editor assistant release gates | BASE90 | `apps/api/app/modules/ai/llm_client.py`; `apps/api/app/modules/ai/question_preview.py` |
| <a id="chg-dce3affd0b40"></a>[CHG-dce3affd0b40](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/dce3affd0b40cd73856812309c559717571b45cc)<br>2026-08-30T20:29:12+05:00 | feat(quizzes): add methodologist question assistant preview | BASE90 | `apps/api/app/modules/ai/llm_client.py`; `apps/api/app/modules/ai/question_preview.py`; `docs/plans/2026-08-30-contextual-ai-editor-and-generation-quality-plan.md` |
| <a id="chg-42bc1e9dd171"></a>[CHG-42bc1e9dd171](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/42bc1e9dd171f960b3551cf015fe6ad306b7af2c)<br>2026-08-30T08:24:04+05:00 | fix(demo): return AI quota after admission failure | BASE90 | `apps/api/app/modules/ai/router.py` |
| <a id="chg-fbcd96f1ae2b"></a>[CHG-fbcd96f1ae2b](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/fbcd96f1ae2b9f4473fbe9b65d42f9df1b1dc0e7)<br>2026-08-30T08:04:00+05:00 | fix(ai): preserve ORM identifier compatibility | BASE90 | `apps/api/app/modules/ai/job_service.py` |
| <a id="chg-e3ce6e4a776a"></a>[CHG-e3ce6e4a776a](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/e3ce6e4a776a9d7766b177e68e5fd5b189fa9030)<br>2026-08-30T07:58:20+05:00 | feat(ai): support tenant-specific admission slots | BASE90 | `apps/api/app/modules/ai/job_service.py`; `apps/api/app/modules/ai/router.py` |
| <a id="chg-c525f0ec45df"></a>[CHG-c525f0ec45df](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/c525f0ec45dfbfca35c883b6f5da9fcb5bcaf221)<br>2026-08-30T05:52:02+05:00 | fix(dev): isolate inline YouTube execution | BASE90 | `apps/api/app/core/celery_app.py` |
| <a id="chg-285c8d888650"></a>[CHG-285c8d888650](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/285c8d888650a64142a169375dbac82a9bfdf975)<br>2026-08-30T05:13:35+05:00 | fix(dev): allow guarded eager task execution | BASE90 | `apps/api/app/core/celery_app.py` |
| <a id="chg-d4788da5f7d5"></a>[CHG-d4788da5f7d5](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/d4788da5f7d567ab45c7a55e493760873ca872c1)<br>2026-08-30T04:34:16+05:00 | fix(ci): type multi-source generation boundaries | BASE90 | `apps/api/app/modules/ai/router.py`; `apps/api/app/modules/ai/schemas.py`; `apps/api/app/modules/ai/source_analysis.py` |
| <a id="chg-dc2199318bce"></a>[CHG-dc2199318bce](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/dc2199318bce3d5692cb0ac81bbb0091dacacf67)<br>2026-08-30T04:19:25+05:00 | feat(ai): add governed multi-source course creation | BASE90 | `apps/api/app/core/celery_app.py`; `apps/api/app/modules/ai/router.py`; `apps/api/app/modules/ai/schemas.py`; ещё 2 |
| <a id="chg-a4438bc5eac8"></a>[CHG-a4438bc5eac8](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/a4438bc5eac8cccfb4b7f16650fba7fe0d86115c)<br>2026-08-29T09:34:10+05:00 | docs(product): plan YouTube course generation | BASE90 | `docs/plans/2026-08-29_youtube-course-generation-plan.md` |
| <a id="chg-b4cca57bded6"></a>[CHG-b4cca57bded6](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/b4cca57bded652c1c4b825c2cdcb6fff4ddb27a5)<br>2026-08-27T13:22:30+05:00 | fix(ai): satisfy context expansion quality gate | BASE90 | `apps/api/app/modules/ai/context_expansion.py` |
| <a id="chg-901df3658b13"></a>[CHG-901df3658b13](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/901df3658b13ae50d3ee1dc7de51779e05d63ef5)<br>2026-08-27T13:16:37+05:00 | fix(ai): deduplicate overlapping context windows | BASE90 | `apps/api/app/modules/ai/context_expansion.py` |
| <a id="chg-4de6358851dc"></a>[CHG-4de6358851dc](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/4de6358851dc22fadcb0a41320e4d52bad9c8069)<br>2026-08-27T12:51:50+05:00 | fix(ai): align document source revision with retrieval | BASE90 | `apps/api/app/modules/ai/ingestion.py`; `apps/api/app/modules/documents/operations.py` |
| <a id="chg-b85688931aba"></a>[CHG-b85688931aba](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/b85688931aba97040eb65ac37152fa3525a96830)<br>2026-08-27T10:18:15+05:00 | fix(ai): type provider response format mapping | BASE90 | `apps/api/app/modules/ai/llm_client.py` |
| <a id="chg-bd35f7a77eaf"></a>[CHG-bd35f7a77eaf](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/bd35f7a77eaf37232df087e2e5b7aa9fade952f3)<br>2026-08-27T10:12:36+05:00 | feat(ai): prioritize DeepSeek with local Qwen fallbacks | BASE90 | `apps/api/app/modules/ai/llm_client.py` |
| <a id="chg-57439672a6b5"></a>[CHG-57439672a6b5](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/57439672a6b5c61e0a5ccafcdbf34736d27c76cf)<br>2026-08-26T12:21:38+05:00 | fix(documents): require OCR before embedding scanned PDFs | BASE90 | `apps/api/app/modules/ai/ingestion.py`; `apps/api/app/modules/ai/tasks.py`; `apps/api/app/modules/documents/operations.py` |
| <a id="chg-e533555dd993"></a>[CHG-e533555dd993](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/e533555dd993f161ddbaae5959b6ebd1f4ca4454)<br>2026-08-25T16:15:40+05:00 | fix: verify text document embedding ids | BASE90 | `apps/api/app/modules/ai/ingestion.py` |
| <a id="chg-39c0a45eff0f"></a>[CHG-39c0a45eff0f](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/39c0a45eff0f43594474ea72a4af41cc1fc7f26e)<br>2026-08-24T19:34:23+05:00 | fix(api): offload document storage upload | BASE90 | `apps/api/app/modules/documents/router.py` |
| <a id="chg-d32c4262e2f4"></a>[CHG-d32c4262e2f4](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/d32c4262e2f42d37832d83c5be2c80817c257f80)<br>2026-08-23T20:09:28+05:00 | fix(ai): align KB-RAG release contracts | BASE90 | `apps/api/app/modules/ai/architect.py`; `apps/api/app/modules/ai/context_expansion.py`; `apps/api/app/modules/ai/embedding_provenance.py`; ещё 10 |
| <a id="chg-0492fd72dc18"></a>[CHG-0492fd72dc18](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/0492fd72dc18c760f91de7acc96cce14de72d9d1)<br>2026-08-23T19:41:00+05:00 | feat(ai): add hybrid KB-RAG lifecycle and release gates | BASE90 | `apps/api/app/modules/ai/architect.py`; `apps/api/app/modules/ai/context_expansion.py`; `apps/api/app/modules/ai/embedding_provenance.py`; ещё 10 |
| <a id="chg-758d41753830"></a>[CHG-758d41753830](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/758d41753830382db7473e46c171d477fa225897)<br>2026-08-20T21:07:53+05:00 | security: harden tenant runtime and release gates | BASE90 | `apps/api/app/modules/ai/architect.py`; `apps/api/app/modules/ai/assessment.py`; `apps/api/app/modules/ai/converter_remote.py`; ещё 9 |
| <a id="chg-ca8b523e3d90"></a>[CHG-ca8b523e3d90](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/ca8b523e3d90ddfa5596bfc6ffe5d260e557a596)<br>2026-08-20T16:17:09+05:00 | fix: exclude incomplete assessment evidence | BASE90 | `apps/api/app/modules/ai/assessment.py` |
| <a id="chg-0fbf57141d92"></a>[CHG-0fbf57141d92](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/0fbf57141d92536a245f7c61d9462712ff2639c3)<br>2026-08-20T16:10:21+05:00 | fix: repair unanchored assessment questions | BASE90 | `apps/api/app/modules/ai/assessment.py` |
| <a id="chg-08f846605ffc"></a>[CHG-08f846605ffc](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/08f846605ffc89b36948cfd5d90c642c135da77e)<br>2026-08-20T16:02:00+05:00 | fix: make grounded answers server-owned | BASE90 | `apps/api/app/modules/ai/assessment.py` |
| <a id="chg-ed4e71761b87"></a>[CHG-ed4e71761b87](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/ed4e71761b870bcdba53d9eeffcc110d796f84c4)<br>2026-08-20T15:54:04+05:00 | fix: enforce structured assessment responses | BASE90 | `apps/api/app/modules/ai/assessment.py` |
| <a id="chg-3daef5a0b735"></a>[CHG-3daef5a0b735](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/3daef5a0b7352c5096caabc1ec9ecda716fe42a6)<br>2026-08-20T15:38:49+05:00 | fix: make generated assessments reliably grounded | BASE90 | `apps/api/app/modules/ai/assessment.py`; `apps/api/app/modules/ai/pipeline.py` |
| <a id="chg-29aff6e76f6a"></a>[CHG-29aff6e76f6a](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/29aff6e76f6af156367faefc40399c082f8991fb)<br>2026-08-20T15:14:53+05:00 | fix: harden tenant acceptance flows | BASE90 | `apps/api/app/modules/ai/assessment.py`; `apps/api/app/modules/ai/assessment_schema.py` |
| <a id="chg-0a4c9a3b906c"></a>[CHG-0a4c9a3b906c](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/0a4c9a3b906c95a69cf09761ee085a712224e6ac)<br>2026-08-20T13:29:39+05:00 | fix(ai): create LLM usage rows with UUID | BASE90 | `apps/api/app/modules/ai/budget.py` |
| <a id="chg-98e17423897c"></a>[CHG-98e17423897c](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/98e17423897ca54afc4e561e09727abdd9d65a7b)<br>2026-08-20T13:04:06+05:00 | fix(documents): add local DOCX and PDF conversion | BASE90 | `apps/api/app/modules/ai/ingestion.py` |
| <a id="chg-282fcf02628b"></a>[CHG-282fcf02628b](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/282fcf02628b428d36dbc4345a36f3a0e39994e6)<br>2026-08-20T10:39:06+05:00 | feat(staff): add adaptive organizational import | BASE90 | `apps/api/app/core/celery_app.py` |
| <a id="chg-9c4d10e2b5cc"></a>[CHG-9c4d10e2b5cc](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/9c4d10e2b5ccb87502f29c5a5f9a4e21360e6098)<br>2026-08-13T14:17:01+05:00 | feat: add timed personal assignments and learner evidence | BASE90 | `apps/api/app/modules/ai/tasks.py` |
| <a id="chg-368116a278b5"></a>[CHG-368116a278b5](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/368116a278b525726109d6d14ebbc987ac009ae3)<br>2026-08-12T06:04:54+05:00 | feat: guard duplicate documents and source reuse | BASE90 | `apps/api/app/modules/ai/pipeline.py`; `apps/api/app/modules/ai/router.py`; `apps/api/app/modules/ai/schemas.py`; ещё 2 |
| <a id="chg-002d9c0fce1c"></a>[CHG-002d9c0fce1c](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/002d9c0fce1cd52fa089589d797ab29eefabba62)<br>2026-08-09T17:01:54+05:00 | feat: productionize learning access workflows | BASE90 | `apps/api/app/core/celery_app.py` |
| <a id="chg-0406eafaac6c"></a>[CHG-0406eafaac6c](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/0406eafaac6cec48e8de3b89d9d008291d8ff135)<br>2026-08-09T14:20:00+05:00 | feat: deliver leads to CRM through durable outbox | BASE90 | `apps/api/app/core/celery_app.py` |
| <a id="chg-7e601c43be85"></a>[CHG-7e601c43be85](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/7e601c43be85ebf9f1955d116d57af057f702987)<br>2026-08-08T19:47:33+05:00 | Harden sessions and generation execution | BASE90 | `apps/api/app/modules/ai/ingestion.py`; `apps/api/app/modules/ai/job_service.py`; `apps/api/app/modules/ai/pipeline.py`; ещё 2 |
| <a id="chg-021a3218176f"></a>[CHG-021a3218176f](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/021a3218176f0c78346fca4e4ad16056a86c60f3)<br>2026-08-08T08:45:03+05:00 | Make quiz builder safer and clarify answer types | BASE90 | `apps/api/app/modules/ai/pipeline.py` |
| <a id="chg-16af4ec2e830"></a>[CHG-16af4ec2e830](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/16af4ec2e83072601d4377a65a5d32020ca9ef53)<br>2026-08-07T10:33:43+05:00 | refactor AI job and frontend workflows | BASE90 | `apps/api/app/modules/ai/job_service.py`; `apps/api/app/modules/ai/router.py` |
| <a id="chg-f959a2368d39"></a>[CHG-f959a2368d39](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/f959a2368d3951a5f51731a8cf8063355afd1cdb)<br>2026-08-06T16:57:08+05:00 | fix(ai): persist generated lesson durations | BASE90 | `apps/api/app/modules/ai/pipeline.py` |
| <a id="chg-e274757565d8"></a>[CHG-e274757565d8](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/e274757565d85e52f2b9d592a960e9638cae759e)<br>2026-08-06T16:31:42+05:00 | fix(ai): reserve architect finalization turns | BASE90 | `apps/api/app/modules/ai/architect.py` |
| <a id="chg-c4a5eb8bf589"></a>[CHG-c4a5eb8bf589](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/c4a5eb8bf58989eff4f4338272dc68941bd416bd)<br>2026-08-06T15:20:31+05:00 | Prevent overlapping AI course lessons | BASE90 | `apps/api/app/modules/ai/writer.py` |
| <a id="chg-93f90b4a2472"></a>[CHG-93f90b4a2472](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/93f90b4a24728974988ba8e6df1ac7d8a0d1fb4e)<br>2026-08-06T14:41:18+05:00 | Fix OCR course provenance chunk IDs | BASE90 | `apps/api/app/modules/ai/ingestion.py`; `apps/api/app/modules/ai/writer.py` |
| <a id="chg-ce6a7008bc63"></a>[CHG-ce6a7008bc63](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/ce6a7008bc630cbca391a9136c642b20b41d7bc3)<br>2026-08-06T13:50:46+05:00 | fix: harden tenant demo and provider failover | BASE90 | `apps/api/app/modules/ai/llm_client.py` |
| <a id="chg-929e2e8d4eba"></a>[CHG-929e2e8d4eba](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/929e2e8d4ebab103575f820d6a6c428d09e356dd)<br>2026-08-04T11:40:58+05:00 | feat(ai): add tenant-fair generation admission | BASE90 | `apps/api/app/modules/ai/job_service.py`; `apps/api/app/modules/ai/router.py`; `apps/api/app/modules/ai/schemas.py` |
| <a id="chg-3364344c9ca8"></a>[CHG-3364344c9ca8](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/3364344c9ca8939e89d12ba3456c2084bfab9721)<br>2026-08-03T17:07:25+05:00 | feat(infra): isolate document and AI workloads | BASE90 | `apps/api/app/core/celery_app.py`; `apps/api/app/modules/ai/ingestion.py` |
| <a id="chg-c57178c5fa60"></a>[CHG-c57178c5fa60](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/c57178c5fa60da599a0787632ca680622fdd53d8)<br>2026-08-03T15:04:02+05:00 | feat(documents): add hybrid MarkItDown conversion routing | BASE90 | `apps/api/app/modules/ai/ingestion.py`; `apps/api/app/modules/documents/operations.py` |
| <a id="chg-43b0545cb417"></a>[CHG-43b0545cb417](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/43b0545cb417bea5da3bb12ee4b94e6ad8df9f51)<br>2026-08-03T12:58:41+05:00 | feat(evidence): harden invitations procedures and retention | BASE90 | `apps/api/app/core/celery_app.py`; `apps/api/app/modules/ai/job_service.py`; `apps/api/app/modules/documents/cleanup.py`; ещё 2 |
### Git 2026-07

| ID / дата | Изменение | Состояние исходников | Основные файлы |
|---|---|---|---|
| <a id="chg-b9ed78efb0e6"></a>[CHG-b9ed78efb0e6](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/b9ed78efb0e6f7b34f04fa165a146c87978bae81)<br>2026-07-30T15:01:07+05:00 | fix(quizzes): localize generated test titles | BASE90 | `apps/api/app/modules/ai/pipeline.py` |
| <a id="chg-4e8c3c24c157"></a>[CHG-4e8c3c24c157](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/4e8c3c24c15704c15ceebd9d1e7047764080a781)<br>2026-07-30T14:11:35+05:00 | fix(ai): enforce complete generated assessments | BASE90 | `apps/api/app/modules/ai/assessment.py` |
| <a id="chg-d1c8b1c0bb0d"></a>[CHG-d1c8b1c0bb0d](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/d1c8b1c0bb0d33a519b5b734bdd02632ea406caf)<br>2026-07-30T13:59:08+05:00 | fix(ai): keep generated assessments reviewable | BASE90 | `apps/api/app/modules/ai/assessment.py` |
| <a id="chg-74e77c3b10a4"></a>[CHG-74e77c3b10a4](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/74e77c3b10a47e38348e4429d57b3990be979cb9)<br>2026-07-30T13:33:24+05:00 | feat(evidence): preserve course releases and quiz attempts | BASE90 | `apps/api/app/modules/ai/assessment.py`; `apps/api/app/modules/ai/pipeline.py`; `apps/api/app/modules/ai/writer.py` |
| <a id="chg-2fe135c77e3e"></a>[CHG-2fe135c77e3e](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/2fe135c77e3e7c0669aa764371d36084471cea95)<br>2026-07-30T12:49:38+05:00 | fix(ai): recover from unsupported course outlines | BASE90 | `apps/api/app/modules/ai/pipeline.py`; `apps/api/app/modules/ai/writer.py` |
| <a id="chg-a082486ae952"></a>[CHG-a082486ae952](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/a082486ae952e1fcaad88860df0ac974e97867ed)<br>2026-07-30T12:37:33+05:00 | fix(documents): return upload after tenant commit | BASE90 | `apps/api/app/modules/documents/router.py` |
| <a id="chg-c04a49bb8a15"></a>[CHG-c04a49bb8a15](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/c04a49bb8a1524896349a784cca9d938a5b89515)<br>2026-07-30T12:03:29+05:00 | fix(documents): move OCR indexing to durable worker | BASE90 | `apps/api/app/modules/ai/converter_remote.py`; `apps/api/app/modules/ai/ingestion.py`; `apps/api/app/modules/documents/router.py`; ещё 1 |
| <a id="chg-f3df397c9a32"></a>[CHG-f3df397c9a32](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/f3df397c9a326964b17d4d8aa9370ecbb5995547)<br>2026-07-29T18:26:32+05:00 | fix(reliability): harden async jobs and storage transactions | BASE90 | `apps/api/app/modules/ai/pipeline.py`; `apps/api/app/modules/ai/router.py`; `apps/api/app/modules/ai/tasks.py` |
| <a id="chg-3418c0e2a1eb"></a>[CHG-3418c0e2a1eb](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/3418c0e2a1eb4cc303b3acbee8d6c92f9a518fd6)<br>2026-07-28T15:29:52+05:00 | fix(ai): enforce audience advisory boundaries | BASE90 | `apps/api/app/modules/ai/audience_advisor.py`; `apps/api/app/modules/ai/router.py` |
| <a id="chg-a1664fe29c8b"></a>[CHG-a1664fe29c8b](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/a1664fe29c8ba07ad939a18351e554bf05492db5)<br>2026-07-28T15:07:53+05:00 | fix(ai): harden audience advisor context and i18n | BASE90 | `apps/api/app/modules/ai/audience_advisor.py`; `apps/api/app/modules/ai/schemas.py` |
| <a id="chg-af8ab40c799b"></a>[CHG-af8ab40c799b](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/af8ab40c799be3e3402c8a75f270e03a74afb8e0)<br>2026-07-28T14:29:36+05:00 | feat(ai): add read-only audience recommendations | BASE90 | `apps/api/app/modules/ai/audience_advisor.py`; `apps/api/app/modules/ai/router.py`; `apps/api/app/modules/ai/schemas.py` |
| <a id="chg-89548c6f369b"></a>[CHG-89548c6f369b](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/89548c6f369b9ef9b2ae1bf0f8a1624c1bfe23a8)<br>2026-07-28T08:43:24+05:00 | fix(documents): recover missing sources safely | BASE90 | `apps/api/app/modules/ai/router.py`; `apps/api/app/modules/ai/schemas.py`; `apps/api/app/modules/documents/operations.py` |
| <a id="chg-365c8b9e2298"></a>[CHG-365c8b9e2298](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/365c8b9e229860e17390f73266e36aa94f6af2d9)<br>2026-07-27T18:38:56+05:00 | feat(p1): harden role onboarding and async workflows | BASE90 | `apps/api/app/modules/ai/router.py`; `apps/api/app/modules/ai/schemas.py` |
| <a id="chg-955764e6a230"></a>[CHG-955764e6a230](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/955764e6a230384a17e6617f0f6c7f5d115330c6)<br>2026-07-25T11:40:46+05:00 | fix(worker): isolate async tasks and flag missing source blobs | BASE90 | `apps/api/app/modules/ai/tasks.py`; `apps/api/app/modules/documents/operations.py` |
| <a id="chg-9d08a9016c52"></a>[CHG-9d08a9016c52](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/9d08a9016c526542a66d660df7ba64e2c663fae9)<br>2026-07-25T10:44:24+05:00 | feat(documents): complete durable source library rollout | BASE90 | `apps/api/app/modules/ai/router.py`; `apps/api/app/modules/ai/source_analysis.py`; `apps/api/app/modules/ai/tasks.py`; ещё 5 |
| <a id="chg-b3a460875e52"></a>[CHG-b3a460875e52](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/b3a460875e52fd5b3f76efa1adb779ed5fed5307)<br>2026-07-24T16:15:27+05:00 | fix(documents): preserve expand-compatible source rollout | BASE90 | `apps/api/app/modules/documents/router.py`; `apps/api/app/modules/documents/schemas.py`; `apps/api/app/modules/documents/service.py` |
| <a id="chg-0e56893baee3"></a>[CHG-0e56893baee3](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/0e56893baee3f173dbdc4157642cd6f7fadf2f2e)<br>2026-07-24T15:57:08+05:00 | feat(documents): expose paginated source catalog | BASE90 | `apps/api/app/modules/documents/router.py`; `apps/api/app/modules/documents/service.py` |
| <a id="chg-4641a1d255fc"></a>[CHG-4641a1d255fc](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/4641a1d255fc1e140b697e3767a6f7012d53a7e8)<br>2026-07-24T15:52:36+05:00 | feat(db): expand document source catalog metadata | BASE90 | `apps/api/app/modules/documents/schemas.py` |
| <a id="chg-d94ad205843d"></a>[CHG-d94ad205843d](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/d94ad205843df83aeb2f1a9b1a6acb084be71bf7)<br>2026-07-23T18:16:10+05:00 | secure and productionize Docling OCR | BASE90 | `apps/api/app/modules/ai/converter_remote.py`; `apps/api/app/modules/ai/ingestion.py` |
| <a id="chg-afab37a40e28"></a>[CHG-afab37a40e28](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/afab37a40e28724c4741704b47efff869b6a8d7a)<br>2026-07-23T17:49:05+05:00 | fix tenant gates and enable docling OCR | BASE90 | `apps/api/app/modules/ai/router.py` |
| <a id="chg-add2f6758fdf"></a>[CHG-add2f6758fdf](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/add2f6758fdfff7df2bf5759090aa09721459183)<br>2026-07-23T13:34:23+05:00 | fix learner progress and quiz copy | BASE90 | `apps/api/app/modules/ai/pipeline.py` |
| <a id="chg-42c7c72bb048"></a>[CHG-42c7c72bb048](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/42c7c72bb048e6fd956dac47063e4aab8c2c350f)<br>2026-07-23T12:49:55+05:00 | ground methodologist assistant in course content | BASE90 | `apps/api/app/modules/ai/router.py` |
| <a id="chg-937c0697660b"></a>[CHG-937c0697660b](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/937c0697660b6951cb1e73e9b46a370430b6c4fe)<br>2026-07-23T12:49:48+05:00 | add cohere embedding fallback | BASE90 | `apps/api/app/modules/ai/ingestion.py`; `apps/api/app/modules/ai/llm_client.py` |
| <a id="chg-506c38bc54f7"></a>[CHG-506c38bc54f7](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/506c38bc54f72be44da4012666fb8e0d4ef516a8)<br>2026-07-23T12:31:37+05:00 | handle voyage embedding rate limits | BASE90 | `apps/api/app/modules/ai/ingestion.py`; `apps/api/app/modules/ai/llm_client.py` |
| <a id="chg-6b17948262fd"></a>[CHG-6b17948262fd](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/6b17948262fdb26b88a3a2c9a7f4bfd3c41e1273)<br>2026-07-23T12:25:13+05:00 | refund failed ai generation quota | BASE90 | `apps/api/app/modules/ai/pipeline.py`; `apps/api/app/modules/ai/router.py` |
| <a id="chg-30d892947efe"></a>[CHG-30d892947efe](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/30d892947efec87dee5afc08eda0e0e808464968)<br>2026-07-23T12:21:40+05:00 | fix ai generation status encoding | BASE90 | `apps/api/app/modules/ai/pipeline.py` |
| <a id="chg-6042aadc994e"></a>[CHG-6042aadc994e](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/6042aadc994e98aba522e4feb0cc636dca99064b)<br>2026-07-23T12:11:49+05:00 | prefer voyage for document embeddings | BASE90 | `apps/api/app/modules/ai/llm_client.py` |
| <a id="chg-58b5fe57446a"></a>[CHG-58b5fe57446a](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/58b5fe57446aeaf1e6ae20303c87cc01cc851690)<br>2026-07-23T12:08:00+05:00 | prefer deepseek for llm generation | BASE90 | `apps/api/app/modules/ai/llm_client.py` |
| <a id="chg-1025089b09ca"></a>[CHG-1025089b09ca](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/1025089b09ca076ffeb614c597a5eac926a7dbc0)<br>2026-07-23T12:05:20+05:00 | fix voyage embedding fallback dimensions | BASE90 | `apps/api/app/modules/ai/llm_client.py` |
| <a id="chg-a829582cd407"></a>[CHG-a829582cd407](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/a829582cd40770a142fc1ea96382acc1d5643980)<br>2026-07-22T10:54:23+05:00 | fix: flush websocket rejection frames | BASE90 | `apps/api/app/modules/ai/router.py` |
| <a id="chg-62095663dc76"></a>[CHG-62095663dc76](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/62095663dc762018ca9e9be4b2b43a60ce8ed4b7)<br>2026-07-22T10:29:24+05:00 | fix: deliver websocket authorization close codes | BASE90 | `apps/api/app/modules/ai/router.py` |
| <a id="chg-2a76e063e03d"></a>[CHG-2a76e063e03d](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/2a76e063e03d88c098eee98c006d1ad3aa3268d9)<br>2026-07-22T09:50:36+05:00 | fix: harden tenant auth role policy and release gates | BASE90 | `apps/api/app/modules/ai/router.py` |
| <a id="chg-564748add24a"></a>[CHG-564748add24a](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/564748add24ab47ef5832ad17e29762488b40470)<br>2026-07-21T14:35:23+05:00 | feat(ai): govern course sources and harden release tests | BASE90 | `apps/api/app/modules/ai/architect.py`; `apps/api/app/modules/ai/ingestion.py`; `apps/api/app/modules/ai/pipeline.py`; ещё 6 |
| <a id="chg-4c994c31ee86"></a>[CHG-4c994c31ee86](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/4c994c31ee861cbc1b3d18da46108c402d8d7926)<br>2026-07-21T09:59:00+05:00 | refactor(auth): canonicalize methodologist role | BASE90 | `apps/api/app/modules/ai/router.py`; `apps/api/app/modules/documents/router.py` |
| <a id="chg-03b509e111ef"></a>[CHG-03b509e111ef](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/03b509e111efcd7388772bb8c025490d00937146)<br>2026-07-20T12:47:20+05:00 | fix(courses): enforce review publish and assignment boundary | BASE90 | `apps/api/app/modules/ai/pipeline.py` |
| <a id="chg-407725e1460b"></a>[CHG-407725e1460b](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/407725e1460be7f57c1b1d793ed04475e237e077)<br>2026-07-16T10:39:55+05:00 | feat(positions): complete job instruction course flow | BASE90 | `apps/api/app/modules/ai/pipeline.py`; `apps/api/app/modules/documents/router.py`; `apps/api/app/modules/documents/schemas.py` |
| <a id="chg-55a926f79a71"></a>[CHG-55a926f79a71](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/55a926f79a7109924382800722f78255b4661698)<br>2026-07-14T18:23:43+05:00 | fix(worker): preserve SQLAlchemy model metadata | BASE90 | `apps/api/app/core/celery_app.py` |
| <a id="chg-8df82e4cd61a"></a>[CHG-8df82e4cd61a](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/8df82e4cd61a38abfa27ad0f68eb75d3ba9ca489)<br>2026-07-14T13:40:24+05:00 | fix(infra): configure Celery Redis TLS verification | BASE90 | `apps/api/app/core/celery_app.py` |
| <a id="chg-ca835917d0b6"></a>[CHG-ca835917d0b6](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/ca835917d0b649ad0e32b52904067e1106aa9be3)<br>2026-07-14T12:38:13+05:00 | fix(api): enforce trial access and queue AI jobs | BASE90 | `apps/api/app/modules/ai/router.py`; `apps/api/app/modules/ai/tasks.py` |
| <a id="chg-3b9e61262f8c"></a>[CHG-3b9e61262f8c](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/3b9e61262f8c5842195c4cf63803aa739468f3cb)<br>2026-07-13T14:20:55+05:00 | feat(rbac): separate tenant administration from learning | BASE90 | `apps/api/app/modules/ai/router.py`; `apps/api/app/modules/documents/router.py` |
| <a id="chg-dc4291853e25"></a>[CHG-dc4291853e25](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/dc4291853e2591069272695186c780dfcae17818)<br>2026-07-04T10:05:40+05:00 | fix: fail over on wrong embedding dimensions | BASE90 | `apps/api/app/modules/ai/ingestion.py`; `apps/api/app/modules/ai/llm_client.py` |
| <a id="chg-a0d98134b8d6"></a>[CHG-a0d98134b8d6](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/a0d98134b8d6054632d5ca39ebe5bbb32b30267b)<br>2026-07-03T07:14:16+05:00 | fix: enforce trial usage limits | BASE90 | `apps/api/app/modules/ai/router.py` |
| <a id="chg-50360cb7b133"></a>[CHG-50360cb7b133](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/50360cb7b1331ebf3c43166a1d613ed8b33edf41)<br>2026-07-02T18:28:53+05:00 | fix: make document uploads visibly progress | BASE90 | `apps/api/app/modules/ai/llm_client.py` |
| <a id="chg-faecdf25e7f7"></a>[CHG-faecdf25e7f7](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/faecdf25e7f72b6230fd455f1bbe68290d4d3a03)<br>2026-07-02T18:04:32+05:00 | fix: skip docling for text document uploads | BASE90 | `apps/api/app/modules/ai/ingestion.py` |
| <a id="chg-2990f2f3c32b"></a>[CHG-2990f2f3c32b](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/2990f2f3c32b7d168b9c47e3261c4d4aac6c2f16)<br>2026-07-02T13:55:50+05:00 | fix: ignore empty ai quizzes in completion | BASE90 | `apps/api/app/modules/ai/pipeline.py` |
| <a id="chg-f660d1207d72"></a>[CHG-f660d1207d72](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/f660d1207d725da8a4dc99b07db676983ffb8e80)<br>2026-07-02T13:39:47+05:00 | fix: bound ai review stage latency | BASE90 | `apps/api/app/modules/ai/pipeline.py`; `apps/api/app/modules/ai/reviewer.py` |
| <a id="chg-2be42b49de80"></a>[CHG-2be42b49de80](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/2be42b49de807ab979e3b4e2da4e84601be73420)<br>2026-07-02T12:54:16+05:00 | fix: serialize ai job course id safely | BASE90 | `apps/api/app/modules/ai/router.py` |
| <a id="chg-e2c59f57e2db"></a>[CHG-e2c59f57e2db](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/e2c59f57e2db91dfba896e870fa3dc4901fecafb)<br>2026-07-02T12:41:09+05:00 | fix: persist generated course id on ai job | BASE90 | `apps/api/app/modules/ai/pipeline.py` |
| <a id="chg-ca5192eef5a3"></a>[CHG-ca5192eef5a3](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/ca5192eef5a334c6a16bac23538e1b57c500d093)<br>2026-07-02T12:25:49+05:00 | fix: read ai documents under tenant context | BASE90 | `apps/api/app/modules/ai/architect.py` |
| <a id="chg-ca53e9068f26"></a>[CHG-ca53e9068f26](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/ca53e9068f26b454934ae23d010b5e3d09dc0a8e)<br>2026-07-02T12:18:03+05:00 | fix: update ai jobs under tenant context | BASE90 | `apps/api/app/modules/ai/pipeline.py`; `apps/api/app/modules/ai/router.py` |
| <a id="chg-a61652fd9441"></a>[CHG-a61652fd9441](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/a61652fd9441ab4d822b09bdaf156a39a497730e)<br>2026-07-02T12:08:54+05:00 | fix: run ai generation as background task | BASE90 | `apps/api/app/modules/ai/router.py` |
| <a id="chg-4a3702f04c11"></a>[CHG-4a3702f04c11](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/4a3702f04c1181de238598f94bd1f2e5a1d6f351)<br>2026-07-02T11:55:23+05:00 | fix: preserve tenant context in ai ingestion | BASE90 | `apps/api/app/modules/ai/architect.py`; `apps/api/app/modules/ai/ingestion.py`; `apps/api/app/modules/ai/pipeline.py`; ещё 2 |
### Git 2026-06

| ID / дата | Изменение | Состояние исходников | Основные файлы |
|---|---|---|---|
| <a id="chg-bff2b5f07bfd"></a>[CHG-bff2b5f07bfd](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/bff2b5f07bfdad11f12d6e877f95d41e219558e1)<br>2026-06-29T19:08:02+05:00 | fix(api): switch Celery tasks to asyncio.run() + add worker_process_init engine reset | BASE90 | `apps/api/app/core/celery_app.py` |
| <a id="chg-9c0eeb3d94d9"></a>[CHG-9c0eeb3d94d9](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/9c0eeb3d94d98077d8f1c9020aa3b2efb7a0872a)<br>2026-06-29T18:14:15+05:00 | fix(api): use ssl.CERT_REQUIRED int instead of string | BASE90 | `apps/api/app/core/celery_app.py` |
| <a id="chg-b1d7232e181b"></a>[CHG-b1d7232e181b](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/b1d7232e181b405b47b90db49e810c717d89975f)<br>2026-06-29T18:12:59+05:00 | fix(api): explicit SSL options for rediss:// broker (Celery 5.6+ requires ssl_cert_reqs) | BASE90 | `apps/api/app/core/celery_app.py` |
| <a id="chg-1c21e914ec1c"></a>[CHG-1c21e914ec1c](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/1c21e914ec1c77df55390ee7444f2762ddbc11fc)<br>2026-06-29T17:03:54+05:00 | feat(api): B1b — wire recompute kernel into all rule-change triggers | BASE90 | `apps/api/app/core/celery_app.py` |
| <a id="chg-468220e55c7c"></a>[CHG-468220e55c7c](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/468220e55c7c627c7a3ac9b1de068302ed7fb70b)<br>2026-06-28T11:35:12+05:00 | feat(6.3): per-tenant LLM budget enforcement (default \/month) | BASE90 | `apps/api/app/modules/ai/budget.py`; `apps/api/app/modules/ai/router.py` |
| <a id="chg-327cd7023e8f"></a>[CHG-327cd7023e8f](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/327cd7023e8f3a142e3ee2ef6289081bd24176a8)<br>2026-06-28T11:21:34+05:00 | fix(4.6/4.7): file-upload size ADR + text-content heuristic | BASE90 | `apps/api/app/modules/documents/router.py` |
| <a id="chg-9481bf74aab3"></a>[CHG-9481bf74aab3](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/9481bf74aab3af62e4c47188730e470ab4adb804)<br>2026-06-28T11:12:48+05:00 | fix(2.4/6.4/6.5): replace silent except and PII print() with structured logger | BASE90 | `apps/api/app/modules/ai/assessment.py`; `apps/api/app/modules/documents/router.py` |
| <a id="chg-5069712c4331"></a>[CHG-5069712c4331](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/5069712c4331c426ca37fcd49eb8a391431d9695)<br>2026-06-28T10:56:28+05:00 | fix(3.2/3.3): restrict legacy email fallback and tenant-scope get_ai_job | BASE90 | `apps/api/app/modules/ai/job_service.py`; `apps/api/app/modules/ai/router.py` |
| <a id="chg-5a476b62cd67"></a>[CHG-5a476b62cd67](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/5a476b62cd677ecca8effbc96e7a51175e9c1fb6)<br>2026-06-28T09:19:09+05:00 | fix(deploy): move ml_prompts into apps/api/app/ for Render rootDir | BASE90 | `apps/api/app/modules/ai/architect.py`; `apps/api/app/modules/ai/assessment.py`; `apps/api/app/modules/ai/reviewer.py`; ещё 2 |
| <a id="chg-a0822aff5eab"></a>[CHG-a0822aff5eab](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/a0822aff5eab055c2de1e4ab173fd0b8c601922a)<br>2026-06-28T08:21:55+05:00 | feat(ai): Jinja2 prompt templates — extract inline f-string prompts to .md files | BASE90 | `apps/api/app/modules/ai/architect.py`; `apps/api/app/modules/ai/assessment.py`; `apps/api/app/modules/ai/reviewer.py`; ещё 2 |
| <a id="chg-8f3b1f3e0dc6"></a>[CHG-8f3b1f3e0dc6](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/8f3b1f3e0dc622dd25f3a51672a4507121246be9)<br>2026-06-26T15:53:30+05:00 | debug(ai): count rows on a FRESH session after commit | BASE90 | `apps/api/app/modules/ai/ingestion.py` |
| <a id="chg-74c79318d879"></a>[CHG-74c79318d879](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/74c79318d879928220c522247dc0efe28e9a695a)<br>2026-06-26T15:25:10+05:00 | fix(ai): explicit flush() before post-commit SELECT in add_chunks | BASE90 | `apps/api/app/modules/ai/ingestion.py` |
| <a id="chg-451ea9cfa616"></a>[CHG-451ea9cfa616](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/451ea9cfa61688c5525f26ce5d9991350ff74c6d)<br>2026-06-26T15:01:56+05:00 | debug(ai): verbose add_chunks logging to pinpoint where embeddings go | BASE90 | `apps/api/app/modules/ai/ingestion.py` |
| <a id="chg-01349f7123ec"></a>[CHG-01349f7123ec](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/01349f7123ec56a76a11c77c14842380ede4631b)<br>2026-06-26T14:54:00+05:00 | fix(ai): truthful embedding_status + loud logging in ingest pipeline | BASE90 | `apps/api/app/modules/ai/ingestion.py`; `apps/api/app/modules/documents/router.py` |
| <a id="chg-c7cd55d40953"></a>[CHG-c7cd55d40953](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/c7cd55d409537ce2aaaf5e940f9025a1e00e88a9)<br>2026-06-26T14:13:42+05:00 | fix(ai): POST embeddings to /embeddings not /chat/completions | BASE90 | `apps/api/app/modules/ai/llm_client.py` |
| <a id="chg-150f60c7ed32"></a>[CHG-150f60c7ed32](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/150f60c7ed32cc61cbe2a92bdd4e50761e7ba359)<br>2026-06-26T14:05:22+05:00 | fix(ai): rewrite hash_embedding to never emit NaN/inf | BASE90 | `apps/api/app/modules/ai/ingestion.py` |
| <a id="chg-7b1683814338"></a>[CHG-7b1683814338](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/7b1683814338c9de4a392ced8fa5c1c48aeae515)<br>2026-06-26T13:54:53+05:00 | fix(ai): skip malformed (NaN/inf) embeddings instead of failing the doc | BASE90 | `apps/api/app/modules/ai/ingestion.py` |
| <a id="chg-e3b2c6c17240"></a>[CHG-e3b2c6c17240](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/e3b2c6c17240d343067d80d3f707b0087976a177)<br>2026-06-26T09:59:18+05:00 | fix(tenant): block superadmin from tenant-only endpoints + UI | BASE90 | `apps/api/app/modules/ai/router.py`; `apps/api/app/modules/documents/router.py` |
| <a id="chg-cc0659ab1879"></a>[CHG-cc0659ab1879](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/cc0659ab18797026ef1b3cd6708428e461902031)<br>2026-06-26T07:54:43+05:00 | feat(demo): sandbox limits + prospect UI banner | BASE90 | `apps/api/app/modules/ai/router.py`; `apps/api/app/modules/documents/router.py` |
| <a id="chg-82c1d2d39a24"></a>[CHG-82c1d2d39a24](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/82c1d2d39a243750ea8e8886e66eefab096f2f96)<br>2026-06-26T07:25:04+05:00 | fix(ui): chat panel + ring-inset; docs schema fields; superadmin demo-login | BASE90 | `apps/api/app/modules/documents/schemas.py` |
| <a id="chg-f03a5d067110"></a>[CHG-f03a5d067110](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/f03a5d067110a3546d170b1533fed3c88082aa36)<br>2026-06-26T06:03:33+05:00 | feat(admin): superadmin UI + DB storage for AI provider API keys | BASE90 | `apps/api/app/modules/ai/llm_client.py`; `apps/api/app/modules/ai/pipeline.py`; `apps/api/app/modules/ai/router.py` |
| <a id="chg-b4262e8fbf78"></a>[CHG-b4262e8fbf78](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/b4262e8fbf78953c42468d1822cc65555ee56c81)<br>2026-06-26T05:38:11+05:00 | feat(ai): add DeepSeek + Voyage fallback chain for LLM and embeddings | BASE90 | `apps/api/app/modules/ai/ingestion.py`; `apps/api/app/modules/ai/llm_client.py` |
| <a id="chg-ef81aab571eb"></a>[CHG-ef81aab571eb](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/ef81aab571ebf82733c7c621b2f88507d9bd097f)<br>2026-06-26T04:59:41+05:00 | feat(ai): inline lesson edit, chat apply, document short summaries | BASE90 | `apps/api/app/modules/ai/router.py`; `apps/api/app/modules/ai/schemas.py`; `apps/api/app/modules/documents/router.py` |
| <a id="chg-c44ac505cc8c"></a>[CHG-c44ac505cc8c](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/c44ac505cc8c49c76c9da782570c8cece99e1929)<br>2026-06-26T04:48:26+05:00 | feat(ai): methodologist chat assistant + per-module/lesson regeneration | BASE90 | `apps/api/app/modules/ai/router.py`; `apps/api/app/modules/ai/schemas.py` |
| <a id="chg-5f8b0f752004"></a>[CHG-5f8b0f752004](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/5f8b0f75200429e9963a482ace7d5513797ff329)<br>2026-06-25T09:52:53+05:00 | fix: use CAST(:emb AS vector) instead of :emb::vector in pgvector query | BASE90 | `apps/api/app/modules/ai/ingestion.py` |
| <a id="chg-e68159cc680c"></a>[CHG-e68159cc680c](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/e68159cc680c856c73c168555017ab9ade6d329b)<br>2026-06-25T04:14:11+05:00 | fix: tenant isolation in architect + embedding status + www.kml.kz CORS | BASE90 | `apps/api/app/modules/ai/architect.py`; `apps/api/app/modules/ai/pipeline.py`; `apps/api/app/modules/documents/router.py`; ещё 1 |
| <a id="chg-72a28ba860c6"></a>[CHG-72a28ba860c6](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/72a28ba860c6d5c0b6396ac2027f73653a20d711)<br>2026-06-24T14:45:50+05:00 | feat: Docling as remote service on VPS | BASE90 | `apps/api/app/modules/ai/converter_remote.py`; `apps/api/app/modules/ai/ingestion.py` |
| <a id="chg-4d09d933e2be"></a>[CHG-4d09d933e2be](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/4d09d933e2be52a78edfb8f721815b237f1abd43)<br>2026-06-24T13:49:30+05:00 | security: complete all 10 audit blockers | BASE90 | `apps/api/app/modules/ai/ingestion.py`; `apps/api/app/modules/ai/tasks.py` |
| <a id="chg-a1ea9c92f336"></a>[CHG-a1ea9c92f336](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/a1ea9c92f33694a8bd8e4589ae7dbc110e8ff24e)<br>2026-06-24T13:17:49+05:00 | security: fix critical audit findings | BASE90 | `apps/api/app/modules/ai/ingestion.py` |
| <a id="chg-01304a2fe341"></a>[CHG-01304a2fe341](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/01304a2fe341432a40568ba9925257c33c7dfb71)<br>2026-06-24T12:20:27+05:00 | fix: LLM client retry on 502/503/504 + 600s timeout | BASE90 | `apps/api/app/modules/ai/llm_client.py` |
| <a id="chg-58bca59520a1"></a>[CHG-58bca59520a1](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/58bca59520a1b94d760b76a6610ec31140fa7785)<br>2026-06-24T09:40:45+05:00 | fix: architect pre-check — better error when doc IDs don't match embeddings, verify all docs exist before starting | BASE90 | `apps/api/app/modules/ai/architect.py` |
| <a id="chg-4b651ccadada"></a>[CHG-4b651ccadada](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/4b651ccadada5eb9d6964369293dbfec2605665d)<br>2026-06-24T09:29:55+05:00 | fix: architect MUST use documents — real embeddings in search, scope filtering, pre-check, stricter prompt | BASE90 | `apps/api/app/modules/ai/architect.py` |
| <a id="chg-50c6c9ceeae8"></a>[CHG-50c6c9ceeae8](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/50c6c9ceeae849768015926d40c5bd878b918d13)<br>2026-06-24T08:54:59+05:00 | fix: writer generates content from LLM when vector search fails (no more 'No relevant content found') | BASE90 | `apps/api/app/modules/ai/ingestion.py`; `apps/api/app/modules/ai/writer.py`; `apps/api/app/modules/documents/router.py` |
| <a id="chg-b69fe34e0290"></a>[CHG-b69fe34e0290](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/b69fe34e02907a5d9603ca16f5bd021983c49ec4)<br>2026-06-24T08:35:20+05:00 | fix: architect tool parsing — fix regex for nested JSON, make tools async, remove dead code | BASE90 | `apps/api/app/modules/ai/architect.py` |
| <a id="chg-28ef703ae804"></a>[CHG-28ef703ae804](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/28ef703ae804474a89ae2f31534a67900f4e5022)<br>2026-06-24T08:19:39+05:00 | feat: cancel generation — asyncio task cancel + frontend button + pipeline checks | BASE90 | `apps/api/app/modules/ai/pipeline.py`; `apps/api/app/modules/ai/router.py`; `apps/api/app/modules/ai/writer.py` |
| <a id="chg-69c8c4d38c79"></a>[CHG-69c8c4d38c79](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/69c8c4d38c793ad1b5ee9b51ef90a27120d0a30a)<br>2026-06-24T08:03:01+05:00 | fix: architect tools read from DB instead of ephemeral disk (list_documents, get_document_summary, get_document_toc, get_chapter_text) | BASE90 | `apps/api/app/modules/ai/architect.py` |
| <a id="chg-9ee6a006c981"></a>[CHG-9ee6a006c981](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/9ee6a006c981db0d471340bd5d0ef0d2b51c6d78)<br>2026-06-24T06:42:01+05:00 | fix: progress 500 (add course_id), pipeline messages in Russian, step indicator auto-advance to result | BASE90 | `apps/api/app/modules/ai/pipeline.py` |
| <a id="chg-cd7b33ee3f39"></a>[CHG-cd7b33ee3f39](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/cd7b33ee3f39ed42ce3323e9acd35a6d3f8b6078)<br>2026-06-23T21:57:08+05:00 | fix: ingest documents at upload time into pgvector (Render ephemeral disk fix) | BASE90 | `apps/api/app/modules/ai/pipeline.py`; `apps/api/app/modules/documents/router.py` |
| <a id="chg-6e0f8743be11"></a>[CHG-6e0f8743be11](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/6e0f8743be11deb4368340935e02dc81b492b915)<br>2026-06-23T21:41:53+05:00 | fix: add GET /lessons/{id} endpoint, auto-enroll creator after generation, skip enrollment for admins | BASE90 | `apps/api/app/modules/ai/pipeline.py` |
| <a id="chg-afb779ccc017"></a>[CHG-afb779ccc017](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/afb779ccc017b0dcf5ab36a10f6524ca31023f6f)<br>2026-06-23T21:09:13+05:00 | fix: document upload saves to disk, pipeline actually ingests docs, edit page has content editor, back button goes to courses | BASE90 | `apps/api/app/modules/ai/pipeline.py`; `apps/api/app/modules/documents/router.py` |
| <a id="chg-806a312afa58"></a>[CHG-806a312afa58](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/806a312afa5806e2682421d66eadf6b12b603a8d)<br>2026-06-23T20:18:50+05:00 | fix: use json_repair library as fallback for LLM JSON parsing in architect + assessment | BASE90 | `apps/api/app/modules/ai/architect.py`; `apps/api/app/modules/ai/assessment.py` |
| <a id="chg-a2e9f1c8d4a6"></a>[CHG-a2e9f1c8d4a6](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/a2e9f1c8d4a6344ce9585a5359421e3f9be9d4c2)<br>2026-06-23T20:05:42+05:00 | feat: add course delete button + fix pipeline stage on completion | BASE90 | `apps/api/app/modules/ai/pipeline.py` |
| <a id="chg-62456f5d67fd"></a>[CHG-62456f5d67fd](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/62456f5d67fd24804b87f4b3b25e26596c0a7dd2)<br>2026-06-23T19:49:19+05:00 | fix: add missing comma repair for string values in JSON parsers | BASE90 | `apps/api/app/modules/ai/architect.py`; `apps/api/app/modules/ai/assessment.py` |
| <a id="chg-26527a2d7839"></a>[CHG-26527a2d7839](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/26527a2d783962abd182f52be141c44eaa7151d1)<br>2026-06-23T19:41:25+05:00 | fix: LLM self-correction for broken assessment JSON | BASE90 | `apps/api/app/modules/ai/assessment.py` |
| <a id="chg-00cef9f86d8a"></a>[CHG-00cef9f86d8a](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/00cef9f86d8aef5f34c5eed20664f38f05d9f202)<br>2026-06-23T19:31:12+05:00 | fix: aggressive JSON repair for malformed LLM output | BASE90 | `apps/api/app/modules/ai/assessment.py` |
| <a id="chg-b8c064d52e87"></a>[CHG-b8c064d52e87](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/b8c064d52e87f3207e349a01186983080fca764e)<br>2026-06-23T19:22:28+05:00 | fix: embed embedding vector as string literal in SQL to avoid :: parsing | BASE90 | `apps/api/app/modules/ai/ingestion.py` |
| <a id="chg-90016f95902a"></a>[CHG-90016f95902a](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/90016f95902af0e50da2fa041ca7612ac2bc5532)<br>2026-06-23T19:22:01+05:00 | fix: remove ::vector cast from pgvector query, let PostgreSQL infer type | BASE90 | `apps/api/app/modules/ai/ingestion.py` |
| <a id="chg-ef694cfb2c51"></a>[CHG-ef694cfb2c51](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/ef694cfb2c51a9ae16dc7bbb8024d2d694cbcef1)<br>2026-06-23T19:15:20+05:00 | fix: single embedding param in pgvector query, use distance alias | BASE90 | `apps/api/app/modules/ai/ingestion.py` |
| <a id="chg-7ddddc969872"></a>[CHG-7ddddc969872](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/7ddddc969872fb47da46cb4c8bb56e8ef44b8e9b)<br>2026-06-23T19:14:18+05:00 | fix: use separate param names for embedding in pgvector query | BASE90 | `apps/api/app/modules/ai/ingestion.py` |
| <a id="chg-406fb013f901"></a>[CHG-406fb013f901](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/406fb013f90148016f94a0afd7d120b5203721c0)<br>2026-06-23T19:01:00+05:00 | fix: make VectorStore methods async, fix embedding dimension 4096 | BASE90 | `apps/api/app/modules/ai/architect.py`; `apps/api/app/modules/ai/ingestion.py`; `apps/api/app/modules/ai/writer.py` |
| <a id="chg-8dd934acd27c"></a>[CHG-8dd934acd27c](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/8dd934acd27c7165c9fc3a43913c4907de7d9c29)<br>2026-06-23T18:47:07+05:00 | fix: retry architect JSON parse with LLM self-correction | BASE90 | `apps/api/app/modules/ai/architect.py` |
| <a id="chg-6e120770691b"></a>[CHG-6e120770691b](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/6e120770691b9686567d4d1657fd36221d53993a)<br>2026-06-23T18:45:46+05:00 | fix: robust JSON parsing for architect course structure | BASE90 | `apps/api/app/modules/ai/architect.py` |
| <a id="chg-bb0d179288ab"></a>[CHG-bb0d179288ab](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/bb0d179288abba33b42941dea68df40473e3f845)<br>2026-06-23T18:38:27+05:00 | feat: replace ChromaDB with Supabase pgvector for embeddings | BASE90 | `apps/api/app/modules/ai/ingestion.py` |
| <a id="chg-057394b5aa58"></a>[CHG-057394b5aa58](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/057394b5aa5814d187b695dbcf959e4261237fea)<br>2026-06-23T18:34:57+05:00 | fix: better JSON parse error logging + retry with cleanup | BASE90 | `apps/api/app/modules/ai/assessment.py` |
| <a id="chg-5bd0d5992603"></a>[CHG-5bd0d5992603](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/5bd0d5992603ad784869e19f74f42cc750b6f480)<br>2026-06-23T18:34:08+05:00 | fix: await async on_progress callbacks in writer and assessment | BASE90 | `apps/api/app/modules/ai/assessment.py`; `apps/api/app/modules/ai/writer.py` |
| <a id="chg-d9a0c949f728"></a>[CHG-d9a0c949f728](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/d9a0c949f728c57360e20f449f426c3ab932f52d)<br>2026-06-23T18:30:37+05:00 | cleanup: remove Groq references, set default model to Qwen | BASE90 | `apps/api/app/modules/ai/llm_client.py` |
| <a id="chg-57b9ed0945c7"></a>[CHG-57b9ed0945c7](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/57b9ed0945c79551af1f990d6638511ad590d8bc)<br>2026-06-23T17:58:31+05:00 | fix: strip thinking tags + debug logging in JSON parser | BASE90 | `apps/api/app/modules/ai/assessment.py` |
| <a id="chg-8cce18237f1c"></a>[CHG-8cce18237f1c](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/8cce18237f1c35382f252fd57f34fd87f4a7f1fc)<br>2026-06-23T17:46:27+05:00 | fix: switch back to Qwen with enable_thinking=false, revert Groq workarounds | BASE90 | `apps/api/app/modules/ai/architect.py`; `apps/api/app/modules/ai/llm_client.py` |
| <a id="chg-0599bcc71ae5"></a>[CHG-0599bcc71ae5](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/0599bcc71ae5dac0aedca3b9bb5dd25a17460cb1)<br>2026-06-23T17:19:52+05:00 | fix: increase retry backoff to 30s steps, 5 retries for Groq TPM | BASE90 | `apps/api/app/modules/ai/llm_client.py` |
| <a id="chg-eb4f45202ceb"></a>[CHG-eb4f45202ceb](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/eb4f45202ceb7412e5df03eeeb6d9b07bc93cba0)<br>2026-06-23T17:13:49+05:00 | fix: back to llama-3.3-70b + drastically shorten architect prompt to fit 12K TPM | BASE90 | `apps/api/app/modules/ai/architect.py` |
| <a id="chg-f6249b054186"></a>[CHG-f6249b054186](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/f6249b054186b2eb7c815d74b226ebe0c1d6d6cd)<br>2026-06-23T17:08:35+05:00 | fix: limit architect messages to last 8 for Groq payload limit | BASE90 | `apps/api/app/modules/ai/architect.py` |
| <a id="chg-ff4d73998644"></a>[CHG-ff4d73998644](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/ff4d73998644363a80418d9e5a4c904f4a5df0b4)<br>2026-06-23T17:03:57+05:00 | fix: reduce payload size for Groq free tier (truncate tool results, fewer chapters) | BASE90 | `apps/api/app/modules/ai/architect.py` |
| <a id="chg-7736b19a591c"></a>[CHG-7736b19a591c](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/7736b19a591c2eb2a8294d4d848ca006fb6f1bbb)<br>2026-06-23T16:58:57+05:00 | fix: switch to llama-3.1-8b-instant + 5s delay between assessments | BASE90 | `apps/api/app/modules/ai/assessment.py` |
| <a id="chg-5f4c09512b59"></a>[CHG-5f4c09512b59](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/5f4c09512b59cf5f74aefbcfd936141e7f0a81b2)<br>2026-06-23T16:49:41+05:00 | fix: find largest JSON block in LLM response + debug logging | BASE90 | `apps/api/app/modules/ai/assessment.py` |
| <a id="chg-79b4ee48776f"></a>[CHG-79b4ee48776f](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/79b4ee48776f6fddf57d70f9e1d3326c05ddaf62)<br>2026-06-23T16:44:37+05:00 | fix: robust JSON parser for Groq markdown-wrapped responses | BASE90 | `apps/api/app/modules/ai/assessment.py` |
| <a id="chg-a56cfc0d1273"></a>[CHG-a56cfc0d1273](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/a56cfc0d12732aab188801a68e59ec28a1d33304)<br>2026-06-23T16:39:20+05:00 | fix: add description field to architect Module dataclass | BASE90 | `apps/api/app/modules/ai/architect_schema.py` |
| <a id="chg-229868df6a72"></a>[CHG-229868df6a72](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/229868df6a7261e6e2cfcdaf8e79435f121052f5)<br>2026-06-23T16:33:40+05:00 | fix: generate UUID for Course when course_id is None | BASE90 | `apps/api/app/modules/ai/pipeline.py` |
| <a id="chg-94f411f33b86"></a>[CHG-94f411f33b86](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/94f411f33b86784ae58a8196ae353b10882f41ef)<br>2026-06-23T16:25:58+05:00 | fix: add retry with backoff on 429 rate limit for Groq free tier | BASE90 | `apps/api/app/modules/ai/llm_client.py` |
| <a id="chg-a7a3e5ff6ca9"></a>[CHG-a7a3e5ff6ca9](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/a7a3e5ff6ca9b862b8ae42df181017276dd0d7c5)<br>2026-06-23T16:21:58+05:00 | fix: remove Qwen-specific chat_template_kwargs for Groq compatibility | BASE90 | `apps/api/app/modules/ai/llm_client.py` |
| <a id="chg-bf5ef876b819"></a>[CHG-bf5ef876b819](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/bf5ef876b819459db919424335c105bbac331194)<br>2026-06-23T16:18:39+05:00 | switch LLM from Qwen to Groq (llama-3.3-70b), keep Qwen embeddings | BASE90 | `apps/api/app/modules/ai/llm_client.py` |
| <a id="chg-455bd68dd4fc"></a>[CHG-455bd68dd4fc](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/455bd68dd4fcec3e83caa0b2d2ba31cffa44c8da)<br>2026-06-23T15:41:22+05:00 | fix: increase assessment retries to 4, better JSON parsing | BASE90 | `apps/api/app/modules/ai/assessment.py` |
| <a id="chg-9a44b57f2bf1"></a>[CHG-9a44b57f2bf1](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/9a44b57f2bf1971011a556ba0eed4bbf24a6bb62)<br>2026-06-23T09:13:23+05:00 | fix: ai_generated boolean type in course save | BASE90 | `apps/api/app/modules/ai/pipeline.py` |
| <a id="chg-5535b0f25036"></a>[CHG-5535b0f25036](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/5535b0f25036fb0fd8668f21e516a2fc34a4909f)<br>2026-06-23T09:03:35+05:00 | fix: merge system prompts to fix Qwen400 - system message must be first | BASE90 | `apps/api/app/modules/ai/architect.py` |
| <a id="chg-adb11ab452ed"></a>[CHG-adb11ab452ed](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/adb11ab452ed3be17f4c80dd0918c9f6d1c2efae)<br>2026-06-23T09:00:02+05:00 | debug: add print logging for LLM errors | BASE90 | `apps/api/app/modules/ai/llm_client.py` |
| <a id="chg-28286cb4d839"></a>[CHG-28286cb4d839](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/28286cb4d839f5dfcc463bf4483849d660d7ee5e)<br>2026-06-23T08:47:36+05:00 | fix: disable Qwen3 thinking mode, fallback to reasoning field | BASE90 | `apps/api/app/modules/ai/llm_client.py` |
| <a id="chg-0fc5fd195c8f"></a>[CHG-0fc5fd195c8f](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/0fc5fd195c8fa1f63156c52348de273b4d56c129)<br>2026-06-23T08:40:45+05:00 | fix: Cloudflare tunnel Qwen URLs, correct model names, asyncio pipeline | BASE90 | `apps/api/app/modules/ai/ingestion.py`; `apps/api/app/modules/ai/llm_client.py` |
| <a id="chg-44ce7ce30f4e"></a>[CHG-44ce7ce30f4e](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/44ce7ce30f4e5a989d0ea314c5dfbfdc6e3c050b)<br>2026-06-23T07:18:10+05:00 | fix: run AI pipeline directly via asyncio instead of Celery | BASE90 | `apps/api/app/modules/ai/router.py` |
| <a id="chg-172776319d27"></a>[CHG-172776319d27](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/172776319d27f9237e95efe9105db58728b4bba9)<br>2026-06-22T17:37:40+05:00 | feat: replace hardcoded Qwen URLs with VPS proxy via config | BASE90 | `apps/api/app/modules/ai/ingestion.py`; `apps/api/app/modules/ai/llm_client.py`; `apps/api/app/modules/ai/pipeline.py` |
| <a id="chg-6c54a137dfab"></a>[CHG-6c54a137dfab](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/6c54a137dfabcfb209190d8d72dcb264f2968ccc)<br>2026-06-22T13:59:24+05:00 | Phase 3-5: security fixes, UI improvements, audit logs | BASE90 | `apps/api/app/modules/ai/ingestion.py`; `apps/api/app/modules/ai/pipeline.py`; `apps/api/app/modules/ai/reviewer.py`; ещё 2 |
| <a id="chg-aa04aad9b10d"></a>[CHG-aa04aad9b10d](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/aa04aad9b10d6f05a9ada215e8a109d2ceb7ac61)<br>2026-06-22T12:30:21+05:00 | fix: Phase 1+2 security — auth sessions Redis, rate limiting, WS auth, MIME check, CORS, blacklist, password | BASE90 | `apps/api/app/modules/ai/router.py`; `apps/api/app/modules/documents/router.py` |
| <a id="chg-437ed03c86d6"></a>[CHG-437ed03c86d6](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/437ed03c86d68d3a1eb4c343dce684db884ddd08)<br>2026-06-22T10:40:55+05:00 | fix: AIJob import path in ai router (was app.modules.ai.models -&gt; app.models.ai_job) | BASE90 | `apps/api/app/modules/ai/router.py` |
| <a id="chg-fc907387726c"></a>[CHG-fc907387726c](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/fc907387726c98947f7949068382d1d1e540c48a)<br>2026-06-22T10:10:37+05:00 | fix: celery import graceful + duplicate document check | BASE90 | `apps/api/app/modules/ai/tasks.py`; `apps/api/app/modules/documents/router.py` |
| <a id="chg-98c8e0ddf307"></a>[CHG-98c8e0ddf307](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/98c8e0ddf30748324595fd966397c43937ab1ac6)<br>2026-06-22T10:00:36+05:00 | fix: graceful fallback when Celery/Redis unavailable | BASE90 | `apps/api/app/modules/ai/router.py` |
| <a id="chg-6ce88db398ea"></a>[CHG-6ce88db398ea](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/6ce88db398ea1069da14165fb2e34d98305e5593)<br>2026-06-22T09:18:56+05:00 | feat: add GET /ai/jobs list endpoint | BASE90 | `apps/api/app/modules/ai/router.py` |
| <a id="chg-ccc2a5bc0b2c"></a>[CHG-ccc2a5bc0b2c](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/ccc2a5bc0b2cda697081de2311291aacf6a73f66)<br>2026-06-22T08:54:31+05:00 | feat: merge positions+JD, redesign documents+AI generation pages, fix sidebar nav | BASE90 | `apps/api/app/modules/documents/router.py`; `apps/api/app/modules/documents/schemas.py` |
| <a id="chg-71e8bac10515"></a>[CHG-71e8bac10515](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/71e8bac10515e52e2ee44757956cc5b84572d22a)<br>2026-06-22T08:08:34+05:00 | feat: Quiz system, enrollment UI, content blocks CRUD, course structure editor | BASE90 | `apps/api/app/modules/ai/job_service.py`; `apps/api/app/modules/ai/pipeline.py`; `apps/api/app/modules/ai/router.py`; ещё 1 |
| <a id="chg-c006390b6d67"></a>[CHG-c006390b6d67](https://github.com/KamillaLMSCRM/Kamilya-NEW/commit/c006390b6d67d452b7398fa6507676619584b8dc)<br>2026-06-21T10:40:09+05:00 | Initial commit: Kamilya LMS Core v1.0 | BASE90 | `apps/api/app/core/celery_app.py`; `apps/api/app/models/ai_job.py`; `apps/api/app/modules/ai/__init__.py`; ещё 17 |
<!-- ENGINE_HISTORY_GENERATED_END -->

## Графовая сверка и ограничения

<!-- ENGINE_HISTORY_GRAPH_START -->
Завершена 11.11.2026 в текущем worktree. Использованы **CodeGraph1.6.2** и
**Graphify0.9.105**, без новой установки, watchers, внешних модельных запросов,
изменений provider/DEV/production. Read-only readiness после обновления — **READY**.

| Проверка | Фактический результат | Ограничение |
|---|---|---|
| CodeGraph `search` + bounded `callers` | Найдены `generate_simple_course` и caller `generate_v3_course_from_corpus`; найден V2 caller в simple service | Статические edges; выбранная policy подтверждена чтением `if` в исходниках |
| Graphify основной AST, directed path | `generate_v3_course_from_corpus → generate_simple_course → run_simple_course_editor_v2`,2hops EXTRACTED | Это локальный92sourcepath; не доказательство его выпуска в DEV91 |
| Основной AST source/exclusion audit | CodeGraph2525files; Graphify34781nodes/116353edges/2563sourcefiles, exclusions PASS,0input/0output LLMtokens | Число nodes не показатель качества курса или полноты динамических связей |
| Отдельная карта истории в Graphify | 1139nodes/3180edges: Gitcommit → изменённый файл; проверенная тема → прежние попытки/локальные92варианты | Карта собрана детерминированно из Git и проверенных человеком ссылок; это **не независимое LLM-извлечение смысла Markdown** |
| Graphify bounded query/path по истории | `concept:coverage → local:L92B` показывает повтор той же цели в новом локальном варианте; links к19.10/20.10/04.11/09.11/11.11 | Ребро «повтор» внесено после сверки исходников и отчётов, а не выдумано AST-инструментом |
| Graphify `diagnose multigraph` карты истории |0missing/danglingendpoints,0exactduplicates,0collapsededges;1139/3180сохранены | Отсутствие структурных ошибок графа не означает отсутствие ошибки в модели |
| Независимая проверка журнала |557уникальныхSHAs/anchors;546BASE90/2DEV91_SOURCE/9OTHER_REF; архивный plan hash и R14 figures совпадают | Все557diffs не проходили повторный смысловой аудит; metadata-only строки честно отмечены |

При построении основного AST потрачено147.873s на Graphify и1.754s на CodeGraph.
Первый широкий поиск Graphify вернул2039кандидатов и был усечён; он не использован
как доказательство зависимости. Затем заданы точные IDs/seed и directed path.
Часть полного ответа CLI может превышать заданный budget из-за отображения всех
рёбер найденного набора; бюджет вывода не считается доказательством экономии.

Markdown сам по себе CodeGraph не анализирует: в нём сознательно исключён `docs`.
Поэтому через CodeGraph проверены **ссылки журнала на текущий код**, а через
Graphify — основной кодовый путь **и отдельная карта истории**. Исключения не
ослаблялись, архивные документы не загружались в облако и не отправлялись ASUS.
Так не подменяется реальная сверка текста ложным утверждением «граф всё проверил».

Воспроизводимые локальные receipts:
`.release-evidence/engine-change-history-full-20261111/git-inventory.json`,
`graph-check-summary.json`, восемь отдельных `codegraph-*.json`/`graphify-*.json`/
`navigation-readiness.json`; source-index receipt
`.release-evidence/navigation/receipt.json`.
Карта истории: `graphify-out/engine-history/graph.json`.
Подготовка inventory/карты и восемь финальных запросов: **0modelcalls**.

**Практический вывод:** повтор не объясняется одним «плохим промптом». Доказаны
смены маршрута, обход прежних проверок, различие local/native и повторные ошибки
модельного сравнения. Следующая попытка обязана сослаться на записи выше и показать,
какое конкретное свойство старой реализации она сохраняет либо сознательно заменяет.
Это ограничение процесса, а не обещание безошибочности модели. Непринятый L92B
нельзя выпускать или объявлять успехом на основании зелёных structural tests.
<!-- ENGINE_HISTORY_GRAPH_END -->


### Final frozen LOCAL93 checks — 11.11

Full API8060PASS/1skip7warnings86.57s; required critical journey29selectors→79PASS8.89s (database gate deferred to approvedDEV). Baseline1004/2174PASS; diffcheckPASS. CodeGraph2538files/Graphify34942nodes117404edges2576sourcefiles/exclusionPASS,read-onlyREADY sourceb09bf586e4ec6b5ade45105e334835ba4330ed46f6327539e7cb4d4af41ab0b2. Typed-origin actual owned seam covered by existing parametrized mainselector. No new model calls. NativeDEV/prod not accepted.


### Native93 acceptance started — 11.11

Exact87f5e500/CI43049241570/build43050113170/image85b42e65;soleworker15cc;APIdep-dbq8to59fdbs73dnpdr0/webdpl_FSH9F4SysTc6jLe7q4GvTfNZE4Co RELEASE_OK. Before inference,H10/native-dev93-standards/submit-intent.json bindsrun native93-standards/source8febe470/engine93/Luna6HIGH. Job3f2745cc-bde2-420c-b84e-375f9fbcc6f6 PENDING/RUNNING, course/actualusage/semanticQA notavailableyet. Freshfullnative generation, notretainedlocaledit. Source/customerwrites0. DEVcapacityfailure correctedunderexactowner-approved8recoverablecachecleanup,all94containers/state unchanged,free8.92GiB/disk81%;no threshold waiver. Ownerauthorized separateDeepSeek93max$1/spent0, afterthreeLunaGO. Production90 unchanged.


### CHG-L94A — ПРОЕКТ перед кодом: редакторские дельты вместо полного замещения урока, 11.11

Предыдущие CHG-L92C/F (domain-scopedmerge), CHG-L93D-I (3stages/sourceunits/typedprovenance) сверены. Freshnative93-standards job3f2745cc/course3eb70efc NO_GO: автор L1 содержит лимиты/города/суммирование, редактор возвращает только новое вступление, полный snapshot замещает весь L1. Все11keys остаютсякорректными, но учебныйтекст теряется. RestrictedREADONLYlms_app:0separatecontentblocks,3realstagecheckpoints; неAPIprojection или hypotheticwrongkey. Evidence H10/native-dev93-standards/{private-stage-block-readback.json,stage-block-readback-receipt.json,independent-quality-review.md}.3calls51800IN10466OUT/343.515s/actualgpt-6-lunaHIGH; ценаUNKNOWN.

Причинаконтракта: V2scopedmerge сохраняет соседние domains, но targetlesson.content всёещё полный snapshot. V3проверяет IDs/ownedrefs/media, а несемантическуюэквивалентность полного переписанного текста. Нельзя автоматически чинить это числовой/городскойрегуляркой или новымсудьёй. Предлагается таже3стадийнаясхема, но обычныйредактор выдаёт адресные exactbefore→after дельты; неизменённыефрагменты сохраняеткод. Source/drafthash/ID/anchorunique/nonoverlap/media ограниченияструктурные, несемантическийвердикт. Редактор по-прежнему сам сверяетисходник и пишетисправления/нужныедобавления.

Сохраняются sourceunitplan/parenttable/confirmedrefclosure/typedorigins/actualusedrefs/pendingjournal/custreplay/sourcequestions/humanapproval. СтарыеV1/V2/V3jobs сохраняютвыбранныйполныйsnapshotпуть. НовыйV4policy/groupконтракт необходимдоDEVчтобысменаформатанеподменяластарыеownedstages. Доинтеграции: savedauthorstandards nohintsonlyoneLunaeditor; pureactualproducer/prepare/transport/anchor/partial-overwrite/media regressions. Затемfresh3fullDEV+DeepSeek$1+protectedprod/live. Не повторять неудачныйдополнительныйcriticH илиwhole-courseгенерациюдлядиагностики. ТекущийPDF93job196cd5d2ужеrunning, его завершаем/сохраняем, cash93неподан. Измененийкода94ещёнет.


### CHG-L94B — ПЛАН до кода: независимое редактирование учебного текста и карточек

CHG-L92C/D/F и CHG-L94A сверены. Saved-delta94/d:1freshLuna6HIGH20608IN1574OUT32.64s, всеgoodгородскиеlimits/aggregation/11cardsсохранены, исправленобщийзапретпролонгации. НоindependentNO_GO: авторскаяфраза привязываетвыборлимита кнаселённомупунктуприёмногопунктавместоегоРД. Новыйдельтаредактореёнеобнаружил. Этоотдельныйсмысловойдефект, неотменаисправленияpartialoverwrite. H11/saved-delta94/d/independent-quality-review.md;94ещёLOCAL/неразвёрнут.

Фактически новыйeditorinput опятьсмешиваеттекстыуроков скарточками/ключами/объяснениями. ПрежнееL92разделениепрозынеперенесеновновыйвызов: инструкции 'readbodyfirst' неравны отсутствиюответоввконтексте. НельзявыдатьдобавлениеметкивтомжеJSON занезависимость. Выбраны4осмысленныестадии:sourceplan→author→teaching-onlyaddressededitor→cardaddressededitor. Оба последнихвносятправки, ненеобязательныесудьи. Первыйневидитсуществующихкарточек/ключей/explanations; второйполучаетизменённыйкурс, нонеимеетправапереписыватьbody/title/addlessons. Удалятьсодержательныеsourcequestionsпервогоредактора вторымнельзя, серверunion. Bodyprovenance сохраняетсяприкарточнойправке.

СохраняютсявсеCHG94Aexactanchordelta/source/draft/ID/media/ownership/journalкритерии. V1/V2/V3историческиеразвернутыепути иLOCALV4single-editorprotoнеперетолковываются: новыйV5policy/groupidentities,94версияещёнекоммичена. Ни семантическихregex, нифиатногомодельноголимита, ниповтораwholecourseдлядиагностики. Одинsame-native93author/source/planлокальныйконтроль→двеeditorcallsсновымивходами, безизвестныхerrorhints;actualproducer/prepare+4ownedstages/replay/rolefencesдоinference. ПослеGO3freshDEV94/DeepSeekapproved$1/prod/live.


### 11.11 CHG-L94B фактический LOCAL результат

H11/separated94/d: sourcepacket9e/currentapprovedworking8f, exactsame native93author/automaticplan (retained,nocheckpointcache).2freshgpt-6-lunaHIGH:teaching18101IN1210OUT26.532s;cards20362IN441OUT11.0s. Firstbodyrolewithoutoldcards independentlychangedonlyL1openingtoregionaldirectorate lookup; cardsnoedits. Independentall3bodies/11cardsLOCALGO;alllimits/cities/aggregation/questions/peerbodiespreserved. CHG94A singlecombineddelta control20608IN1574OUT32.64s remainsNO_GO onmissedauthoredscopeerror, notrelabeled. Freshnative94/production stillOPEN. Full8088PASS/1skip7warnings76.67s; critical96PASS8.13s; baseline1004/2174PASS; graph2542files/34981nodes117630edges refreshdone. ExistingV3/V4ownedreplays23PASS;V5actualfakeseam6PASS. Metadata/usage/hashreceiptsinH11, managedUSD/providerbuildUNKNOWN. No paidDeepSeekcall.
