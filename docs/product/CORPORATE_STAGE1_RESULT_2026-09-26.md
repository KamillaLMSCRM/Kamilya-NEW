# Corporate Stage 1: результат приёмки

Дата: 2026-09-26  
Source/runtime snapshot: `66576b1a4ab33f201956aae0e3798aed26d0023b` (`v0.11.7`)
Итог этапа 1: `PASS_WITH_FOLLOW_UP`; итог всей corporate readiness: `PARTIAL`

## Краткий вывод

Базовые корпоративные контракты, tenant isolation, иерархия, повторное
назначение, журнал обучения, подписанные экземпляры и Evidence V2 проходят
актуальные local/DEV проверки. Канонический реальный DEV-маршрут
`XLSX -> index -> Evidence V2 -> course/tests -> cleanup` завершился успешно.

Release mismatch устранён: API и frontend production работают на одном SHA
`66576b1a`, версия API `0.11.7`. Отдельный живой пользовательский прогон на
синтетическом источнике создал курс и тесты за 67 секунд, после чего
одноразовый черновик был удалён с точным readback отсутствия.

`PARTIAL` относится не к релизу этапа 1, а ко всему корпоративному продукту:
полный путь от структуры и назначения до прохождения, подписанного скана,
повторного назначения и evidence package ещё не повторён одним непрерывным
production-сценарием на текущем SHA.

## Runtime identity

| Контур | Результат | Наблюдаемое доказательство |
|---|---|---|
| Production API | PASS | `/health` и `/api/v1/health`: HTTP 200, `0.11.7`, SHA `66576b1a` |
| Production frontend | PASS | `/healthz` и `X-Kamilya-Release`: HTTP 200, SHA `66576b1a` |
| Production login | PASS | `/login`: HTTP 200 |
| Production dashboard | PASS с UX follow-up | synthetic methodologist вошёл; headings и данные доступны; API responses >=400 отсутствуют; overflow отсутствует на 1440/1024/390 px |
| DEV API | PASS | HTTP 200, `0.11.5`, SHA `94d064ae` |
| DEV frontend | PARTIAL | `/login`: HTTP 200; `/healthz`: 404, поэтому exact frontend SHA публично не доказан |

Production release chain: CI `36221935456`, native frontend build
`36222253356`, protected backend release `36222254803`, production smoke
`36223181166` — все `success`. Git tag and GitHub release `v0.11.7` указывают
на точный SHA `66576b1a`.

## Local deterministic gates

| Набор | Результат | Время |
|---|---:|---:|
| AI-COURSE-01 critical journey | 7 passed | 4.29 s |
| Corporate contracts: hierarchy, repeat, log/evidence, signed scans, packages | 118 passed | 5.23 s |
| Frontend focused corporate workflows | 121 passed / 18 files | 34.30 s |
| Evidence V2 and assessment quality | 144 passed | 7.31 s |
| Staff import and assignment contracts | 121 passed | 2.80 s |

Итого: `511 passed`; один Pydantic deprecation warning в corporate API-наборе,
продуктовых failures нет. Это не runtime evidence.

## Isolated Supabase DEV gates

| Проверка | Результат | Основное доказательство |
|---|---|---|
| Read-only environment preflight | PASS | canonical DEV, revision `0163`, `lms_app` без superuser/BYPASSRLS, writes `0` |
| Training log | 23 passed | 163.00 s, cleanup PASS, residue `0` |
| Signed training evidence | PASS | tenant isolation, pending/review/accept/replace contracts, cleanup PASS |
| Organization hierarchy V2 | PASS | depth 0–8, depth 9 rejected, cycle/overflow/head-office/cross-tenant negatives, cleanup PASS |
| Manual reassignment | PASS | occurrence/history and cross-tenant negatives, cleanup PASS |
| Learning Insights | PASS | exact answers, privacy/role/RLS/bounded-query gates, cleanup PASS |
| Learning Actions | PASS | tenant-owned lifecycle, append-only and cross-tenant negatives, cleanup PASS |

## Real DEV course generation

Использован утверждённый синтетический fixture
`expanded_collections.xlsx`, SHA-256
`13d7dbbaf0ef0b133059fc853d13b220340bf71b2ed670cbd9e70ee15bfb9449`.

Канонический маршрут с обязательным wake/keepalive Render Free worker прошёл
upload, index `processing -> ready`, adaptive course size, asynchronous queue,
Evidence V2 generation и удаление disposable course/document за `45.23 s`.
Runner завершился с exit `0`, 13 checks и `passed=true`. Результат:

- 1 module;
- 2 lessons;
- 2 quizzes;
- 6 questions;
- recommended/hard maximum: 2 lessons;
- 3 из 3 focus terms найдены;
- generic titles, unsupported lessons, lessons without sources, meta questions,
  duplicate questions/choice sets, invalid correct counts, weak distractors,
  answer leakage, fixed-position bias, longest-answer bias и unsupported
  relationship claims: `0`;
- cleanup course/document: `PASS/PASS`.

Перед финальным PASS были три ошибки запуска, не продукта: review artifact вне
system temp, исчерпанная demo quota и пропущенный обязательный
`--worker-health-url`. Последняя ошибка оставила disposable document в
`processing`; он был переведён штатной application-операцией в failure,
удалён через API и production cleanup-код. Readback: document rows `0`, cleanup
job `completed`, index job `failed`, tenant восстановлен в `is_demo=true`.
Канонический повтор после исправления маршрута прошёл полностью.

### Human review результата

Машинный structural gate прошёл, но педагогическое качество — `PARTIAL`:

- все вопросы и варианты относятся к фактам того же смыслового блока;
- отвлекающие варианты предметные, бессмысленных вариантов нет;
- два урока соответствуют объёму малого источника, искусственного padding нет;
- содержание уроков в основном перечисляет характеристики, а не объясняет их
  применение;
- `explanation` повторяет правильный ответ, а не объясняет причину;
- в финальном наборе шесть вопросов покрывают «Север» и «Берег», но не
  проверяют факты по «Риф», хотя он входит во второй урок;
- на одинаковом fixture успешные/почти успешные запуски дали 4, 2 и 6 вопросов.
  Допустимый максимум соблюдён, но точное покрытие и объём недетерминированы.

Вывод: для простого каталожного источника результат пригоден как factual
training draft, но это не доказательство уровня 9/10 и не основание считать
semantic coverage полностью решённым.

## Production human smoke на `v0.11.7`

Суперадмин вошёл в `Kamilya Production Smoke (Synthetic)` как методист,
выбрал документ `Smoke: безопасное обслуживание клиента`, оставил цель курса
пустой и подтвердил повторное использование источника причиной
`Другая аудитория`.

- accepted/queued: `2026-09-26T06:23:31Z`;
- completed: `2026-09-26T06:24:26Z`; UI result readback через 67 секунд;
- progress readback: `0% -> 90% (0/3 блоков) -> 92% (2/3) -> completed`;
- результат: 1 модуль, 3 урока, 3 теста, 7 вопросов (`2/3/2`);
- новые console errors после принятого запуска: `0`;
- все distractors относятся к проверяемому факту; бессмысленных вариантов,
  мета-вопросов и искусственного padding нет;
- исправленный semantic-axis подтверждён: вопрос об эскалации объясняется как
  `положение`, а не как ложный `срок`; вопрос о персональных данных — как
  `обязанность`;
- два вопроса проверяют 15-минутный первый ответ в разных контекстах; это
  допустимая смысловая близость, но не буквальный дубль;
- каждый AI-тест остался в `needs_review`, курс — `draft/pending`, публикации
  без методиста не произошло.

Первый bounded submit до запуска получил ожидаемый `403` суточной demo-квоты.
Квота была возвращена только для exact platform subject и exact synthetic
tenant через канонический VM126-контур; тарифы и клиентские лимиты не менялись.
После приёмки одноразовый курс `e7eff3ea-a8be-455c-83de-7654453f3c58`
удалён с guards по tenant/title/status/review/created_at/no-enrollment;
production readback: `deleted=1`, `absent`.

## Visual UX review production dashboard

Положительное:

- desktop и mobile layout читаемы, горизонтального overflow нет;
- следующий шаг и быстрые действия видимы;
- attention/training/content блоки логично сгруппированы.

Найдено:

1. demo banner имеет недостаточный контраст белого текста на светлом фоне;
2. «Готово — все шаги пройдены» визуально противоречит двум проблемным
   назначениям и одной генерации с проблемой; нужно уточнить, что речь только
   о первичной настройке кабинета;
3. failed generation показана сырым идентификатором `0228597d`, а не понятным
   названием/причиной/следующим действием;
4. синтетическое имя `выфвыфы фыфвыв` делает acceptance-экран похожим на
   технический стенд и мешает оценивать клиентскую понятность.

## Архетипы

| Архетип | Статус | Что доказано | Что не доказано |
|---|---|---|---|
| A. Небольшая компания | PARTIAL | synchronized production login/dashboard и source-to-draft generation; DEV source-to-course и cleanup | один непрерывный human path до learner completion, signed scan, repeat и evidence package; большой неоднородный источник остаётся отдельной приёмкой |
| B. Филиальная структура | PASS для contracts/DEV | import, hierarchy, assignment/reassignment, RLS | 1k browser performance и массовый UX не проверены |
| C. Регулируемая компания | PASS для contracts/DEV, PARTIAL product | immutable history, training log/evidence, signed-copy review, tenant boundaries | комиссия/решение о допуске и scheduled retention отсутствуют; full runtime reconciliation не пройден |

Числа B/C не являются SLA.

## Hard-gate verdict

- Tenant/RLS negatives: `PASS`.
- Import/assignment idempotency contracts: `PASS`.
- Repeat occurrence/history contracts: `PASS`.
- Signed scan review/evidence contracts: `PASS`.
- AI course structural quality on canonical real DEV run: `PASS`.
- AI course human pedagogical review на малом структурированном источнике: `PASS`.
- Disposable DEV cleanup: `PASS`.
- Exact synchronized production frontend/API release: `PASS` (`v0.11.7`).
- Bounded production source-to-draft human smoke and cleanup: `PASS`.
- Dashboard/log/export/evidence reconciliation in one live journey: `NOT VERIFIED`.
- Complete production synthetic corporate journey: `NOT VERIFIED`.

## Следующее минимальное действие

1. Выполнить один bounded synthetic human journey по
   шагам 1–13 acceptance plan с timing ledger и cleanup readback.
2. Добавить exact frontend build identity для DEV.
3. Отдельно выполнить capacity acceptance; до этого не обещать 1k/10k SLA.
4. Для Evidence V2 добавить измерение coverage по source entities/facts и
   минимальное качество explanation; не добивать фиксированное число вопросов
   padding-ом.
5. Исправить четыре dashboard UX-находки отдельным минимальным изменением и
   повторить тот же production synthetic screenshot/browser gate.
6. Перейти к этапу 2: единая explainable матрица обязательного обучения как
   source of truth для dashboard, training log и CSV.

