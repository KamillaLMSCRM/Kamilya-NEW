# Kamilya Corporate Readiness: карта продукта

Дата среза: 2026-09-28
Git/runtime-срез: `967d15cd82a96bc863560769dc2a0e356acfea9f` (`v0.11.12`)
Назначение: source of truth для корпоративной приёмки и перехода к этапу 3.
Результат этапа 1: [`CORPORATE_STAGE1_RESULT_2026-09-26.md`](CORPORATE_STAGE1_RESULT_2026-09-26.md).

## Продуктовая граница

Kamilya — multi-tenant система внутрикорпоративного обучения. Основной
проверяемый результат:

> Компания знает, кто, чему, почему и к какому сроку должен обучиться, видит
> отклонения и может доказать прохождение конкретной версии обучения.

Публичная продажа курсов, учебный маркетплейс, собственный прокторинг,
собственная видеоконференц-платформа и интеграция с ЕЦС не являются частью
основного корпоративного контура.

## Уровни доказательности

- `SOURCE-VERIFIED` — поведение найдено в актуальном source/API contract.
- `TEST-VERIFIED` — поведение покрыто актуальным детерминированным тестом.
- `DEV-VERIFIED` — есть изолированное Supabase DEV/RLS подтверждение и cleanup.
- `HISTORIC-RUNTIME` — существовало живое подтверждение на более раннем
  release; оно не доказывает текущий runtime.
- `LIVE-RECHECK` — нужен новый человеческий проход на точном deployed SHA.
- `PARTIAL` — полезная часть реализована, но корпоративный workflow не замкнут.
- `ABSENT` — канонической реализации нет.

HTTP 200, наличие страницы, локальный commit или прежний production smoke сами
по себе не повышают capability до текущего `LIVE-RECHECK PASS`.

## Карта возможностей

| Корпоративная возможность | Текущее состояние | Доказательство | Что проверяет этап 1 |
|---|---|---|---|
| Tenant boundary и активная роль | Реализовано | SOURCE/TEST, прежние runtime smokes | cross-tenant negatives и impersonation exit |
| Документы: upload, conversion, index, reindex | Реализовано | SOURCE/TEST, HISTORIC-RUNTIME | PDF/XLSX, повтор, ошибка provider, точный progress |
| Evidence V2: source -> draft course/test | Structural PASS, pedagogical PARTIAL | SOURCE/TEST/DEV/PROD на `0.11.12` | entity/fact coverage, meaningful explanations и learner-visible quality |
| Review, edit, publish immutable release | Реализовано | SOURCE/TEST, HISTORIC-RUNTIME | draft/review/publish и сохранение версии |
| Сотрудники и должности | Реализовано | SOURCE/TEST, HISTORIC-RUNTIME | ручной ввод, import preview/commit, необязательное подразделение |
| Организационная иерархия произвольной глубины | Реализовано | SOURCE/TEST, прежний four-level smoke | 4 уровня, breadcrumbs, центральный офис, cleanup |
| Группы и программы обучения | Реализовано | SOURCE/TEST, HISTORIC-RUNTIME | сохранение группы и последовательная программа |
| Правила и ручные назначения | Реализовано | SOURCE/TEST, HISTORIC-RUNTIME | дедупликация и основание назначения |
| Email invitation и manual fallback | Реализовано | SOURCE/TEST, HISTORIC-RUNTIME | delivery state/readback без отправки клиентам |
| Learner lessons, progress, quiz, completion | Реализовано | SOURCE/TEST, HISTORIC-RUNTIME | mobile path, resume, fail/retry/pass |
| Повторное назначение и сохранение истории | Реализовано недавно | SOURCE/TEST | новый live/DEV occurrence path |
| Сертификат и подтверждение результата | Реализовано | SOURCE/TEST, HISTORIC-RUNTIME | одинаковая доступность из email-link и обычного кабинета |
| Подписанный экземпляр и review | Реализовано | SOURCE/TEST/DEV | upload, request replacement, accept, audit |
| Training log и PDF/ZIP evidence | Реализовано | SOURCE/TEST, HISTORIC-RUNTIME | reconciliation с dashboard/export |
| Restricted evidence share | Реализовано | SOURCE/TEST | expiry, download limit, revoke, no public PII |
| Retention и legal hold | Частично | SOURCE/TEST | manual dry-run; scheduled purge остаётся backlog |
| Внутренняя аттестация и допуск | Только конфигурация procedure | PARTIAL | fail-closed; фактическая комиссия/решение отсутствуют |
| Recurring learning cycles | Частично | SOURCE/TEST/DEV для отдельных срезов | occurrence, reminder, repeat history, overdue read model |
| Action center и deadline read model | Реализовано и выпущено | SOURCE/TEST/DEV/PROD | непрерывная corporate reconciliation остаётся этапом 3 |
| Methodologist dashboard | Реализовано и выпущено | SOURCE/TEST/DEV/PROD на `0.11.12` | сверка matrix/log/export/evidence в одном journey |
| Learning Insights / слабые темы | Локально реализовано | SOURCE/TEST/DEV для срезов | current-runtime privacy и action navigation |
| SCORM 1.2 | Реализован базовый flow | SOURCE/TEST | реальные пакеты и browser UX |
| Матрица обязательного обучения | Реализована и выпущена | SOURCE/TEST/DEV/PROD с `0.11.9` | непрерывная reconciliation с остальными представлениями |
| Объяснение `why assigned` | Единый reason contract в matrix/log/CSV | SOURCE/TEST/DEV/PROD с `0.11.9` | повторное назначение и version-change decision в одном journey |
| Scoped responsible-for-training view | Реализовано по org subtree/group | SOURCE/TEST/DEV/PROD с `0.11.9` | mobile/large-org acceptance без возврата глобальных ролей |
| Content owner/review/change impact | Нет замкнутого workflow | ABSENT | определить version-change decision flow |
| Полная матрица компетенций | Карточка должности частично | PARTIAL | фактический уровень, evidence, gap отсутствуют |
| Практическая проверка навыка | Универсального flow нет | ABSENT | checklist/file/observer/commission design later |
| HR lifecycle/API/webhooks/SSO/SCIM | Import есть, lifecycle не замкнут | PARTIAL | hire/transfer/termination idempotency; integrations later |
| Tenant AI/email/storage cost dashboard | Единого продуктового dashboard нет | ABSENT | определить метрики после stage-1 telemetry readback |
| Видео и online lessons | Основного corporate flow нет | ABSENT | только интеграционный модуль при подтверждённом спросе |

## Инварианты следующей разработки

1. Tenant — граница данных компании; подразделение и филиал не являются tenant.
2. Не возвращать `teacher` и `org_admin`. Новые полномочия задавать capability
   плюс ограниченный scope.
3. История завершённой occurrence и опубликованной версии неизменяема.
4. Тест, completion и OTP не означают аттестацию, ЭЦП или допуск.
5. Любой dashboard aggregate должен иметь тот же source of truth, что training
   log и export.
6. AI создаёт draft; публикация остаётся осознанным действием методиста.
7. Малый источник не дополняется искусственными уроками или вопросами.
8. Production customer tenant не используется для экспериментальной приёмки.

## Решение этапа 0 и состояние этапа 2

Следующий продуктовый эпик после приёмки — `Corporate Readiness V1`:

1. матрица обязательного обучения;
2. объяснимое основание назначения;
3. action center с точной навигацией;
4. scoped responsibility по org subtree/group;
5. reconciliation dashboard/log/export/evidence;
6. управление актуальностью источника и повторным обучением.

Этап 1 закрыт как `PASS_WITH_FOLLOW_UP`. Срезы 2.1 и 2.2 выпущены в production
в `0.11.9`; action-center follow-up вошёл в `0.11.10`, а dashboard и
обязательный AI critical journey укреплены в `0.11.12`.

## Состояние после этапа 1

Local и isolated DEV контракты подтверждают основную корпоративную модель.
Production frontend/API синхронизированы на `v0.11.12`; новый bounded
source-to-draft human smoke завершился за 67 секунд, создал 1/3/3/7 и был
очищен с readback отсутствия. Поэтому этап 1 закрыт как
`PASS_WITH_FOLLOW_UP`. Вся corporate readiness остаётся `PARTIAL`, пока один
непрерывный сценарий не сверит dashboard, training log, export и evidence
package, а capacity не подтверждён отдельно. Текущая исполнимая работа описана
в `docs/plans/2026-09-28_corporate-readiness-stage3.md`.
