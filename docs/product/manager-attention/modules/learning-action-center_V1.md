# Центр действий методиста — V1

Статус: локальная реализация принята; миграция и RLS проверены в одноразовой
схеме Supabase DEV. Deployed browser acceptance и production-релиз не выполнены.
Этот документ сам по себе не разрешает выпуск в production.

## Результат

Методист работает с одной проверяемой цепочкой:

```text
наблюдаемая проблема
  → действие с ответственным и сроком
  → сохранённый исходный снимок
  → наблюдаемый или явно обоснованный ручной итог
  → сохранённый итоговый снимок
```

Завершение курса, оценка теста и исходные ответы не изменяются. Центр действий
только связывает существующий журнал, аналитику ответов и штатные маршруты
напоминания/повторного назначения.

## Публичные границы

- `GET /api/v1/admin/learning-actions` — текущие назначения, слабые вопросы
  выбранного курса и сохранённые действия.
- `POST /api/v1/admin/learning-actions` — создать действие для точного
  enrollment occurrence или точной редакции вопроса.
- `POST /api/v1/admin/learning-actions/{id}/close` — сохранить результат.

Доступ только активному tenant-методисту. Platform superadmin без выбранного
tenant, tenant admin, сотрудник и чужие UUID не получают данные.

## Наблюдаемые группы

Для текущего occurrence используется ровно один приоритетный сигнал:

1. `overdue`;
2. `failed_required_quiz`;
3. `stalled`;
4. `not_started`.

Завершённые, отменённые и superseded occurrences в рабочую очередь не входят.
Предыдущее назначение остаётся в истории, но не загрязняет текущий action center.

Слабый вопрос предлагается как действие только при одновременно выполненных
условиях:

- минимум 5 ответов;
- не менее 30% ошибок;
- идентичность включает course, quiz, content release и immutable question key.

Малая выборка остаётся видимой в подробной аналитике, но не становится
управленческим сигналом.

## Жизненный цикл

Типы действий: `reminder`, `reassignment`, `supplemental_material`,
`manual_review`. Первая версия сохраняет намерение и ведёт к существующему
штатному маршруту; она не отправляет письмо и не создаёт назначение скрытно.

Статусы: `open`, `completed`, `cancelled`. Для одной точной цели,
проблемы и типа действия допускается только одно открытое действие. Повторный
запрос должен завершаться конфликтом, а не дублем.

При создании сервер сам сохраняет baseline. При закрытии сервер сам сохраняет
outcome. `manual` и `cancelled` требуют текстового обоснования. События
создания и закрытия append-only; удаление истории runtime-ролью запрещено.

## Данные и безопасность

Таблицы tenant-scoped, используют RLS и FORCE RLS. Runtime `lms_app` получает
только необходимые права. Сервер проверяет, что target, course, enrollment,
owner и actor принадлежат одному tenant. Исторические quiz evidence и enrollment
не переписываются.

## Приёмка

- текущий и предыдущий occurrence одного сотрудника не смешиваются;
- малая выборка не попадает в очередь слабых вопросов;
- дубликат активного действия отклоняется;
- чужие target/owner/action возвращают 404/403 без утечки;
- закрытие сохраняет baseline и outcome, а отмена не удаляет историю;
- RU/KK/EN интерфейс показывает loading, empty, error/retry, create и close;
- существующие журнал обучения и Learning Insights проходят регрессию;
- миграция проверена upgrade/downgrade/re-upgrade в одноразовой схеме Supabase
  DEV до любого production-релиза.

## Локальная приёмка 2026-09-24

- полный API unit-набор: 2100 passed;
- профильные Learning Actions / Learning Insights / occurrence-тесты: 41 passed;
- контракт канонического API test runner: 1 passed;
- полный frontend-набор: 685 passed; typecheck, lint и production build PASS;
- Python quality baseline PASS: Ruff 1050, mypy 2221, допуски не расширялись;
- одноразовая Supabase DEV схема: upgrade/downgrade/re-upgrade, tenant-owned
  create/close, cross-tenant target/actor reject, immutable events, tenant read isolation,
  cleanup и неизменный shared migration head — PASS;
- production deploy, общая DEV/public migration и browser readback отсутствуют.
