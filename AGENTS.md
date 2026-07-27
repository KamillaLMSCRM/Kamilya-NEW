# AGENTS.md

Правила работы AI-агентов в Kamilya LMS.

## Точка входа

Сначала прочитать:

1. [`docs/CODEX_HANDOFF.md`](docs/CODEX_HANDOFF.md)
2. [`PROJECT.md`](PROJECT.md)
3. [`docs/PROJECT-CONTEXT.md`](docs/PROJECT-CONTEXT.md)
4. [`docs/PRODUCTION_READINESS.md`](docs/PRODUCTION_READINESS.md)
5. [`docs/PRODUCT_BACKLOG.md`](docs/PRODUCT_BACKLOG.md)
6. [`docs/PROJECT_INTERNAL_DOCUMENTATION.md`](docs/PROJECT_INTERNAL_DOCUMENTATION.md)
7. [`docs/LESSONS.md`](docs/LESSONS.md)

Git history содержит старые ТЗ и отчёты, но они не являются источником
текущего поведения.

## Значение команды «проверь»

Если пользователь не ограничил задачу read-only, «проверь» означает:

1. воспроизвести;
2. найти root cause;
3. исправить;
4. добавить пропорциональные тесты;
5. прогнать broader checks;
6. выпустить;
7. независимо проверить production revision и пользовательский flow.

HTTP 200 или зелёный deploy сам по себе не закрывает задачу.

## Продуктовые инварианты

- Канонические роли: `superadmin`, `admin`, `methodologist`, `student`.
- `teacher` и `org_admin` не поддерживаются.
- Tenant admin не управляет курсами, тестами, обучающимися или назначениями.
- Methodologist владеет staff import, invitations и training log.
- Active role не объединяется с capability других назначенных ролей.
- `/admin/enrollments` не возвращается как самостоятельный экран.
- У каждой функции один canonical route и один data source of truth.

## Tenant isolation

Новая tenant-scoped таблица или mutation требует:

1. `tenant_id`;
2. ownership checks входящих IDs;
3. RLS;
4. FORCE RLS;
5. runtime role без `BYPASSRLS`;
6. cross-tenant test.

Не выполнять tenant write без установленного tenant context.

## Работа с репозиторием

- Сначала `git status`, не откатывать чужие изменения.
- Предпочитать существующие паттерны и domain boundaries.
- Для структурированных данных использовать parser/API, а не string hacks.
- Комментарии добавлять только там, где код неочевиден.
- Не делать unrelated refactor.
- Миграции только additive/expand-compatible, если нет отдельного плана
  безопасного cutover.

Graphify обязателен для исследования кода как для основного агента, так и для
subagents:

1. перед чтением исходников выполнить scoped-запрос `graphify query`;
2. для связи компонентов использовать `graphify path`, для отдельного понятия
   `graphify explain`;
3. проверить вывод Graphify по реальным исходникам и тестам;
4. после изменения кода выполнить `graphify update .`;
5. если индекс отсутствует, построить локальный code-only индекс командой
   `graphify . --code-only --no-viz`.

Для поиска текста в документации использовать обычный поиск. Graphify является
индексом связей, а не источником правды. Недоступность Graphify считается
блокером исследования кода: агент должен сообщить оркестратору, а не молча
переходить к полному ручному обходу.

## План и агенты

Для работы больше одного шага создать временный
`docs/plans/YYYY-MM-DD_<slug>.md` с проверками и gate.

Дешёвые subagents разрешены для ограниченной массовой работы:

- у каждого отдельный read/write scope;
- не делегировать критический интеграционный blocker;
- агент не пушит и не деплоит;
- оркестратор проверяет diff и тесты;
- отчёт агента не является доказательством.

После завершения:

1. перенести устойчивый результат в product/internal/user docs, ADR,
   `PRODUCTION_READINESS.md` или `PRODUCT_BACKLOG.md`;
2. удалить временный план;
3. не создавать `final_report_v2` и папку старых done-планов.

История остаётся в Git.

## Тесты

Backend:

```powershell
cd apps\api
poetry run pytest
poetry run alembic heads
```

Frontend:

```powershell
cd apps\web
npm test
npm run typecheck
$env:NEXT_TELEMETRY_DISABLED='1'
npx next build
```

Тесты должны соответствовать риску:

- RBAC/RLS: negative and cross-tenant integration;
- background job: queue plus real worker smoke;
- migration: empty/current schema upgrade;
- UI: route, loading/error/empty states and responsive browser QA;
- exports/imports: real files and human-readable output.

## Production

Перед утверждением release проверить независимо:

- GitHub commit and CI;
- Vercel production commit;
- Render API commit;
- Alembic revision;
- Celery worker commit and registered tasks;
- business smoke.

Worker на отдельном VPS не обновляется автоматически вместе с Render.

## Секреты

- Локальные значения только в `.env`.
- Не печатать секреты в chat, docs, commands output или widgets.
- Не коммитить `.env`, tokens, passwords, private keys.
- Для проверки разрешено читать только имена переменных.
- Production changes выполнять только в scope запроса пользователя.

## Git и release

- Commit author email: `kamilla_lms_crm@proton.me`.
- Push выполнять токеном из `.env`, без Git Credential Manager.
- Не использовать `git reset --hard` и слепой production `git pull`.
- После push дождаться CI и provider deploys.
- Документировать только подтверждённый текущий результат.

## Документация

Текущие источники:

- `PROJECT.md`: продукт;
- `docs/PROJECT-CONTEXT.md`: текущая система;
- `docs/PRODUCTION_READINESS.md`: release gates;
- `docs/PRODUCT_BACKLOG.md`: открытые задачи;
- `docs/USER_DOCUMENTATION_RU.md`: пользовательский flow;
- `docs/adr/`: долговечные решения.

Старый audit, execution report, agent prompt или ТЗ удаляется после переноса
полезного результата в канонический документ.

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

When the user types `/graphify`, use the installed graphify skill or instructions before doing anything else.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/graph.json is absent, run `graphify . --code-only --no-viz` before exploring code. This applies to every subagent and isolated worktree.
- Dirty graphify-out/ files are expected after hooks or incremental updates; dirty graph files are not a reason to skip graphify. Only skip graphify if the task is about stale or incorrect graph output, or the user explicitly says not to use it.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
