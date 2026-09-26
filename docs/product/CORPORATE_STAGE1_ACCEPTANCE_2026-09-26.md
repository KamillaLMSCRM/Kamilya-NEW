# Corporate Stage 1 Acceptance

Дата: 2026-09-26  
Source snapshot: `94d064ae59ed50bb51fa4f78870e2e77fa037fd5`

Фактический результат:
[`CORPORATE_STAGE1_RESULT_2026-09-26.md`](CORPORATE_STAGE1_RESULT_2026-09-26.md).

## Цель

Проверить текущую Kamilya как систему внутрикорпоративного обучения до начала
следующего продуктового эпика. Результат каждого пункта — `PASS`, `FAIL`,
`BLOCKED` или `NOT VERIFIED` с наблюдаемым доказательством.

## Контуры

| Архетип | Контур | Объём | Основной риск |
|---|---|---:|---|
| A. Небольшая компания | существующий production synthetic tenant | 50–100 сотрудников в модели, малый реальный UI-срез | понятность полного человеческого пути |
| B. Компания с филиалами | local contracts + isolated Supabase DEV | 1 000 сотрудников, 4 уровня иерархии | scope, дедупликация, массовые операции |
| C. Регулируемая компания | local contracts + isolated Supabase DEV | несколько тысяч модельных строк, малый фактический evidence workflow | версии, repeat, confirmation, signed scan, retention |

Числа B/C — acceptance-профили, а не заявленный SLA. Отдельный capacity report
нужен до публичного обещания конкретной одновременной нагрузки.

## Общий маршрут

1. Создать или восстановить точное синтетическое исходное состояние.
2. Настроить организационную структуру и должности.
3. Выполнить import preview/commit и повторить тот же import.
4. Загрузить PDF/XLSX, дождаться conversion/index и проверить progress.
5. Создать draft Evidence V2, просмотреть уроки и тесты, опубликовать release.
6. Создать группу/программу и ручное/правиловое назначение.
7. Войти обучающимся, сохранить progress, провалить и повторить тест, завершить.
8. Получить сертификат/подтверждение, загрузить подписанный экземпляр.
9. Проверить methodologist review, training log, export и evidence package.
10. Назначить тот же курс повторно и доказать сохранение первой истории.
11. Проверить новую версию источника/курса без изменения старого evidence.
12. Проверить перевод/увольнение сотрудника и неизменность истории.
13. Выполнить точный cleanup disposable data и readback нулевого residue.

## Hard gates

- Нет записи или чтения другого tenant.
- Нет клиентских production writes.
- Dashboard, training log и export согласованы по occurrence/enrollment.
- Повторный import/assignment не создаёт дубли.
- Прошлая completion/attempt/evidence история не перезаписывается.
- Нельзя завершить курс прямым вызовом без требуемого progress/test.
- Нельзя создать admission/attestation generic completion-вызовом.
- Ошибка AI/email/worker имеет видимое состояние и безопасный retry/fallback.
- После cleanup нет disposable tenant rows, storage objects или queued jobs.
- Секреты, PII и тела писем не попадают в отчёт.

## Матрица проверок

| Проверка | A | B | C |
|---|:---:|:---:|:---:|
| Login/impersonation/active role | UI | contract | contract |
| Organization hierarchy | UI small | 4-level DEV | 4-level DEV |
| Staff import idempotency | UI small | 1k fixture | regulated fixture |
| Document/index progress | UI | provider-degraded contract | scan/legal source contract |
| Course/test quality | human review | deterministic corpus | deterministic corpus |
| Assignment reason/dedup | UI/API | DEV | DEV |
| Learner fail/retry/pass | UI | contract | contract |
| Repeat occurrence/history | UI/API | DEV | DEV |
| Signed scan review | UI/API | contract | DEV |
| Training log/export/evidence | UI/API | DEV | DEV |
| Tenant/RLS negatives | API | DEV | DEV |
| Cleanup/readback | exact IDs | disposable schema | disposable schema |

## UX-проверка архетипа A

На каждом экране фиксируются:

- видимый следующий шаг;
- понятность языка без знания внутренней архитектуры;
- loading/empty/error/success/retry state;
- mobile 390 px и desktop 1024/1440 px;
- клавиатурная навигация для основного действия;
- отсутствие горизонтального overflow;
- сохранение superadmin preview context;
- совпадение названия действия с фактическим результатом.

## Выходные артефакты

1. Заполненная capability map с текущими PASS/FAIL.
2. Sanitized timing ledger по каждому этапу.
3. Reconciliation report dashboard/log/export/evidence.
4. Список дефектов с severity и воспроизводимым маршрутом.
5. Cleanup report.
6. Отдельное наблюдение context/token efficiency.

FAIL не исправляется молча в рамках этой приёмки. Сначала фиксируется исходный
RED и его граница; исправление выполняется отдельным минимальным изменением и
тот же сценарий повторяется.
