# Corporate Stage 1: результат приёмки

Дата: 2026-09-26  
Source snapshot: `94d064ae59ed50bb51fa4f78870e2e77fa037fd5`  
Итог: `PARTIAL / NO-GO для объявления полной corporate readiness`

## Краткий вывод

Базовые корпоративные контракты, tenant isolation, иерархия, повторное
назначение, журнал обучения, подписанные экземпляры и Evidence V2 проходят
актуальные local/DEV проверки. Канонический реальный DEV-маршрут
`XLSX -> index -> Evidence V2 -> course/tests -> cleanup` завершился и не
обнаружил структурных дефектов курса или тестов.

Полная приёмка не закрыта по двум причинам:

1. production API работает на `94d064ae`, а production frontend `/healthz`
   сообщает `7f54b652`; UI и API не доказаны как единый release;
2. полный human path архетипа A от настройки структуры до повторного
   назначения и evidence package не выполнялся на одном синтетическом наборе
   данных текущего release. После обнаружения release mismatch новые
   production writes не выполнялись.

## Runtime identity

| Контур | Результат | Наблюдаемое доказательство |
|---|---|---|
| Production API | PASS | `/health` и `/api/v1/health`: HTTP 200, `0.11.5`, SHA `94d064ae` |
| Production frontend | FAIL | `/healthz`: HTTP 200, body/header SHA `7f54b652`, не равен API/source SHA |
| Production login | PASS | `/login`: HTTP 200 |
| Production dashboard | PASS с оговоркой | synthetic methodologist вошёл; headings и данные доступны; API responses >=400 отсутствуют; overflow отсутствует на 1440/1024/390 px; frontend при этом остаётся старой ревизией |
| DEV API | PASS | HTTP 200, `0.11.5`, SHA `94d064ae` |
| DEV frontend | PARTIAL | `/login`: HTTP 200; `/healthz`: 404, поэтому exact frontend SHA публично не доказан |

HTTP 200 старого frontend не компенсирует несовпадение release identity.

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
| A. Небольшая компания | PARTIAL | production login/dashboard UX; DEV source-to-course generation и cleanup | один непрерывный human path до learner completion, signed scan, repeat и evidence package на synchronized release; педагогическое покрытие курса PARTIAL |
| B. Филиальная структура | PASS для contracts/DEV | import, hierarchy, assignment/reassignment, RLS | 1k browser performance и массовый UX не проверены |
| C. Регулируемая компания | PASS для contracts/DEV, PARTIAL product | immutable history, training log/evidence, signed-copy review, tenant boundaries | комиссия/решение о допуске и scheduled retention отсутствуют; full runtime reconciliation не пройден |

Числа B/C не являются SLA.

## Hard-gate verdict

- Tenant/RLS negatives: `PASS`.
- Import/assignment idempotency contracts: `PASS`.
- Repeat occurrence/history contracts: `PASS`.
- Signed scan review/evidence contracts: `PASS`.
- AI course structural quality on canonical real DEV run: `PASS`.
- AI course human pedagogical review: `PARTIAL`.
- Disposable DEV cleanup: `PASS`.
- Exact synchronized production frontend/API release: `FAIL`.
- Dashboard/log/export/evidence reconciliation in one live journey: `NOT VERIFIED`.
- Complete production synthetic corporate journey: `NOT VERIFIED`.

## Следующее минимальное действие

1. Выпустить или откатить production frontend так, чтобы `/healthz` и API
   показывали один exact SHA; затем повторить production dashboard smoke.
2. Добавить exact frontend build identity для DEV.
3. После синхронизации выполнить один bounded synthetic human journey по
   шагам 1–13 acceptance plan с timing ledger и cleanup readback.
4. Отдельно выполнить capacity acceptance; до этого не обещать 1k/10k SLA.
5. Для Evidence V2 добавить измерение coverage по source entities/facts и
   минимальное качество explanation; не добивать фиксированное число вопросов
   padding-ом.
6. Исправить четыре dashboard UX-находки отдельным минимальным изменением и
   повторить тот же production synthetic screenshot/browser gate.

