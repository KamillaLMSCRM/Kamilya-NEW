# AGENTS.md

Правила работы AI-агентов в Kamilya LMS. Workspace `AGENTS.md` определяет общий
scope, безопасность, billing и формат взаимодействия; этот файл добавляет только
проектные инварианты и маршруты к специализированным процедурам.

## Начало задачи

1. Прочитать применимые `AGENTS.md`, установить точный scope, ожидаемый результат
   и границу полномочий.
2. Прочитать только источники, которые относятся к задаче:
   - [`PROJECT.md`](PROJECT.md) — продукт и границы функций;
   - [`ERRORS.md`](ERRORS.md) — поиск по компоненту, симптому и классу ошибки;
   - [`docs/PROJECT-CONTEXT.md`](docs/PROJECT-CONTEXT.md) — архитектура,
     окружения и доступы;
   - [`docs/PRODUCTION_READINESS.md`](docs/PRODUCTION_READINESS.md) — release и
     production gates;
   - [`docs/PRODUCT_BACKLOG.md`](docs/PRODUCT_BACKLOG.md) — открытая продуктовая
     работа;
   - [`docs/PROJECT_INTERNAL_DOCUMENTATION.md`](docs/PROJECT_INTERNAL_DOCUMENTATION.md)
     — внутренняя эксплуатация;
   - [`docs/CODEX_HANDOFF.md`](docs/CODEX_HANDOFF.md) — продолжение работы на
     этой машине.
3. Не читать весь набор ради локальной правки, точного вопроса или статуса.
   Полностью читать документ только при его аудите, широком onboarding либо когда
   задача действительно охватывает всю его ответственность.
4. Уже прочитанное перечитывать только после изменения файла, смены scope,
   потери контекста или появления существенного противоречия.

История Git, память, старые планы, handoff, screenshots, Graphify и отчёты агентов
помогают найти источник, но не являются текущей runtime/provider truth и не дают
полномочий на mutation.

## Владение правилами

- `AGENTS.md` — общие проектные инварианты и маршрутизация.
- `.codex/agents/<role>/AGENTS.md` — контракт постоянного worker.
- `.codex/skills/<skill>/SKILL.md` — специализированный повторяемый workflow.
- `ERRORS.md` — подтверждённые повторяемые ошибки и профилактика.
- `docs/adr/` — долговечные архитектурные решения.
- `docs/PRODUCTION_READINESS.md` — текущие release gates и принятые evidence.
- `docs/testing/TEST_RUN_LEDGER.md` — append-only история тестовых запусков, не
  источник полномочий или текущего runtime state.

Не создавать новый документ, если его ответственность уже принадлежит одному из
этих источников. Подробность редкого workflow хранить в его skill/runbook, а не
дублировать здесь.

## Ошибки и диагностика

При широком production/release расследовании root обязан полностью прочитать `ERRORS.md`;
для локальной задачи применяется точечный поиск, описанный ниже.

Перед анализом найти относящиеся записи в `ERRORS.md` через точные термины задачи
и прочитать найденные записи полностью. Расширять поиск только по обнаруженной
зависимости. Весь журнал нужен лишь при его аудите или широком расследовании.

Новая подтверждённая повторяемая ошибка в рамках той же задачи требует:

1. отделить наблюдаемый симптом от гипотезы;
2. подтвердить первопричину;
3. исправить минимальный слой;
4. повторить падавшую проверку и выполнить соразмерную регрессию;
5. обновить существующий ID либо добавить уникальный `CATEGORY-NNN` с датой,
   причиной, исправлением, проверкой и профилактикой;
6. удалить секреты, PII и устаревшие рекомендации.

Сначала закреплять инвариант исполняемым тестом, CI gate или проверочным script.
Текстовое правило не заменяет проверку. Один новый пример обычно становится
узкой регрессией, а не универсальным запретом для всех задач.

Для root запрос «проверь», если пользователь не ограничил его read-only,
означает: воспроизвести, диагностировать, исправить, проверить и довести до
готового релизного пакета. Выпуск и production readback входят только при текущем
явном разрешении на release. HTTP 200 или зелёный deploy не закрывают business
flow сами по себе.

## Продуктовые инварианты

- Канонические роли: `superadmin`, `admin`, `methodologist`, `student`.
- `teacher` и `org_admin` не поддерживаются.
- Tenant admin не управляет курсами, тестами, обучающимися или назначениями.
- Methodologist владеет staff import, invitations и training log.
- Active role не объединяется с capability других назначенных ролей.
- `/admin/enrollments` не является самостоятельным экраном.
- У каждой функции один canonical route и один data source of truth.

Новая tenant-scoped таблица или mutation требует `tenant_id`, ownership checks
для входящих IDs, RLS, FORCE RLS, runtime role без `BYPASSRLS` и cross-tenant
negative test. Tenant write без установленного tenant context запрещён.

## Репозиторий и код

- Сначала проверить `git status`; сохранить unrelated dirty/untracked work.
- Не выполнять reset, clean, broad stash, слепое staging или unrelated refactor.
- Использовать существующие domain boundaries и parser/API для структурированных
  данных; string hacks допустимы только как проверенное локальное преобразование.
- Миграции по умолчанию additive/expand-compatible.
- На этой машине не использовать локальный Docker PostgreSQL для Kamilya DB,
  migration или RLS-проверок. Использовать канонический Supabase DEV/test-контур.
  Docker без базы допустим для build/runtime-hardening; CI service containers не
  затрагиваются.

Перед Git, DB, provider, deployment или infrastructure действием найти
канонический путь в релевантной записи `ERRORS.md`, разделе
`docs/PROJECT-CONTEXT.md` и профильном skill/runbook. Читать только относящиеся
разделы, но не заменять их ambient CLI, browser или keyring state.

## Навигация и Graphify

Для точного файла, символа или текста использовать `rg`/`rg --files`. Для
нетривиального cross-module flow, dependency path или blast-radius анализа
использовать [Graphify skill](.codex/skills/graphify/SKILL.md), затем подтвердить
решающий вывод в исходниках и тестах. Простая правка, review инструкций или
известный однофайловый путь не требуют Graphify и обновления индекса.

После изменения связей в коде обновить AST-индекс один раз перед итоговым review.
Недоступный или устаревший индекс — навигационный пробел, а не blocker: перейти к
ограниченному чтению нужных исходников и явно отметить ограничение.

## Архитектура и планы

Для новой или изменяемой cross-module продуктовой цепочки использовать
[`docs/product/contract-modules/README.md`](docs/product/contract-modules/README.md),
активную [`AGENT_INSTRUCTION_V2.md`](docs/product/contract-modules/AGENT_INSTRUCTION_V2.md)
и ADR-0024/ADR-0025. Не создавать формальный EPIC/mini-spec для typo, локального
bugfix или изменения с очевидным однофайловым контрактом.

Временный `docs/plans/YYYY-MM-DD_<slug>.md` нужен, когда работа имеет несколько
зависимых модулей, исполнителей, сред, approval gates либо вероятно переживёт
текущую сессию. Для короткой последовательной задачи достаточно рабочего плана
в текущем контексте. После завершения устойчивые факты переносятся владельцам
документации, а временный план удаляется.

Крупный multi-agent/cross-repository epic маршрутизировать через
[kamilya-orchestrator](.codex/skills/kamilya-orchestrator/SKILL.md). Обычное
делегирование использовать только когда параллельность или независимая проверка
реально окупает передачу контекста, через
[kamilya-subagent-delegation](.codex/skills/kamilya-subagent-delegation/SKILL.md).
Root владеет критическим blocker, общими интерфейсами, интеграцией, итоговым diff,
release и production readback. Одновременно — не более двух независимых leaf
writers с непересекающимся scope.

Постоянные workers:

- Release Runner: [канонический контракт](.codex/agents/release-runner/AGENTS.md).
- Test & Evidence Runner: [канонический контракт](.codex/agents/test-runner/AGENTS.md);
  `.codex/agents/test-evidence-runner/AGENTS.md` — только compatibility redirect.

Worker packet и handoff не дублируются здесь. `READY FOR ROOT REVIEW` не является
project GO; root проверяет результат и принимает решение.

## Тестирование и завершение

Выбирать минимальную матрицу, которая доказывает риск:

1. во время реализации — focused unit/module tests;
2. после изменения interface — contract tests и затронутые соседи;
3. после сборки cross-module цепочки — integration/critical journey;
4. перед release — один полный suite по риску плюс обязательные
   migration/security/runtime gates.

Не запускать полный suite после каждой локальной правки и не повторять зелёные
проверки без нового delta, среды или риска. Нельзя выпускать цепочку только по
узким тестам.

Дополнительные риски:

- RBAC/RLS — negative и cross-tenant integration;
- background jobs — queue плюс реальный worker smoke;
- migration — empty/current schema upgrade и cleanup;
- UI — loading/error/empty states и responsive browser QA;
- import/export — реальный файл и человекочитаемый результат.

Machine-readable critical journeys живут в `docs/critical-journeys/`. Для
затронутого journey прочитать его контракт, проследить изменённый путь, выполнить
указанные gates и сохранить observable invariants либо отдельно согласовать их
изменение. `AI-COURSE-01` покрывает document-to-course pipeline. Для AI-качества
сначала воспроизводить точный provider output детерминированным replay-тестом;
полная генерация DEV/production — финальная приёмка неизменённого кандидата, а не
цикл отладки каждого нового текстового примера.

Завершение означает реализованный результат, пропорциональную проверку, review
итогового diff, cleanup временных артефактов и честно названные непройденные
внешние gates. Не останавливаться на первом implementation pass, если проверка и
безопасное исправление входят в поставленную задачу.

## Production, доступы и секреты

Production release маршрутизировать через:

- [release evidence gate](.codex/skills/kamilya-release-evidence-gate/SKILL.md);
- [KZ backend deploy](.codex/skills/kamilya-production-deploy/SKILL.md);
- [safe remote execution](.codex/skills/kamilya-safe-remote-exec/SKILL.md) для
  VM126 scripts;
- [`docs/PRODUCTION_FRONTEND_RUNBOOK.md`](docs/PRODUCTION_FRONTEND_RUNBOOK.md)
  для CT137 frontend.

Перед внешней операцией читать только раздел целевого окружения в
[`docs/PROJECT-CONTEXT.md`](docs/PROJECT-CONTEXT.md) и, когда нужен guest/SSH,
[`docs/VPS_CONNECTION_GUIDE.md`](docs/VPS_CONNECTION_GUIDE.md). Эти источники
владеют текущей топологией; не копировать её сюда и не использовать старый plan
или handoff как endpoint/credential truth.

Ключевые неизменные границы:

- public proxy — только Nginx/TLS, WireGuard hub и SSH transit; без checkout,
  Node.js, application runtime или базы;
- VM126 — production API/workers/Valkey/file runtime;
- CT125 — PostgreSQL 17, pgvector и backup; PostgreSQL не публикуется в Internet;
- CT137 — native production frontend и public landing;
- Render/Supabase/Vercel используются только в роли, указанной актуальной картой
  окружений, и не подменяют KZ production evidence.

Секреты разрешено загружать только process-locally из канонического `.env` для
точно разрешённой операции. Нельзя выводить или сохранять значения, передавать их
в URL/аргументах, коммитить, искать в старых `.env` или использовать credentials
соседнего проекта. Skills, memory, agents, планы и наличие доступа не дают
полномочий на mutation.

После двух материально одинаковых access/auth/network failures worker прекращает
повторы и возвращает root точный target, попытки, классы ошибок, требуемую границу
доступа и безопасное состояние. Root не перебирает credentials или новые каналы,
а выбирает другой безопасный метод только внутри исходного scope и authority.

## Git, версии и release

- Каноническая версия — `VERSION`; `apps/api/pyproject.toml` и
  `apps/web/package.json` должны совпадать. Проверка:
  `python scripts/validate_version.py`.
- Пользовательски заметные изменения записываются в `[Unreleased]`
  `CHANGELOG.md`. Release требует dated changelog, `docs/releases/vX.Y.Z.md`,
  тега, опубликованного GitHub Release и exact-SHA runtime readback.
- Exact author: `Kamilya Codex <kamilla_lms_crm@proton.me>`; canonical GitHub
  account: `KamillaLMSCRM`.
- Использовать только repository-root `GITHUB_TOKEN` через process-local
  `gh auth git-credential`; plain `git push`, чужая keyring-сессия или custom
  `GIT_ASKPASS` не являются каноническим credential path.
- Перед push из `apps/api`:
  `poetry run dotenv -f ..\..\.env run -- gh auth status --hostname github.com`.
- Push:
  `poetry run dotenv -f ..\..\.env run -- git -c credential.helper= -c "credential.helper=!gh auth git-credential" -C ..\.. push origin <exact-sha>:<branch>`.
- После push независимо прочитать remote branch SHA и сохранить sanitized
  repository/branch/local SHA/remote SHA/account/credential-path/timestamp
  evidence. Никогда не сохранять token value.

Только root утверждает GO/NO_GO, меняет `VERSION`, создаёт release/tag и принимает
production readback. Release Runner может выполнить только точный уже разрешённый
packet и не вправе расширять его.

## Документация

Текущие владельцы:

- `PROJECT.md` — продукт;
- `docs/PROJECT-CONTEXT.md` — система и окружения;
- `docs/PRODUCTION_READINESS.md` — release gates;
- `docs/PRODUCT_BACKLOG.md` — открытая работа;
- `docs/USER_DOCUMENTATION_RU.md` — пользовательский flow;
- `docs/adr/` — долговечные решения.

После переноса полезного результата удалять устаревший execution report, agent
prompt или ТЗ. История остаётся в Git; не создавать `final_report_v2` и параллельные
источники истины.
