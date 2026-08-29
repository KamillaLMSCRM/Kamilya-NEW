# Система управления разработкой проекта с AI-агентами

Практическая переносимая инструкция на примере подхода, применённого в Kamilya LMS,
с отдельными идеями, вдохновлёнными Hermes Agent.

Версия: 1.0  
Дата: 2026-08-23  
Статус: пример архитектуры управления, а не обязательный стандарт для каждого проекта

Практическое дополнение: [Защита работающих блоков и критических пользовательских сценариев](agent-critical-journey-protection-guide-ru.md).

Практическое дополнение: [Версионирование продукта в проектах с AI-агентами](agent-product-versioning-guide-ru.md).

---

## 1. Для чего нужна такая система

AI-агент может быстро читать код, редактировать файлы, запускать тесты, работать с
Git, браузером, облачными провайдерами и инфраструктурой. Но без явной системы
управления эта скорость создаёт типовые проблемы:

- агент выбирает не тот проект или окружение;
- старый чат принимается за текущее состояние;
- план или документация подменяют runtime evidence;
- один агент перезаписывает работу другого;
- секреты попадают в команды, логи или отчёты;
- успешный HTTP-ответ принимается за доказательство корректного release;
- повторяемые ошибки исправляются заново, но не превращаются в правила и тесты;
- длинные инструкции загружаются всегда и расходуют контекст;
- автономная задача продолжает работать после утраты практической ценности;
- локальная нехватка доступа ошибочно трактуется как отсутствие объекта в production.

Цель системы — не ограничить агента максимальным числом запретов, а дать ему
понятную модель проекта:

1. где находится действующая правда;
2. что агент может делать самостоятельно;
3. какие действия требуют отдельного разрешения;
4. как доказывается результат;
5. как делегируется работа;
6. как подтверждённый опыт становится тестом, правилом или skill;
7. как удалить временную координацию после завершения работы.

Подход можно применять частично. Небольшому локальному проекту может быть достаточно
`AGENTS.md`, `PROJECT.md`, `ERRORS.md` и тестов. Сложному продукту с production,
несколькими репозиториями и внешними провайдерами полезна полная система.

---

## 2. Основная идея: не один большой файл, а несколько слоёв

Один гигантский `AGENTS.md` быстро становится неудобным. В нём смешиваются правила,
текущее состояние, история, backlog, инструкции по deployment и разовые планы.
Лучше разделить информацию по сроку жизни и назначению.

| Слой | Что хранит | Пример |
|---|---|---|
| Поведение агента | Границы, приоритеты, обязательные проверки | `AGENTS.md` |
| Продукт | Назначение, роли, инварианты, границы функций | `PROJECT.md` |
| Текущая система | Архитектура, окружения, topology, access map | `docs/PROJECT-CONTEXT.md` |
| Готовность | Release gates и подтверждённые evidence | `docs/PRODUCTION_READINESS.md` |
| Открытая работа | Product/technical backlog | `docs/PRODUCT_BACKLOG.md` |
| Решения | Почему принято устойчивое архитектурное решение | `docs/adr/` |
| Ошибки | Подтверждённые причины, исправления и профилактика | `ERRORS.md` |
| Продолжение работы | Короткий handoff следующему оператору | `docs/CODEX_HANDOFF.md` |
| Временная координация | Узлы эпика, зависимости, owners и gates | `docs/plans/` |
| Повторяемые процедуры | Узкие загружаемые по необходимости workflows | `.codex/skills/` |
| Инструменты агента | Pinned tool packages и способы запуска | `.codex/tooling/` |
| Исполняемые гарантии | Тесты, CI gates, linters, scripts | `tests/`, `scripts/`, CI |
| Навигация по коду | Архитектурный граф и impact analysis | `graphify-out/` или аналог |

Главный принцип: каждый факт имеет один наиболее подходящий источник истины.
История остаётся в Git, а не в папках `old`, `final-v2` или `done-plans`.

---

## 3. Пример структуры проекта

```text
project/
|-- AGENTS.md
|-- PROJECT.md
|-- ERRORS.md
|-- README.md
|-- .env.example
|-- .gitignore
|-- .codex/
|   |-- skills/
|   |   |-- release-evidence/
|   |   |   `-- SKILL.md
|   |   `-- project-orchestrator/
|   |       `-- SKILL.md
|   `-- tooling/
|       |-- requirements.txt
|       `-- TOOLS.md
|-- docs/
|   |-- PROJECT-CONTEXT.md
|   |-- PRODUCTION_READINESS.md
|   |-- PRODUCT_BACKLOG.md
|   |-- PROJECT_INTERNAL_DOCUMENTATION.md
|   |-- CODEX_HANDOFF.md
|   |-- adr/
|   |   `-- 0001-example-decision.md
|   `-- plans/
|       `-- 2026-08-23_current-epic.md
|-- scripts/
|   |-- ci/
|   |-- ops/
|   `-- tests/
|-- tests/
`-- graphify-out/
```

Названия можно менять. Важно не название, а разделение обязанностей.

---

## 4. Иерархия правил и разрешений

Разные агенты по-разному обрабатывают инструкции, поэтому точную семантику нужно
проверить в документации используемого инструмента. Как переносимая модель может
работать следующий порядок:

1. Системные ограничения платформы и безопасности.
2. Текущая явная инструкция владельца в допустимых границах.
3. Workspace-level `AGENTS.md`, определяющий разрешённые проекты и общие правила.
4. Repository-level `AGENTS.md`.
5. Более узкий `AGENTS.md` в подкаталоге, если инструмент поддерживает наследование.
6. Канонический документ соответствующего домена.
7. Текущий временный task graph или план.
8. Исторический handoff, session summary или memory.

Историческая информация помогает найти evidence, но не должна самостоятельно
разрешать mutation или доказывать текущее состояние.

### Важное различие

- **Контекст** говорит агенту, где искать.
- **Evidence** доказывает конкретный факт.
- **Authority** определяет, что можно изменить.
- **Approval** разрешает конкретное действие.

Эти четыре понятия не следует объединять.

---

## 5. `AGENTS.md`: договор поведения агента

`AGENTS.md` лучше использовать как короткий операционный контракт, а не как полную
документацию проекта.

### Что обычно полезно закрепить

- workspace и repository scope;
- запрещённые соседние проекты;
- порядок чтения канонических документов;
- роли и продуктовые инварианты;
- правила Git и dirty worktree;
- secret/PII boundary;
- правила миграций и tenant isolation;
- минимальные тесты по классам изменений;
- Graphify или другой архитектурный индекс;
- правила делегирования и один writer на scope;
- правила deployment и exact revision readback;
- язык внутренней коммуникации агентов;
- evidence labels;
- approval gates;
- порядок обновления `ERRORS.md`;
- правила persistent memory, skills и automations.

### Что лучше не хранить в `AGENTS.md`

- текущий deployed SHA;
- временный статус конкретного эпика;
- длинные команды одного разового incident;
- полный backlog;
- подробную историю изменений;
- raw logs;
- secrets и значения `.env`;
- большие справочники API;
- правила, уже надёжно обеспеченные кодом и не требующие объяснения агенту.

### Минимальный шаблон

```markdown
# Project agent rules

## Scope
- Default repository: `<absolute or repo-relative target>`.
- Do not enter adjacent repositories unless explicitly requested.

## Canonical sources
1. `ERRORS.md`
2. `PROJECT.md`
3. `docs/PROJECT-CONTEXT.md`
4. `docs/PRODUCTION_READINESS.md`
5. `docs/PRODUCT_BACKLOG.md`

## Authority
- Read-only inspection is the default for external systems.
- File edits, database writes, deployment, spend and destructive actions use
  separate approval rules proportional to risk.

## Git
- Inspect status first.
- Preserve unrelated changes.
- Never use destructive reset as an automatic fallback.

## Secrets and data
- Values stay in approved secret stores or `.env`.
- Never print credentials, raw PII or payloads.

## Verification
- Match tests to the changed boundary.
- Provider success is not runtime proof.
- Report exact revision and observable result.

## Learning
- Confirmed recurring failures go to `ERRORS.md`.
- Deterministic prevention should become a test, CI gate or script.
- New skills and memory changes require review before activation.
```

Такой шаблон стоит адаптировать. Например, локальной библиотеке не нужны production
approval gates, а multi-tenant SaaS потребует более строгих DB/RLS правил.

---

## 6. Канонические документы и их границы

### `PROJECT.md`

Хранит устойчивое описание продукта:

- целевую аудиторию;
- поддерживаемые роли;
- ключевые user journeys;
- domain boundaries;
- функциональные ограничения;
- то, чем продукт сознательно не является.

Он не должен регулярно меняться из-за deployment или incident.

### `docs/PROJECT-CONTEXT.md`

Хранит текущее техническое устройство:

- сервисы и их ответственность;
- окружения;
- базы данных;
- storage и queues;
- topology;
- канонические access paths;
- внешних провайдеров;
- различие dev, staging, production и rollback.

Этот файл изменяется чаще `PROJECT.md`, но реже временного плана.

### `docs/PRODUCTION_READINESS.md`

Хранит проверяемые release gates:

- exact commit;
- CI run и конкретные jobs;
- deployment identity;
- migration revision;
- worker revision;
- backup/restore evidence;
- security gates;
- business smoke;
- известные незакрытые условия.

Здесь важны точные evidence pointers, а не длинные повествовательные отчёты.

### `docs/PRODUCT_BACKLOG.md`

Хранит открытые задачи продукта. Полезно отделять:

- подтверждённую проблему;
- предлагаемое решение;
- приоритет;
- dependency;
- критерий готовности;
- то, что сознательно отложено.

Backlog не является обещанием реализации и не доказывает текущее поведение.

### `docs/adr/`

ADR фиксирует устойчивое решение и его причины:

- контекст;
- принятое решение;
- рассмотренные альтернативы;
- последствия;
- условия пересмотра.

ADR полезен, когда будущий агент иначе может «улучшить» систему, вернув уже
отклонённую альтернативу.

### `docs/CODEX_HANDOFF.md`

Handoff помогает продолжить работу:

- где остановились;
- что подтверждено;
- что не проверено;
- текущий frontier;
- безопасное следующее действие;
- точные approval gates;
- временные artifacts, требующие cleanup.

Handoff должен быть компактным. Он не заменяет канонические документы и runtime
readback.

---

## 7. `ERRORS.md`: не журнал всех неудачных команд, а база подтверждённого опыта

`ERRORS.md` — один из наиболее полезных элементов системы. Его задача — не хранить
каждый traceback, а предотвращать повторение подтверждённых причин.

### Когда добавлять запись

Запись оправдана, если:

- симптом воспроизведён;
- причина подтверждена;
- выполнено исправление или определён безопасный interim path;
- исходная проверка повторена;
- сформулирована профилактика;
- проблема может повториться у другого агента.

Одиночная опечатка без системной причины обычно не требует записи.

### Формат записи

```markdown
## TOOL-001 - Short stable title

- Date: 2026-08-23.
- Symptom: exact observable failure.
- Cause: confirmed cause, separate from hypothesis.
- Fix: minimum effective correction.
- Verification: original check plus proportional regression.
- Status: resolved, pending, or exact blocker.
- Prevention: concrete action before repeating the risky procedure.
```

### Почему стабильный ID полезен

- на него можно ссылаться из `AGENTS.md`, теста или task graph;
- повтор той же причины обновляет существующую запись;
- CI может проверять структуру журнала;
- skill может требовать перечитать конкретные категории;
- история изменения правила остаётся в Git.

### Чего не должно быть в журнале

- секретов;
- connection strings;
- raw PII;
- полных логов;
- неподтверждённых причин, представленных как факт;
- устаревших рекомендаций «на всякий случай»;
- дублей одного root cause.

---

## 8. Evidence-модель

Формальная evidence taxonomy особенно полезна в проектах с production и внешними
провайдерами. Один из возможных вариантов:

| Label | Значение |
|---|---|
| `GIT-DERIVED` | Checkout, commit, diff, ancestry, Git-object reachability |
| `RUNTIME-DERIVED` | Прямое наблюдение приложения, БД, worker, network или UI |
| `OWNER-CONFIRMED` | Явное текущее указание или фактическое подтверждение владельца |
| `PROVIDER-CONFIRMED` | CI, deployment или persisted readback внешнего провайдера |
| `GRAPH-DERIVED` | Навигация или связь, найденная архитектурным графом |
| `INFERRED` | Обоснованный, но не наблюдавшийся напрямую вывод |
| `NOT VERIFIED` | Evidence отсутствует, устарело или недоступно |
| `BLOCKED` | Названное условие не позволяет закрыть exit gate |

Не каждому проекту нужны восемь labels. Для небольшой команды может быть достаточно
`VERIFIED`, `INFERRED`, `NOT VERIFIED`, `BLOCKED`. Важно, чтобы labels имели точные
значения и не смешивали source, provider и runtime.

### Пример разделения слоёв

- Код содержит health endpoint — это intended source behavior.
- CI проверил endpoint в конкретном commit — это CI/provider evidence.
- Cloud provider развернул commit — это deployment provider evidence.
- Публичный endpoint вернул exact SHA — это runtime evidence.
- Бизнес-действие завершилось и результат прочитан обратно — это business runtime
  evidence.

Один слой не следует автоматически усиливать до другого.

---

## 9. Обычный цикл работы агента

### Шаг 1. Установить scope

- определить repository и target environment;
- проверить workspace/repository rules;
- зафиксировать branch, HEAD, upstream и dirty state;
- не трогать соседние проекты и unrelated изменения.

### Шаг 2. Прочитать канонический минимум

- `AGENTS.md`;
- релевантные записи `ERRORS.md`;
- продуктовый и системный контекст;
- текущий plan/task graph, если он существует.

### Шаг 3. Сначала навигация, затем широкое чтение

- архитектурный graph query;
- поиск точного symbol/path;
- чтение минимального набора source/tests/migrations;
- подтверждение graph findings в реальных файлах.

### Шаг 4. Определить изменяемые файлы и ownership

- один writer на файл, каталог или внешний mutation scope;
- reviewers работают read-only;
- независимые задачи можно делегировать параллельно;
- критический integration blocker остаётся у root agent.

### Шаг 5. Изменить минимальный слой

- не выполнять unrelated refactor;
- использовать структурированный parser/API вместо string hacks;
- применять patch так, чтобы не перезаписать чужие изменения;
- не ослаблять тест только ради зелёного результата.

### Шаг 6. Проверить пропорционально риску

- parser/formatter — focused unit test;
- API mutation — реальный verb и data boundary;
- tenant/RLS — negative и cross-tenant test;
- worker — queue, worker execution и side-effect readback;
- migration — upgrade и runtime privileges;
- UI — loading/error/empty/responsive flow;
- release — exact SHA, providers, DB revision, workers и business smoke.

### Шаг 7. Зафиксировать новое устойчивое знание

- повторяемая подтверждённая ошибка — `ERRORS.md`;
- детерминированный инвариант — test/CI/script;
- архитектурное решение — ADR;
- универсальная граница — `AGENTS.md`;
- специализированная процедура — skill;
- открытая продуктовая работа — backlog.

### Шаг 8. Завершить временную координацию

- перенести долговечные факты в канонические документы;
- удалить временный task graph после полного завершения;
- оставить историю в Git;
- сообщить exact result, evidence, residual risk и следующий gate.

---

## 10. Graph engineering

Архитектурный граф полезен как индекс связей, особенно в больших codebase.

### Практический порядок

1. `query` — найти относящиеся к вопросу symbols и communities.
2. `path` — проверить предполагаемый путь между компонентами.
3. `explain` — получить локальный контекст отдельного понятия.
4. Прочитать только найденные source и tests.
5. Проверить вывод по migrations, CI и runtime, если вопрос относится к ним.
6. После code change обновить graph index.

### Что graph не доказывает

- текущий deployment;
- активную migration revision;
- provider configuration;
- наличие runtime role;
- фактическую tenant isolation;
- успешность business flow;
- актуальный status task graph.

Graph — ускоритель навигации, а не источник runtime truth.

### Freshness

Полезно хранить рядом с индексом metadata:

- built commit;
- timestamp;
- exclusions;
- parser gaps;
- extraction warnings;
- покрытие migrations или других критических типов файлов.

Если provenance индекса неизвестен, вывод остаётся `GRAPH-DERIVED` или
`NOT VERIFIED`.

---

## 11. Делегирование subagents

Subagents полезны не потому, что «больше агентов всегда быстрее», а когда работу
можно безопасно разделить.

### Хорошие задачи для делегирования

- независимая инвентаризация;
- варианты текста;
- сравнение документации;
- focused source review;
- проверка отдельного test scope;
- оппонентский review готового artifact;
- массовая однотипная низкорисковая работа.

### Плохие задачи для делегирования

- критический blocker, без которого root не может продолжить;
- два writers на один файл;
- production mutation без отдельного owner/gate;
- работа, требующая передачи большого набора secrets;
- расплывчатое «разберись во всём проекте»;
- повторение уже выполненного root-анализа.

### Контракт поручения

Каждое поручение желательно описывать так:

```text
Objective:
Scope:
Allowed reads:
Allowed writes:
Forbidden actions:
Expected evidence:
Exit gate:
Language and report format:
```

### One-writer rule

- один агент владеет writable path;
- второй агент может быть reviewer, но не редактирует тот же файл;
- root проверяет artifact, diff и тесты;
- отчёт subagent не является достаточным evidence;
- subagent не push/deploy, если это специально не передано отдельным процессом.

### Выбор модели

Недорогие модели подходят для bounded low-risk work. Более сильная модель полезна
для архитектурного решения, security boundary или интеграционного blocker. Это
экономическая рекомендация, а не жёсткое правило: сложность задачи важнее названия
модели.

---

## 12. Управляемое самообучение в стиле Hermes Agent

Hermes Agent интересен тем, что разделяет persistent facts, session history и
procedural skills. В официальной документации Hermes:

- `MEMORY.md` и `USER.md` используются для persistent factual/user memory;
- `AGENTS.md` и другие context files задают project instructions;
- skills содержат процедурное знание и загружаются по необходимости;
- session search ищет фактические сообщения прошлых сессий;
- skills могут создаваться и улучшаться на основании опыта.

Полезная идея здесь не в буквальном копировании автономности, а в замкнутом цикле
обучения на уровне управляемых artifacts.

### Безопасный цикл курации знаний

```text
Наблюдение
  -> независимая проверка
  -> подтверждённый root cause
  -> ERRORS.md со stable ID
  -> test / CI gate / deterministic script
  -> при необходимости AGENTS.md / ADR / SKILL.md
  -> review diff и authority
  -> явная активация
  -> проверка на следующем реальном применении
  -> обновление или удаление устаревшего знания
```

### Почему сначала test или script

Текстовая инструкция может быть забыта, неверно интерпретирована или вытеснена из
контекста. Исполняемая проверка даёт наблюдаемый pass/fail. Поэтому правило вида
«не допускай две Alembic heads» лучше закрепить CI gate, а skill оставить для
процедуры диагностики и безопасного исправления.

### Candidate artifact должен быть инертным

Сгенерированный skill, script, prompt, automation или routing rule не должен
автоматически получать:

- credentials;
- network access;
- production authority;
- hooks или scheduler activation;
- право менять собственные ограничения;
- право выполнять mutation.

До активации reviewer проверяет scope, inputs, outputs, side effects, secrets,
stop condition и rollback.

### Memory и skills — не одно и то же

| Тип | Подходящее содержимое | Не следует хранить |
|---|---|---|
| Memory | Короткие устойчивые факты и предпочтения | Secrets, raw PII, текущий volatile status |
| Skill | Повторяемая процедура и её safety gates | Огромную энциклопедию проекта |
| Session history | Исторические сообщения и evidence pointers | Автоматическую текущую правду |
| `AGENTS.md` | Универсальные project rules | Разовые incident details |
| `ERRORS.md` | Подтверждённые причины и профилактику | Каждую неудачную команду |

### Retrieval не является verification

Найденный старый SHA, provider report или DB aggregate полезен как pointer. Для
изменчивого факта нужен свежий readback. Если доступ отсутствует, корректный статус
— `NOT VERIFIED` или `BLOCKED`, а не «объекта нет».

### Почему этот подход пока встречается не везде

Многие проекты уже имеют `README`, CI и coding conventions, но не связывают их в
один learning loop. Часто отсутствуют:

- стабильный error ledger;
- правило promotion из incident в test/skill;
- разделение memory и procedural skills;
- review gate для generated agent artifacts;
- lifecycle удаления устаревших skills;
- связь между agent instructions и исполняемыми проверками.

Именно эта связка даёт наибольшую практическую ценность.

---

## 13. Как проектировать skill

Skill имеет смысл, когда процедура:

- повторяется;
- достаточно специализирована;
- требует неочевидного порядка действий;
- имеет safety или evidence boundary;
- слишком велика для постоянной загрузки в `AGENTS.md`;
- не может быть полностью заменена одним deterministic script.

### Минимальная структура

```text
.codex/skills/release-evidence/
|-- SKILL.md
|-- references/       # только если нужны большие conditional details
`-- scripts/          # только для повторяемой deterministic mechanics
```

### Минимальный `SKILL.md`

```markdown
---
name: release-evidence
description: Verify exact release and deployment evidence without mutation. Use for
  release reconciliation; do not use to deploy or approve remediation.
---

# Release evidence

## Preconditions
...

## Workflow
...

## Secret boundary
...

## Mutation boundary
...

## Output contract
...
```

### Skill review checklist

- description достаточно узкая;
- нет скрытого scope expansion;
- inputs и outputs определены;
- mutation boundary явная;
- secrets/PII не сохраняются;
- historical context не объявляется runtime truth;
- approval gate описывает точную операцию;
- ссылки ведут на канонические документы;
- placeholders удалены;
- skill прошёл validator;
- независимый realistic forward-test не выявил обход границ.

---

## 14. Tool dependencies агента

Agent tooling не следует смешивать с application dependencies.

### Рекомендуемый гибрид

1. Machine-readable manifest хранит желаемые pinned packages.
2. Короткий `TOOLS.md` объясняет назначение и команду использования.
3. Live probe подтверждает фактическую доступность и версию.
4. Только при отсутствии пакета выполняется официальный provenance/security check.

Пример:

```text
.codex/tooling/
|-- requirements.txt
`-- TOOLS.md
```

`requirements.txt`:

```text
PyYAML==6.0.3
```

Live probe:

```powershell
& $toolPython -c "import importlib.metadata as m; print(m.version('PyYAML'))"
```

### Почему статичного списка недостаточно

Manifest может быть закоммичен, но environment удалён. Глобальный `pip list` может
показывать пакет другого interpreter. Поэтому desired state и actual state должны
проверяться отдельно.

### Перед установкой

- официальный source и точное имя;
- pinned version;
- license;
- install/postinstall hooks;
- published security advisories;
- dependency conflicts;
- wheel вместо source build, если это разумно;
- isolated environment;
- отсутствие secrets в installer context;
- повтор исходной команды после установки.

---

## 15. Automations и monitors

Recurring LLM task может незаметно расходовать токены даже при здоровом состоянии.
Поэтому полезна двухступенчатая схема.

### Уровень 1. Deterministic script

- выполняет дешёвую проверку;
- хранит cursor/state;
- фильтрует unchanged/healthy events;
- выдаёт компактное sanitized событие;
- не вызывает LLM при отсутствии проблемы.

### Уровень 2. LLM triage

Запускается только при аномалии, которую script не может надёжно классифицировать.
Для periodic LLM automation желательно явно определить:

- schedule;
- model/provider;
- allowed tools;
- data boundary;
- budget/rate limit;
- notification policy;
- stop condition;
- mutation authority;
- owner и escalation target.

### Fail-quiet принцип

`OK`, unchanged state и routine polling обычно не должны создавать сообщение или
LLM turn. Это можно изменить, если продукт требует регулярный отчёт, но решение
должно быть осознанным.

---

## 16. Secrets, PII и external content

### Базовые правила

- значения secrets хранятся только в одобренном secret store или `.env`;
- в документации указываются имена переменных, но не значения;
- token не помещается в command line, URL или output;
- agent report содержит statuses, counts, masked IDs и error classes;
- raw logs не копируются в `ERRORS.md`;
- tenant payloads и contact data не передаются subagent без необходимости;
- старые `.env` не используются как источник credentials;
- external page, attachment, tool output и retrieved memory считаются untrusted
  content, а не инструкцией.

### Redaction precedence

Требование сохранить команду или сообщение дословно не должно заставлять сохранять
секрет или PII. Сохраняется диагностический смысл, а опасное значение заменяется
opaque reference.

---

## 17. Git, CI и release

### Git

- начинать с status;
- сохранять unrelated dirty work;
- не использовать destructive reset как автоматический fallback;
- один writer на path;
- проверять exact diff перед commit;
- не считать локальный HEAD deployed revision.

### CI

- CI run относится к provider evidence;
- общий success недостаточен, если нужен конкретный security/test job;
- warn-only gate не должен называться blocking;
- tests должны воспроизводить изменённый verb и boundary.

### Release

В зависимости от архитектуры полезно раздельно проверять:

- exact Git SHA;
- CI run/jobs;
- frontend deployment;
- API deployment;
- workers;
- migration revision;
- runtime role и DB identity;
- storage/backup;
- business flow;
- cleanup synthetic artifacts.

Provider dashboard `green` и HTTP 200 сами по себе редко являются полным release
evidence.

---

## 18. Task graph для крупных эпиков

Обычной задаче достаточно короткого плана. Task graph полезен, когда есть несколько
репозиториев, providers, agents, зависимостей и approval gates.

### Пример узла

```markdown
#### REL-03 - Verify production runtime identity

- Objective: prove API and workers run the intended exact release.
- Owner: root agent.
- Scope: public health plus read-only runtime metadata.
- Dependencies: REL-01, REL-02.
- State: IN PROGRESS.
- Exit gate: API and every worker match exact approved SHA and environment.
- Evidence: exact safe pointers with permitted labels.
- Approval gate: none for authorized read-only inspection.
- Cleanup: no artifacts expected.
```

### Состояния

- `PENDING` — dependency ещё не закрыта;
- `IN PROGRESS` — есть active owner;
- `DONE` — exit gate подтверждён evidence;
- `BLOCKED` — названо точное препятствие;
- `NO-GO` — итоговый gate не закрыт.

Checkbox в старом плане не должен подменять актуальный evidence readback.

### После завершения

- устойчивые факты переносятся в канонические документы;
- временный graph удаляется;
- Git сохраняет историю;
- не создаются `final-report-v2-final` и архивы завершённых планов.

---

## 19. Поэтапное внедрение

### Уровень 1. Минимум

- `AGENTS.md`;
- `PROJECT.md`;
- `ERRORS.md`;
- Git rules;
- базовые тесты.

Подходит небольшому проекту с одним репозиторием.

### Уровень 2. Каноническая документация

- system context;
- backlog;
- ADR;
- handoff;
- release-readiness document.

Подходит продукту с несколькими окружениями.

### Уровень 3. Исполняемые gates

- CI contracts;
- migration checks;
- secret scanning;
- dependency audit;
- release identity;
- realistic integration tests.

### Уровень 4. Skills и tool registry

- узкие procedural skills;
- validator;
- `.codex/tooling` manifest;
- independent forward-testing;
- review/activation gate.

### Уровень 5. Orchestration

- stable task node IDs;
- ownership matrix;
- one-writer rule;
- dependency frontier;
- evidence taxonomy;
- cleanup lifecycle.

### Уровень 6. Controlled memory и automation

- bounded persistent memory;
- session search;
- retention/redaction;
- candidate skill generation;
- fail-quiet script monitors;
- LLM triage только для проблемных событий.

Необязательно внедрять все уровни. Следующий уровень оправдан, если снижает уже
наблюдавшийся риск или стоимость работы.

---

## 20. Антипаттерны

### Один огромный `AGENTS.md`

Проблема: постоянная стоимость контекста и смешение разных сроков жизни.  
Альтернатива: короткие rules плюс canonical docs и on-demand skills.

### Memory как текущая production truth

Проблема: facts устаревают.  
Альтернатива: memory хранит pointers и устойчивые conventions; volatile facts
перепроверяются.

### Skill для каждой ошибки

Проблема: сотни узких и конфликтующих инструкций.  
Альтернатива: сначала test/script; skill только для повторяемой процедуры.

### Автоматическое самоизменение

Проблема: одна ошибочная гипотеза становится постоянной политикой.  
Альтернатива: generated candidate, independent evidence, diff review, activation.

### Дублирование канонических документов

Проблема: агент выбирает удобную, но устаревшую версию.  
Альтернатива: один source of truth на домен, история в Git.

### Отчёт subagent как доказательство

Проблема: worker мог ошибиться, читать не то окружение или не завершить cleanup.  
Альтернатива: root проверяет artifact, diff, tests и runtime/provider evidence.

### Broad scan до архитектурной навигации

Проблема: лишние токены и случайное чтение secrets/irrelevant files.  
Альтернатива: graph/query, точные IDs и scoped source confirmation.

### LLM heartbeat для каждого `OK`

Проблема: токены расходуются без решения.  
Альтернатива: script filters healthy state; LLM включается на anomaly.

### Глобальная установка agent packages

Проблема: conflicts и невоспроизводимость.  
Альтернатива: pinned isolated tool environment плюс live probe.

---

## 21. Чек-лист переноса в другой проект

### Сначала

- [ ] Определить repo scope и соседние запрещённые проекты.
- [ ] Создать небольшой `AGENTS.md`.
- [ ] Создать `PROJECT.md`.
- [ ] Создать `ERRORS.md` с форматом записи.
- [ ] Зафиксировать secret и PII boundary.
- [ ] Определить минимальные test/release gates.

### Затем

- [ ] Разделить product truth, system context, backlog и readiness.
- [ ] Ввести ADR для устойчивых решений.
- [ ] Добавить handoff format.
- [ ] Настроить Graphify или другой архитектурный индекс, если codebase большой.
- [ ] Описать one-writer и subagent review rules.
- [ ] Выбрать evidence labels, если есть production/providers.

### После накопления опыта

- [ ] Перенести повторяемые ошибки в tests/CI/scripts.
- [ ] Создать первые узкие skills.
- [ ] Добавить tool dependency manifest и live probes.
- [ ] Ввести candidate/review/activation lifecycle.
- [ ] Определить memory retention и redaction.
- [ ] Заменить routine LLM polling на deterministic fail-quiet scripts.

---

## 22. Рекомендуемый минимальный starter kit

Если нужно начать быстро, можно создать только пять artifacts:

1. `AGENTS.md` — scope, authority, Git, secrets, tests, learning.
2. `PROJECT.md` — продукт и инварианты.
3. `ERRORS.md` — подтверждённые повторяемые ошибки.
4. `docs/PROJECT-CONTEXT.md` — окружения и архитектура.
5. CI script, проверяющий наиболее опасный инвариант проекта.

После первых нескольких повторяемых workflows добавить:

6. `.codex/skills/`;
7. `.codex/tooling/`;
8. ADR;
9. release-readiness document;
10. task graph только для действительно крупных эпиков.

---

## 23. Итоговая модель

Зрелая система управления AI-разработкой состоит не из одного умного prompt, а из
сочетания:

- компактных правил поведения;
- разделённых источников истины;
- исполняемых проверок;
- точной evidence-модели;
- управляемого делегирования;
- воспроизводимого agent tooling;
- безопасной памяти;
- on-demand skills;
- review и activation gates;
- удаления устаревших временных artifacts.

Hermes-подобная часть особенно полезна там, где подтверждённый опыт не просто
записывается в журнал, а проходит путь до test, CI, skill или policy. Это позволяет
агентам действительно становиться эффективнее от проекта к проекту, не превращая
самообучение в неконтролируемое самоизменение.

---

## 24. Материалы для дальнейшего изучения

Официальные материалы Hermes Agent, использованные как источник идей:

- Project/context files and memory roles:
  https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/which-file-does-what.md
- Persistent memory:
  https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/memory.md
- Working with skills and progressive disclosure:
  https://github.com/NousResearch/hermes-agent/blob/main/website/docs/guides/work-with-skills.md
- Tools, toolsets and session search:
  https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/tools.md
- Session lifecycle and compression behavior:
  https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/sessions.md

Эти материалы описывают Hermes Agent. При переносе идей в Codex, Claude Code,
Cursor, OpenCode или другой агент нужно проверять фактическую поддержку hierarchy,
skills, memory, hooks, approvals и tool isolation в выбранной платформе.
