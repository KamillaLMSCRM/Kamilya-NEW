# Журнал ошибок движка генерации и обработки курсов

Владелец ответственности: движок Камили. Создан 05.11.2026 по прямому указанию
владельца. `ERRORS.md` предназначен для ошибок работы агента и их профилактики.
Новые дефекты продукта записываются здесь. Ранние записи в `ERRORS.md` остаются
историческими свидетельствами; этот журнал не объявляет их повторную проверку.

Цель — воспроизводить и устранять причины на сохранённых входах/ответах, а не
перезапускать генерацию ради каждого замечания. Полный пригодный черновик должен
сохраняться; смысловые сомнения видны редактору. Ошибка контракта, потеря данных,
чужой источник и неизвестный исход запроса требуют отдельной обработки.

Статусы: **OPEN** — причина не устранена; **LOCAL FIXED** — проверено локально;
**RUN VERIFIED** — проверено на сохранённом/новом реальном ответе модели;
**DEV VERIFIED** и **PROD VERIFIED** — только при доказанном штатном полном пути.
Зелёный технический тест не доказывает смыслового качества курса.

## ENG-001 — смешение автоматической проверки и одобрения человеком

- Обнаружение: внешний аудит P30, 05.11.2026, ревизия e9c9571d.
- Симптом/причина: общий verified мог соседствовать с непроверенной custody;
  состояния черновика, самопроверки и решения методиста не были явно разделены.
- Исправление: e1b5b945, отдельный версионированный реестр и состояния; готовый
  черновик сохраняется, решение человека связано с редакцией, публикация отдельная.
- Проверка: полный API7832PASS, web1606PASS, два синтетических браузерных сценария.
- Статус: LOCAL FIXED. Настоящий native/DEV/production цикл ещё не принят.

## ENG-002 — замечания и дополнительные связи не доходили единым контрактом до UI

- Причина: plan/source uncertainty, обнаруженные зависимости и текстовые заметки
  хранились в разных диагностических полях. Непустая строка не определяет серьёзность.
- Исправление: e1b5b945, материальные issues и информационные observations отдельно;
  начальные и итоговые заметки сохранены, существующий API подключён к редактору.
- Проверка: синтетические положительные/отрицательные сценарии, UI, source review.
- Статус: LOCAL FIXED. Не добавлен новый модельный критик.

## ENG-003 — валидные вспомогательные блоки отвергались следующим этапом

- Причина: план допускал non_teaching_units, сборка требовала только учебных владельцев.
- Исправление: e1b5b945, вспомогательные блоки сохраняются побайтно как контекст,
  без автоматического нормативного вывода об их ненужности.
- Проверка: полный цикл синтетического плана; сохранены все исходные байты.
- Статус: LOCAL FIXED.

## ENG-004 — старое замечание могло получить варианты из новой версии вопроса

- Причина: повторённый OPEN ID интерпретировался через текущий список вариантов.
- Исправление: e1b5b945, ID замечания связан с первым проверенным контекстом;
  новое замечание связывается с новой версией. Решения/история отделены от raw.
- Проверка: сохранение исходных вариантов после перестановки, разные контрпримеры
  одной цели, отдельные practice и quiz; регрессии и независимый source review.
- Статус: LOCAL FIXED.

## ENG-005 — допустимое использование одного пункта несколькими уроками останавливало курс

- Обнаружение: реальный Luna6/HIGH, «стандарты26», 05.11.2026 11:07UTC.
- Симптом: source_core_unit_ownership_invalid до генерации уроков. Ответ плана
  использует U5/U6 и в уроках согласования, и в уроке приёма-передачи.
- Причина: producer разрешал многие учебные связи, consumer требовал единственность.
- Исправление: many-to-many владение источником; точные байты и все владельцы
  передаются в ссылки, уточнения и зависимости. Дубли внутри раздела и конфликт
  teaching/non_teaching по-прежнему отвергаются.
- Проверка: 62focusedPASS, полныйAPI7833PASS544skipped115.23s, baselinePASS,
  независимый GO; сохранённый план без нового вызова дал полный ответ автора.
- Статус: RUN VERIFIED локально; DEV не проверен.
- Воспроизведение: `.release-evidence/p30-luna-draft-20261105/standards/stage-00/`.

## ENG-006 — замечания о покрытии подавались в контракт правильности ответов

- Обнаружение: тот же курс после реального ответа редактора, 11:14UTC.
- Симптом: practical_review_prior_scope_invalid перед финальной проверкой.
- Причина: assessment findings урока вошли в prior, поддерживающий question/source.
- Исправление: в answer-review передаются только соответствующие домены; исходный
  общий реестр остаётся в истории/редакторе, покрытие проверяется через goal_checks.
- Проверка: 63focusedPASS; полныйAPI7834PASS544skipped93.84s; baselinePASS;
  четыре полученных ответа проиграны без повторной генерации, финальный ответ
  Luna получен, полный черновик5L15Q сохранён.
- Статус: RUN VERIFIED локально, с отдельным открытым ENG-007.
- Артефакты: `shared-source-fix/standards/` и `review-domain-fix/standards/`
  в `.release-evidence/p30-luna-draft-20261105/`.

## ENG-007 — несвязанная правка могла снять первоначальный пробел покрытия

- Обнаружение: независимый source review исправления ENG-006, 05.11.2026.
- Причина: менялся любой quiz урока — исходный assessment finding мог исчезнуть,
  хотя нужная цель была NOT_REQUIRED либо ссылалась только на неизменённый вопрос.
- Исправление: серверный goal_id исходного замечания; для снятия требуется COVERED
  именно этой цели и изменённый проверенный quiz-свидетель без финального дефекта.
  Practice, чужая цель, неизменённый вопрос, INVALID_GOAL и NOT_REQUIRED не снимают
  исходное существенное замечание автоматически. Черновик при этом сохраняется.
- Проверка: 35 профильных тестов PASS, включая шесть классов исходов и плохой ответ
  при наличии изменённого свидетеля. Replay пяти реальных ответов PASS, без новых вызовов; точные хеши всех запросов совпали.
- Статус: RUN VERIFIED на сохранённых ответах, полный gate ещё выполняется.

## ENG-008 — модель распространила правило приёма-передачи на неподтверждённую ветвь

- Обнаружение: initial bank Luna, «стандарты26», 11:13UTC, L4P1.
- Случай: пример требовал подпись сменного оценщика для II категории без сомнений;
  исходник явно устанавливает эту ветвь для несогласованного кредита I категории.
- Исправление: штатный редактор уточнил в примере I категорию и несогласованность,
  без новой нормы и без ручной подсказки root. Исходный ответ сохранён.
- Статус: реальная адресная правка получена; полный независимый итоговый аудит впереди.

## ENG-009 — адресная правка покрытия может вытеснить уже проверявшееся решение

- Наблюдение: initial/final author банка «стандарты26»; при правке порога второй
  группы городов заменён вопрос о пороге первой. При добавлении положительного
  согласования заменён вопрос о составе осмотра. Это требует проверки по матрице,
  не означает автоматически неверный ключ или необходимость вопроса на каждый факт.
- Вероятная причина: редактор меняет фиксированный набор из трёх вопросов раздела;
  доказанность системной причины и достаточность итогового покрытия ещё проверяются.
- Статус: OPEN / гипотеза, не выдавать за установленную универсальную причину.

## ENG-010 — автору запрещено создавать связное учебное объяснение

- Класс: концептуальное ограничение текущего source-core, закреплённое кодом промпта.
- Доказательство: SYSTEM в practical_source_core.py явно говорит «Не создавай
  учебный нормативный текст или объяснения»; compile_source_core собирает content
  из исходных блоков, цитат и практики. Принятый эталон имеет связные объяснения.
- Следствие: одинаковая модель не получает одинаковое задание. Из этого нельзя
  заключать, что Luna не способна создать урок качества ручного эталона.
- Решение: оценить текущий полный черновик, затем возвращать автору связную учебную
  переработку при сохранении исходника/ссылок и одной общей редакторской проверке.
  Не компенсировать запрет новыми критиками и регулярками.
- Статус: OPEN, в текущем прогоне не изменялось; источники/ответы сохранены.

  Контроль 05.11.2026: полноценный keyed-редактор и одна правка той же Luna6/HIGH,
  без root-замечаний/эталона на входе, дали5L15Q/5337знаков вместо30325. Независимый
  аудит всех15ключей и16семейств — CONTENT GO для человеческой проверки, source hold
  сохраняется. Это подтверждение применимости роли, не интеграция в native worker.

## ENG-011 — одно замечание требует нескольких человеческих обоснований

- Класс: детерминированный дефект представления реестра.
- Доказательство: в Standards structured findings дублируются техническими строками
  integrity question:L3Q1/assessment:L1…L5/source:…; UI требует решения каждой строки.
- Причина: общий integrity summary превращается в новый issue поверх уже существующего
  типизированного замечания. Это не несколько независимых ошибок курса.
- Решение: не создавать второй issue из точного scope/target summary при существующем
  finding; история и настоящий независимый integrity defect сохраняются.
- Статус: OPEN; устранять на сохранённом diagnostics, без новой генерации.

## ENG-012 — содержание меняется, а историческая претензия выглядит текущей

- Класс: смешанный; контекстные выводы модели плюс контракт жизненного цикла замечания.
- Доказательство: начальная претензия о второй группе городов остаётся рядом с
  финальной претензией к тому же широкому G1 уже о роли согласующего. При этом
  вопросы по второй группе в редакции есть. Начальное и текущее утверждения нельзя
  выдавать за два доказанных текущих дефекта. Независимый ревьюер также может
  перепутать retained initial с final; решающий вывод сверяется с raw/версией.
- Решение: показывать исходную формулировку с её проверенной версией и текущим
  статусом/основанием. Группировать решения по исходному требованию, историю сохранять.
  NOT_REQUIRED означает суждение о существенности, а не доказанную полноту покрытия.
- Статус: OPEN. Число issues не является метрикой числа смысловых ошибок курса.

## ENG-013 — неполный ответ при составном условии вопроса Fire

- Класс: ошибка автора/редактора модели, подтверждённая на конкретном ответе.
- Случай: L5Q3 спрашивает о людях И материальных ценностях, ключ отвечает только
  про материальные ценности. При угрозе жизни источник требует немедленного спасения.
- Проверка: независимый аудит полного Fire7L21Q, F01–F12; исходник учит спасению,
  это неполный вариант ответа, а не потеря правила в тексте урока.
- Статус: OPEN; не превращать в универсальное правило по словам «и/или».
- Граница: локальный source-only fixture не передавал старые source questions
  о4.4/6.2 как review_only_source_context; отсутствие их в новых warnings само по
  себе не доказывает дефект native loader. Не объявлять эти вопросы решёнными.

## ENG-014 — полезный редакторский ответ отвергнут из-за несовместимости scope/target

- Класс: детерминированное рассогласование producer/consumer редакторского контракта.
- Контроль: full-editor-role/review, Luna6/HIGH,89.531s38019in4730out.
- Причина: старый untyped schema разрешает сочетание assessment+question-ID,
  consumer разрешает assessment только для lesson-ID. Модель дала применимые
  замечания о качестве отдельных вопросов, но interpret_practical_review отклонил
  весь отзыв practical_review_response_invalid. Сырой ответ не потерян.
- В локальном сравнении сохранённый отзыв передан следующей модели как непроверенные
  предложения; она повторно сверяла их с источником. Это эксперимент, не обход
  штатного gate и не утверждение, что невалидный контракт принят worker.
- Решение для интеграции: согласованный типизированный scope/target на producer,
  сохранение пригодного черновика и отдельных непроверенных замечаний; не угадывать
  смысл регулярками и не отбрасывать весь курс из-за ошибки отдельного замечания.
- Статус: OPEN для native-интеграции; ещё один запрос модели ради формата не сделан.

  05.11.2026/P31: LOCAL INTEGRATED, REAL SERVICE VERIFIED. Domain теперь отделён от
  закрытого typed target(kind,id); scope больше не кодирует одновременно вид ошибки
  и тип цели. Сохранённые10строк отзыва прошли явную legacy-проекцию без нового
  обращения. Затем три новых полных сервисных курса получили корректные typed
  отзывы от Luna; этот конкретный отказ не повторился. Это не смысловая приёмка.

## ENG-015 — полноценное keyed-ревью не гарантирует обнаружение каждой ошибки ответа

- Класс: контекстная ошибка модели; концептуальный риск общего редакторского задания.
- Доказательство: reviewer full-editor-role/review назвал исходный L3Q1 про субботу
  UNIQUE и не указал недостающее условие выходного дня. Предшествующий blind bank
  этот случай обнаружил. Полноценный редактор лучше выявил повторяющиеся исходные
  фрагменты и повторение практики, но этот частный ответ пропустил.
- Итоговая правка заменила вопрос корректным праздничным случаем без ручной подсказки;
  это подтверждает качество полученного курса, но не способность отзыва заметить
  именно первоначальную ошибку. Не заявлять100% или превосходство нового режима
  по одной проверке; сохранить тест случая и раздельную оценку функций проверяющего.
- Статус: измеренный риск, остаётся видимым при проверке новой архитектуры.

## ENG-016 — после правки объяснения наследовалась историческая привязка источников

- Класс: дефект кода/контракта версии, найден независимым source review интеграции.
- Причина: редакторское ревью относилось к первоначальному тексту, а его ссылки
  могли попасть в covered_rule_ids уже переписанного урока без проверки новой версии.
- Исправление P31: редактор возвращает актуальные lesson_sources в том же ответе;
  прежние связи остаются в истории. Новые ссылки — предложения модели, не доказанная
  полнота смысла; changed prose явно остаётся unverified даже при непустых ссылках.
  Пропуск ссылки не удаляет готовый текст, сохраняет hold для проверки человеком.
- Проверка: sourceA→newB через полный цикл/adapter; заданные новые refs сохраняются,
  historical refs не наследуются как проверенные. FullAPI7889PASS/baseline1004-2174;
  новый реальный сервисный ответ вернул5наборов ссылок без отдельного вызова.
- Статус: LOCAL FIXED / реальный контракт ответа проверен, native DB/DEV ещё не принят.

## ENG-017 — типизированная цель source не преобразовывалась общим codec

- Класс: детерминированный дефект стыка нового контракта и старого alias-конвертера.
- Причина: прежний codec знал scope+id, но не tagged object(kind=source,id); для
  массива новых источников уроков также было использовано занятое dict-поле.
- Исправление: отдельное lesson_sources и строгое преобразование только точного
  tagged source target. Чужие ID по-прежнему отвергаются; старые форматы сохранены.
- Проверка: encode/decode source target и новых source_refs, полный API и три новых
  реальных сервисных курса. Статус: REAL SERVICE VERIFIED.

## ENG-018 — цельный короткий курс теряет часть обязательного смысла источника

- Класс: смысловое поведение модели; концептуальное ограничение одного общего ревью.
- Реальные P31 результаты: Standards5L16Q — неверный первый ключ исправлен редактором,
  но остался неподтверждённый статус воскресенья в L4Q1; supporting property-care
  duty в L5 опущена. Fire7L21Q — потеря посетителей из запрета курения, отдельных
  электрических запретов, develop AND implement preventive measures; исчезла
  немедленность спасения при угрозе жизни и неверно объединены условия действий.
- Обе модельные проверки Fire объявили содержание чистым. Независимый аудит нашёл
  пропуски в обучении; это не требование отдельного вопроса на каждый пункт.
- Статус: OPEN. Курс сохраняется как редактируемый; semantic GO/production не заявлены.
- Артефакты: p31-editorial-integration-20261105/{standards,fire}-independent-review.*
  и luna-{standards,fire}-configured/. Нельзя считать случайное исчезновение ошибки
  при следующем авторе доказательством её выявления или универсального исправления.

## ENG-019 — в длинном микрокредитном курсе утрачены альтернативы и отдельные уведомления

- Класс: смысловое поведение автора/редактора; проблема полноты проверки по источнику.
- Реальный P31 Microcredit10L29Q/17944знаков: неверно обобщено согласие супруга для
  >=1000МРП без явной альтернативы заявления о несостоянии в браке; отсутствуют
  уведомления об уступке, сообщение о залоге в кредитное бюро, первичное уведомление
  о предоставленной отсрочке призывнику. Отдельный календарный месяц до продажи
  не раскрыт; доказанный более ранний незаконный момент продажи из одной лишь
  гарантии30календарных дней НЕ установлен — первоначальный пример ревьюера отозван.
- Числовые пределы неустойки исправлены моделью и присутствуют в финальном тексте;
  исходная претензия к ним является исторической EDITED_UNVERIFIED.
- Статус: OPEN, полный исходный ответ сохранён. Неправильный ключ отдельно не доказан.
- Аудит: p31-editorial-integration-20261105/microcredit-independent-review.*

## ENG-020 — новые роли не унаследовали общие инструкции сохранения смысла

- Класс: подтверждённая недоработка подключения ролей; связь с каждым отдельным
  пропуском модели является гипотезой и проверяется, а не объявляется доказанной.
- Новый P31 использовал сокращённые инструкции вместо существующих общих
  SOURCE_APPLICABILITY/FIDELITY/LOGIC и EXPLICIT_CASE требований. При переходе
  потеряны единые требования сохранения области нормы, причинности и условий.
- Исправление: общие инструкции возвращены автору, редактору и правке; слепой
  проверке явно задано различие бытового названия и нормативного статуса. Полнота
  проверяется в направлении от исходника к курсу. Нет правил под конкретный документ,
  распознавания слов регулярками или новых каскадов критиков.
- Парный контроль на сохранённом Fire, без эталона/root-findings: та же Luna
  нашла ранее пропущенный visitor scope и дополнительные общие обязанности;
  не обнаружила автоматически все ранее найденные проблемы.58.375s27953in2987out.
  Это измеренный частичный эффект, не доказательство100% качества.
- Проверка:58профильныхPASS/quality baselinePASS; свежий Fire guided6L18Q,
  4обращения/301.656s/98289in15687out. Независимо прочитаны все уроки/вопросы и
  F01–F12: visitor scope, электрические запреты и немедленность спасения восстановлены;
  отсутствие обязанности выполнить разработанные меры осталось, q5-3 подсказывает
  ответ в условии. Эти два замечания нашёл независимый аудит, не штатный reviewer.
  Статус: LOCAL INTEGRATED / PARTIAL SEMANTIC IMPROVEMENT, HUMAN REVIEW REQUIRED.

## Дисциплина проверки

Подход сравнения: самостоятельное чтение источника → логические разделы и рабочие
решения → связный черновик → общая редакторская проверка → одна адресная правка →
готовый черновик с видимыми остаточными замечаниями. Эталон стандарты26 и независимая
матрица67семейств/16границ служат контролем качества, не передаются генератору как
скрытые ответы. Время, токены и труд человека измеряются отдельно.

Стоимость фиксируется по уникальным полученным ответам; повторное чтение одного
raw не является новым вызовом. Unknown dispatch не повторяется автоматически.
Изменение уровня reasoning не объявляется улучшением без сравнения: в текущих
прогонах Luna6/HIGH остался тем же, что раньше.


## P31 guided recheck — 2026-11-05

- Standards4L12Q: independent CONTENT GO for human review across16families;
  explicit after18:00 fixes workday-premise case, property-care duty restored.
  Original source intervals stay unresolved.3calls165.469s/67377tokens.
- Fire6L18Q: three previous semantic categories repaired; prevention implementation
  still omitted and one stem discloses its answer.4calls301.656s/113976tokens.
- Microcredit11L33Q: several earlier omissions repaired, but collateral sealing/
  lost-ticket handling, assignment notices, bureau property reporting and3-day
  customer-information responses are absent. Source conjunction ambiguity is
  detected by keyed review and remains a visible source hold; prose still asserts
  AND/OR and needs human correction. No separately wrong key established.
  4calls622.516s/268432tokens. Do not label all three CONTENT GO.
- These are source/model completeness limits, not a new deterministic parser
  failure. Keep editable drafts and typed human review, without another automatic
  generator rerun. Native DEV persistence and combined UI are separate gates.

## ENG-021 — fresh managed DEV admission still selected the old review workflow

- Class: deterministic integration defect, not a semantic model failure.
- Evidence: actual owned native job43e64c49-c769-463a-9f46-c5a94c80e634 on exact
  DEV0a95a0e2 stored v3-practical-source-review-v29, no editorial marker and
  qa-managed-luna-diversity-v1 transport. Readback is tenant/actor-bound READ ONLY
  lms_app without superuser/BYPASSRLS. The course is NOT a P31 acceptance run.
- Cause: router reused source_core_qa_admission, which requires marker=None and
  disabled transport flags. Actual DEV uses the authenticated managed Luna path;
  its practical fallback still stamped29. Worker/final fences also assumed only
  the strict native transport. Focused tests used that narrower settings fixture.
- Correction: in progress; a distinct server-owned managed-editorial marker must
  pair with the existing authenticated managed transport, source/journal/profile
  and final-save checks. Do not turn off actual provider flags or rewrite old jobs.
- Verification required: actual managed settings across admission→worker→stage→
  atomic save, drift/forgery/foreign-scope negatives, then a NEW native admission.
  Existing P29 job/replies remain historical; unknown pending requests are not
  cleared or forcibly restarted. No new full generation while this is unfixed.
- Status: LIVE REPRODUCED / FIX IN PROGRESS. Evidence: native-standards-routing-
  diagnostic*.json in .release-evidence/p31-design-integration/.

  Local correction verified: server selects managed-editorial-qa-v1 only paired
  with qa-managed-luna-diversity-v1 under actual managed DEV flags; strict native
  marker remains distinct. Startup, owned source/journal verification and managed
  final transaction fence require the pair, actor, source and route.82focusedPASS,
  full unit6731PASS1skip7warnings99.04s;baseline1004/2174PASS;independent sourceGO.
  Native selection/stage/save proof on a new deployment remains required. Existing
  43e64c49 stays P29 and is not rewritten or restarted.

  LIVE correction verified2026-11-05: DEVc450f1af, new nativede6b22ce stored31,
  exact managed marker pair; actual4stage replies, final durable snapshot and
  ordinary persisted API readback match. Job completed486.9s/5L18Q/94899tokens.
  Status: FIX VERIFIED FOR MANAGED QA ROUTE. This does not close semantic/all3/prod
  acceptance. Historical43e64c49 settled and normally cancelled, no course.

## ENG-022 — source ambiguity was turned into an impossible assessment premise

- Date:2026-11-05. Class: contextual author/editor model error, not deterministic
  parser/validator defect. Native P31 Standards q1-3 states one sum falls into both
  disjoint category ranges; the key asks to recognize ambiguity. The source's own
  awkward conjunction does not make this a useful feasible employee decision.
- Evidence: owned nativede6b22ce/course9c6dbda2, initial final snapshot preserved;
  independent16-family review in native-standards-independent-review.json/.md.
  q4-4 was already fixed in the current course; its historical finding is retained
  for human review and must not be counted as a new active prose/question defect.
- Correction: one human QA edit through normal question PUT, using feasible
  2x400000 Karaganda same-client/day/branch aggregate in category I. Preserve all
  other17questions and5lesson texts; no full-course regeneration or lexical guard.
- Verified: ordinary API readback exact proposal/key/choices/explanation;18question
  IDs retained; source-uncertainty content hash00ca8f5d→702dc6aa. Initial18literal
  source quotes belong to the immutable pre-edit version. PUT clears revised
  question source_quote intentionally; do not restore it by DB or claim it verified.
- Status: QA HUMAN CORRECTION VERIFIED / SOURCE REVIEW STILL REQUIRED. Independent
  post-edit CONTENT GO for human review, not automatic clean generation, source
  resolution, approval or publication. Actual model editor did not catch this item;
  do not claim the deterministic code can prevent every future semantic variation.

## ENG-023 — received rejected reply and unreceived outcome share a legacy pending state

- Date:2026-11-05. Class: lifecycle/operational contract limitation, independent of
  course semantics. Old P24 Micro f0692f27 retains pending after a fully received
  HTTP200 reply was rejected by the old93-judgment validator. Original body SHA
  d796e2c6...d11d7 and83622received tokens are recorded; no final course. It must
  never be resumed/reset/replayed/promoted or refunded as an unmade request.
- Effect: normal source-set admission correctly blocks another job. Existing
  abandon-unknown would falsely assert an unknown provider response for this case.
  Removing pending guards or duplicating the source is not a safe correction.
- Correction LOCAL: normal owned POST/jobs/{id}/quarantine acknowledges retaining
  the stage, not provider outcome/cost. Interrupted-only/no course/valid pending/
  no final-save intent; expected_updated_at compared under advisory→tenant→job
  locks. Terminal failed/quarantined metadata fingerprints pending; original
  params/result/journal/reservation state remain unchanged. No provider request
  is dispatched or cancelled. Late-save/rerun guards remain; no refund.
- Verification:52focusedPASS;6746unitPASS1skip7warnings89.83s before final visible
  error projection adjustment, final52PASS after; baseline1005/2174PASS. Added two
  real PostgreSQL/RLS concurrency tests, locally SKIPPED as expected, CI pending.
  Independent reviewer requested truthful reservation:unchanged response, fixed.
- Status: LOCAL VERIFIED, NOT DEPLOYED/NOT EXECUTED. Do not relabel original
  response as unknown/accepted or claim successful live quarantine before readback.
  Update LIVE VERIFIED on DEV12d33577: CI42059258101 both real PG contention/
  isolation tests PASS; one owned normal quarantine f0692f27 read back unchanged
 11checkpoint rows, original pending result/source/prior parameters/reservation.
  No received-rejected response/cost truth overwritten. New P31 admission b41487fe
  succeeded on the same source without replaying any historical request.

## ENG-024 — dropped permission qualifier in a generated exception

- Date:2026-11-05. Class: contextual author/editor model omission. Native P31 Fire
 75991580/6L18Q L6 described continuous-operation devices without retaining that
  they must be permitted devices; source6.2 includes that qualification.
- Correction: one independently reviewed human lesson PATCH, keeping existing
  five other lessons and all18question objects unchanged. No global regex,
  full-course regeneration or additional model critic. Prior automatic draft stays
  in immutable native snapshot, metadata still requires source/human review.
- Verified: normal API readback manual-fire-l6-result.json, content snapshot
  6b09a997→47f2e5fc; current phrase explicitly includes permitted continuous-operation
  devices. Genuine parenthetical source-scope ambiguity remains held.
- Status: HUMAN QA CORRECTION SAVED; independent after-edit review next. Model
  generation4replies91298in15121out106419tokens, no model call for the manual edit.
  Update: independent after-edit CONTENT GO for human review; existing source/
  provenance holds remain. No approval or publication.

## ENG-025 — a long course can cite a rule without teaching its workflow

- Date:2026-11-05. Class: recurring author/editor coverage omission in dense
  source, distinct from conversion/data loss. Micro D30 assignment notices and
  D31 bureau/property reporting missing from both guided local and native P31
  lesson narratives. In native immutable output both exact source passages are
  still present in assessment source_quote fields. Citation/quiz presence is
  therefore no proof of instruction. Source not removed or rewritten by parser.
- Native Micro b41487fe:11L30Q24,476chars;4Luna6HIGH responses857.6s,
  229863in33791out263654tokens,30/30literal quotes, no pending. Independent
 39-family/7-boundary lesson and separate30-question review found D30/D31,
  refusal and spouse source conflicts, and L6Q1 insufficient conditions.
- Correction in owned QA draft: L10 restores both workflows with recipient,
  trigger, channels and deadlines; L1/L2 retain both conflicting source provisions
  and ask for source-owner clarification; L1Q2 uses explicitly married applicant,
  L6Q1 gives actual whole/complete precious-metal-and-stone conditions.3lesson/
 2question ordinary edits,8lessons/28questions unchanged,0new modelcalls.
  All prior raw responses/snapshot kept; revised question quotes cleared, source
  holds/pending retained. Original source conflicts recorded separately, not
  silently resolved. No new prompt/heuristic claimed to prevent recurrence.
- Status: HUMAN QA CORRECTION VERIFIED, model coverage limitation remains.
  Existing one editor should check meaningful source workflows against teaching
  passages; do not add per-point retry loops or count attached quotes as coverage.
  If improving this review, use the saved before/after as a bounded witness,
  keeping previous P31 request bytes and recovery valid. No repeated full-course
  runs just to remove known human-review findings.

## ENG-026 — JSONB changes the byte identity of a resumed editorial request

- Date: 2026-11-05. Class: deterministic request serialization defect, separate
  from lesson quality, provider behavior and validation. Exact offline replay of
  Standards found the author checkpoint, then failed to match the completed
  editor checkpoint on request_sha256 alone. The JSONB response digest remained
  valid: object order in prompt strings was significant, unlike the stored JSON.
- Cause verified on all three native courses: restoring provider schema order
  recovered all 12 original request hashes and all three original course
  snapshots. This is a diagnostic reconstruction, not a historical data edit
  or proof of a live interrupted resume.
- Fix: new server-stamped editorial policy 32 uses canonical object key order
  in embedded prompt JSON; arrays, prompt instructions and the four-stage
  editorial flow are unchanged. Stored P31 retains its original request bytes;
  no fallback claim, historical rewrite or additional review/inference.
  Source, actor, model route and policy checks remain in place at save.
- Verified locally: stage-journal interruption regression with simulated JSONB
  ordering resumes only the missing stage. Three sets of stored native responses
  yield the same 12 canonical request hashes before and after object reordering
  and the same original courses. Zero provider/DB calls in the replay. Evidence:
  .release-evidence/p31-ordinary-dev-20261105/native-p32-canonical-replay.json.
  Live DEV P32 recovery and provider acceptance are separate, still open.

## ENG-027 — Source review lost a semantic finding while handling cosmetic edits

- Date: 2026-11-06. Three separate failure modes were observed/reproduced. The
  first author could mark a material `conflict` under `unresolved` while the
  cosmetic compiler accepted only edit categories. Replay stopped at
  `source_editorial_invalid_unresolved_category` before the independent review.
  Route material clues to the reviewer; keep the strict compiler for patches.
- Exact DEV `76b199bf` passed the two-deadline PPTX case end to end with two
  Luna 6 calls and grounded findings, and TXT independently reached the same
  result. DOCX extracted both competing deadlines twice, but the second real
  response had no findings. XLSX stopped in `independent_review_response` with
  `source_review_overlapping_or_stale_edit`. No earlier generic error was
  assigned a precise cause without runtime evidence.
- Reproduced the XLSX failure code locally with a safe two-spaces-to-one
  automatic edit. Allow whitespace-only replacements only when the exact
  original span is also all whitespace. Empty replacements and erasing words
  with whitespace still fail. The unresolved policy finding survives.
- Source analysis v3 begins with comparing original instructions across sections
  and table rows; the cosmetic verdict contract is included only when edits
  exist. A material author clue must receive an explicit decision tied to an
  original quote. No additional provider calls and no auto-resolution of a
  substantive source conflict. The omitted-clue regression fails closed.
- Evidence: `.release-evidence/course-ux-docx-synthetic-review-evidence.json`,
  `.release-evidence/course-ux-dev-clue-fix-pptx.json`, and
  `.release-evidence/course-ux-dev-clue-fix-remaining.json` in the
  `course-creation-ux-20261106` worktree. All used DEV fixtures verified absent.
  Latest local corrections still require exact live DOCX/XLSX acceptance.

## ENG-028 — Source review stopped on a complete invalid JSON response

- Date: 2026-11-06. Exact DEV `54fc6927`: Word detected and anchored the
  contradictory 24/72-hour deadlines, two Luna 6 calls, 135 seconds including
  cleanup. Excel extracted successfully but the editor request stopped after
  a complete HTTP 200 at the `content_json` parser, confirmed in the sanitized
  DEV worker log. No raw model reply or client document was captured.
- The review client now opts in to a distinct error for this completed failure.
  It can make one corrective JSON request for the entire analysis run; source
  text and semantics are unchanged, and all independent checks still run.
  No repeat on a transport-unknown result, timeouts, or other response failures.
  Failed content is never accepted and existing generation clients keep their
  rejection behavior. The extra call is counted separately from usable replies.
- Evidence: `.release-evidence/course-ux-dev-audit-v3-probe.json`,
  `.release-evidence/format-r6/dev-review-log.json`. Both synthetic documents
  were deleted and verified absent. The remaining matrix stopped before any
  model call. The retry mechanism is covered offline; live release acceptance
  still requires the corrected exact candidate.

## ENG-029 — An invalid clue disposition discarded the rest of source review

- Date: 2026-11-06. Exact DEV `eb6585b1` passed both provider transport stages
  for the Excel fixture, then failed at `independent_review_response` with
  `source_review_clue_disposition_invalid`. The exact invalid field is unknown;
  no raw reply was retained. No extra format review was submitted, and the Excel
  fixture was removed with verified absence.
- Analysis v4 isolates a missing, malformed, duplicated or ungrounded decision.
  The author clue remains open for a human, marked as unconfirmed; already
  grounded independent findings survive. The original is unchanged, unresolved
  issues still prevent approval, and a replacement needs an exact original
  quote. An unbound clue suppresses automatic edits in the same block. There
  are no extra model calls for this case.
- Deterministic regressions include a wrong question link alongside a valid
  independent finding, a missing clue disposition and a correctly evidenced
  dismissal. DEV evidence: `.release-evidence/course-ux-dev-json-r7-probe.json`.
- Exact DEV `49902a0d` passed Excel in 130 seconds with two Luna 6 calls and
  no retry. It showed the conflict as an anchored open question. An additional
  finding expressed the same conflict without exact table markers and remained
  unbound; this is a known duplicate, not a lost or automatically resolved
  question. No model response was used as a human decision. Exact product
  proof is in `.release-evidence/format-r8/`.
- 2026-11-07: the saved reviewer excerpt omits the closing Markdown table pipe
  on its first row. This left the reviewer question unbound while the author
  clue retained the literal span. The overlap pass saw only one of the two
  copies. The local correction restores coordinates only if inserting that
  separator identifies one literal table span. Replaying the saved pair then
  yields one open issue. Repeated source rows and changed deadlines remain
  unbound. Production `49902a0d` produced one anchored issue for each Excel
  fixture in the separate nine-format run.

## ENG-030 — A source echo invalidated the independent review response

- Date 2026-11-07. Released backend 0.11.79 `ebc80e21` removes the saved Excel
  duplicate. All nine formats were exercised through the production synthetic
  tenant. Eight formats passed. PDF failed repeatedly, and the first separate
  XLS check also failed, at `independent_review_response`. Bounded production
  logs identified Pydantic `ValidationError`. A subsequent separate XLS/XLSX
  pair passed with exactly one anchored open conflict per original.
- One bounded diagnostic on the exact uploaded synthetic PDF and the canonical
  `load_direct_source_corpus` path reproduced `original / extra_forbidden`.
  Its recognized source SHA was `ee97ac310641ef1bae3d15996d9e5d53147011a2396d8eaa6fbb4b67e036b02a`.
  The reviewer echoed an input field. Recognition had preserved both deadlines.
  Raw customer content and model bodies were excluded from diagnostic logs.
- The response adapter discards only the unused `original` field. It cannot
  supply or rewrite the recognized source. All other unexpected fields and
  invalid finding categories still fail. Five regressions cover exact and
  altered echoes, an object echo, an unknown decision field and an invalid
  category. The 34-test source review suite and focused Ruff checks passed.
  The new exact release and ordinary production format acceptance are pending.
- Evidence under `.release-evidence/table-quote-v079/`, including
  `review-failure-classes.json`, `pdf-diagnostic-final.json` and
  `pdf-corpus-diagnostic.json`. Original failed format receipts are preserved.
  All disposable browser and diagnostic documents were removed with verified
  absence. CodeGraph readiness reported a missing per-checkout runtime, so this
  known local response-adapter repair used bounded source inspection.

## ENG-031 — Completed source review replies can violate the response schema

- Date 2026-11-07. Exact production 0.11.80 `81e28c20` accepted PDF through
  the ordinary browser after ENG-030. XLSX and CSV still failed at independent
  response validation. Their raw rejected replies were not retained, so their
  exact offending fields are unknown. A separate canonical XLSX diagnostic
  returned one grounded issue with two completed DeepSeek replies, 2,287 input
  and 2,797 output tokens. This does not relabel either ordinary failure.
- The response contract now permits one corrective request after a completed
  object fails Pydantic validation. Feedback supplies only safe field paths and
  error types. The same model receives its rejected JSON as untrusted correction
  context with an instruction to preserve valid findings. Original/proposal
  stay identical and the revised reply runs strict validation again. Rejected
  response bodies are kept out of logs.
  One correction budget is shared by all blocks of an analysis run. A second
  invalid reply fails. Unknown transport outcomes, timeouts and a changed
  proposal identity do not trigger this correction. No findings are discarded
  or accepted merely to complete processing. Successful corrections add one
  to the stored model-call count.
- Six new offline cases cover category, extra-field and list-shape errors,
  shared multi-block budget, timeout and unknown-outcome negatives. All 40
  source-review tests and focused Ruff passed. Local correction awaits exact
  CI, protected production release and ordinary nine-format acceptance.
- The 0.11.80 Word run also returned a distinct grounded reference question
  about form versus record. This is separate from the deadline conflict and
  must remain visible. The acceptance harness must count one deadline conflict,
  rather than requiring one question of any kind for an entire document.
  Evidence `.release-evidence/prod-v080-*-result.json` and
  `.release-evidence/source-echo-v080/xlsx-corpus-diagnostic.json`. All used
  synthetic sources were removed and verified absent.
- Final verification 2026-11-07. Exact production0.11.81 `369f82a1`,
  CI42333787858/protected42334400327 PASS. Ordinary final nine-format checks
  passed, including CSV with three completed model stages and one open anchored
  issue. The source and original blob remained unchanged. Separate same-file
  XLS/XLSX checks passed14s/29s with one deadline question each. Initial CSV
  browser automation failed before terminal readback, exact cause unknown,
  original receipt preserved. Runtime saved-case replay independently verified
  one correction and strict final validation with zero provider calls.
  Full proof and scope in RUN-20261107-PROD-SOURCE-SCHEMA-081.

## ENG-032 — Text conversion silently omitted embedded instructional images

- Saved reproduction: the supplied cash DOCX contains ten native illustrations.
  The ordinary local text converter returned13152 characters without image IDs or
  placements while retaining references such as “as shown in the picture”.
- Cause: conversion represented the document as text, without a visual-source
  contract propagated through approval, generation and learner delivery.
- Local fix: native text/table/image placements, bounded visual readings,
  source-bound checkpoints, complete semantic partition, selected immutable
  manifest, approved image markers and snapshot-authorized binary endpoints.
  Source retention now covers released and approval-revision snapshots.
- Saved real-file preparation:9PDF page images/42recognized blocks/3parts and
  10DOCX images/129blocks/7parts. Twelve completed requests,38274input/19380output
  reported tokens. This is preparation evidence, not generated-course acceptance.
- Verification: full local API6856PASS/web1696PASS; focused recovery, image
  authorization, old page approvals and selection tests. Isolated settings
  upgrade/audit/RLS/cleanup PASS. Hosted DEV and production pending.
- Status: LOCAL FIXED. Evidence `.release-evidence/source-preparation/`.

## ENG-033 — Selected-page approval failed its immutable readback

- Cause: approval payload included selected pages, while read_approval rebuilt
  the expected payload without pages. A later generation pin rejected that
  approved edition instead of using the agreed material.
- Local fix: reconstruct historical optional page fields and new preparation
  bindings using their original shapes. Legacy command digests remain unchanged.
  Selection changes are revision-bound, and previous approved pins remain stable.
- Verification: saved-payload tests and competing-command gate prepared; hosted
  worker readback remains part of current DEV acceptance.
- Status: LOCAL FIXED; no historical failed receipt was relabeled.

## ENG-034 — Image description substituted expected context for visible wording

- Source: actual cash instruction image7. First visual author described a basis
  from neighboring prose rather than the visible dialog. Native pixels and
  literal text were retained, but interpretation could distort subsequent teaching.
- Fix: independent pixel-based editorial verification of complete readings;
  neighboring prose and proposed reading explicitly untrusted, literal text and
  non-normative descriptions separate. Completed schema errors receive one
  addressed correction, good siblings preserved, unknown calls never repeated.
- Saved result: image7's invented basis removed. Ten images preserved under
  matching PKO/RKO/cashbook parts. Remaining image4 signature-description overclaim
  is visible in audit and generic role instruction tightened before hosted DEV;
  it is not proof of completed signing and not a source business-rule change.
- Scope: local evidence only. Both files cumulatively28completed requests,
  111905input/108733output reported tokens, including historical failed replies.
  Hosted generated-course/production acceptance pending. Actual returned model
  identity unavailable; configured DeepSeek is not asserted as identity proof.
- Recovery audit found a legacy-state bypass: provisional old manifests could
  hydrate after failure or be newly approved after reopen without the new visual
  review. Exact verified-checkpoint provenance is now required for queued reuse
  and new approval; explicit fresh retry is available and historical approved
  snapshots preserved. Local58source-review cases and independent code review
  PASS; integrated hosted source/course acceptance remains pending.
