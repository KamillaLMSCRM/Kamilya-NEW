# Организационная структура v2: произвольная вложенность и независимые должности

**Дата:** 2026-09-17  
**Статус:** утверждённый план реализации в отдельной feature-ветке; production не изменяется  
**Ветка:** `feature/org-hierarchy-v2-20260917`  
**Базовая ревизия:** `6205c640fd0b9b6e3bb5a28b89be912915e29e39`

## 1. Цель

Сделать оргструктуру пригодной для компаний с любой обычной иерархией:

```text
Центральный офис
└── Управление
    └── Департамент
        └── Отдел
            └── Сектор
```

При этом сотрудник обязан иметь должность, но может не относиться ни к одному
структурному подразделению. Должность и место сотрудника в оргструктуре не должны
создавать обязательную пару.

## 2. Подтверждённая проблема текущей реализации

Текущая физическая таблица `departments` уже имеет `parent_id`, но доменный
контракт разрешает только `branch -> department`:

- `OrganizationUnitType` содержит только `branch` и `department`;
- филиал обязан быть корнем;
- отдел обязан иметь родителем филиал;
- `Position.department_id` одновременно используется как принадлежность
  должности к отделу и как косвенное место сотрудника в структуре;
- у `User` нет самостоятельного `organization_unit_id`;
- правила обучения, программы, отчёты и импорт раскрывают только один уровень;
- «центральный офис» не имеет явной семантики и может быть только названием.

Поэтому точечное изменение одной модалки оставит противоречивые данные и разные
правила в ручном вводе, импорте и назначении обучения.

## 3. Принятые продуктовые решения

### 3.1. Организационный узел

`Department` временно остаётся физической совместимой моделью, но в новом
доменном модуле рассматривается как `OrganizationUnit`.

Поддерживаемые виды узлов:

- `organization` — верхний уровень компании, если он нужен;
- `branch` — филиал/территориальная площадка;
- `management` — управление;
- `division` — департамент/дивизион;
- `department` — отдел;
- `sector` — сектор;
- `team` — группа/команда;
- `other` — иной тип с пользовательским названием.

Тип не задаёт допустимого родителя. Любой активный узел может быть дочерним
любому активному узлу того же tenant. Структурные ограничения общие:

1. родитель принадлежит тому же tenant;
2. узел не может быть родителем самому себе;
3. родителем нельзя выбрать собственного потомка;
4. максимальная глубина — 8 уровней;
5. архивный узел нельзя выбрать новым родителем;
6. активные соседи одного родителя не могут иметь одинаковые нормализованные
   имя и тип;
7. перемещение сохраняет ID узла и всех потомков.

### 3.2. Центральный офис

Центральный офис — явный признак `is_head_office`, а не имя и не следствие
`parent_id IS NULL`.

- у tenant может быть не более одного активного центрального офиса;
- центральный офис является корневым узлом;
- создание центрального офиса необязательно: существующие tenant продолжают
  работать без автоматической классификации;
- пустое подразделение сотрудника никогда не трактуется как центральный офис;
- смена центрального офиса — отдельная аудируемая операция.

### 3.3. Должность и место сотрудника

`Position` остаётся tenant-scoped справочником должностных профилей: название,
обязанности, требования, инструкция, компетенции и правила обучения.

Добавляется nullable `User.organization_unit_id`:

- `position_id` обязателен в ручной форме сотрудника;
- `organization_unit_id` необязателен;
- одну и ту же должность можно выбрать сотрудникам из разных узлов;
- новая должность по умолчанию создаётся без `department_id`;
- старый `Position.department_id` сохраняется как compatibility/default hint,
  но не является авторитетным местом сотрудника;
- старый `department_id` API принимается как alias `organization_unit_id` на
  переходный период;
- автоматического переноса неоднозначных legacy-связей нет.

Отдельная таблица истории переводов и несколько одновременных мест сотрудника не
входят в этот релиз. Они потребуют самостоятельного продукта и UX. Изменения
фиксируются существующим аудитом.

## 4. Глубокий модуль и интерфейсы

Новый модуль `organization_scope` скрывает recursive SQL и совместимость от
всех потребителей.

```python
resolve_descendants(tenant_id, unit_ids, *, include_self=True, active_only=True)
resolve_ancestor_path(tenant_id, unit_id)
resolve_employee_scope(tenant_id, unit_ids)
validate_move(tenant_id, unit_id, parent_id, *, max_depth=8)
```

Ни router, ни training rules, ни learning paths, ни отчёты не должны строить
собственные варианты рекурсивного обхода.

Наследование правил:

- правило узла действует на сотрудников самого узла и всех активных потомков;
- правила всех подходящих предков объединяются;
- правило должности продолжает применяться независимо от узла;
- для provenance ближайший узел считается наиболее специфичным;
- completed/manual/program enrollments не удаляются при пересчёте;
- архивные узлы не получают новых назначений, но сохраняются в истории.

## 5. Миграция данных

### 5.1. Expand migration

1. Расширить допустимые `unit_type` без переименования таблицы.
2. Добавить `departments.is_head_office boolean not null default false`.
3. Добавить `users.organization_unit_id nullable`.
4. Добавить tenant-safe индексы и проверки:
   - один активный `is_head_office` на tenant;
   - центральный офис только в корне;
   - tenant ownership родителя и сотрудника;
   - cycle/depth trigger;
   - RLS и FORCE RLS сохраняются.
5. Удалить только старые ограничения, запрещающие вложенный отдел и требующие
   филиал-корень; заменить их новыми общими инвариантами.

### 5.2. Backfill

- существующие ID, slug, правила и связи не меняются;
- если `User.position_id -> Position.department_id` однозначен, заполнить
  `User.organization_unit_id`;
- если связь отсутствует — оставить `NULL`;
- если legacy-текст противоречит FK — не угадывать, сохранить `NULL` и вывести
  запись в отчёт миграции;
- ни один существующий узел автоматически не объявлять центральным офисом.

### 5.3. Compatibility period

- новые записи пишут `User.organization_unit_id`;
- чтение сначала использует его, затем однозначный legacy fallback;
- старые поля API остаются, но помечаются compatibility;
- `Position.department_id` не удаляется и не перепривязывается массово;
- downgrade не удаляет уже созданную многоуровневую структуру; rollback — это
  отключение feature flag и возврат на legacy-read, а не потеря данных.

## 6. Backend

### 6.1. CRUD структуры

- generic create/update/archive/move для любого типа узла;
- `PATCH /organization-units/{id}` различает отсутствующий `parent_id` и явный
  `null`;
- отдельный preview перемещения возвращает затронутые узлы, должности и
  сотрудников;
- archive запрещён при активных детях, сотрудниках или legacy positions;
- ответы содержат `breadcrumb`, `depth`, `is_head_office` и recursive counts.

### 6.2. Сотрудники

- manual create/update принимает `organization_unit_id | null` независимо от
  `position_id`;
- существующая должность выбирается без предварительного выбора узла;
- выбор legacy position может предложить, но не навязать старый отдел;
- cross-tenant unit/position дают 422/404 без утечки существования;
- employee projection строится по `User.organization_unit_id`, а не только
  через `Position.department_id`.

### 6.3. Правила и аудитории

Через `organization_scope` переводятся:

- department/unit course rules;
- recompute enrollments;
- learning program audience;
- quiz bulk audience;
- learning insights filters;
- training log filters;
- evidence export current hierarchy path.

Исторические evidence snapshots не переписываются после перемещения узла.

## 7. Импорт

### 7.1. Legacy adapter

Старые Excel/CSV с колонками «Филиал / Отдел / Должность» продолжают работать.
Adapter переводит их в generic units и сохраняет прежнюю идемпотентность.

### 7.2. Generic import contract

Новый внутренний контракт:

```json
{
  "organization_units": [
    {
      "external_key": "unit-1",
      "parent_external_key": null,
      "unit_type": "management",
      "name": "Управление"
    }
  ],
  "positions": [
    {"external_key": "pos-1", "name": "Бухгалтер"}
  ],
  "staff": [
    {
      "personnel_number": "001",
      "position_external_key": "pos-1",
      "organization_unit_external_key": "unit-1"
    }
  ]
}
```

- неоднозначный parent/path блокирует approval;
- коррекция меняет proposal revision и требует повторного approval;
- повторный импорт не создаёт дубликаты;
- commit атомарный;
- post-commit tree readback обязателен.

## 8. Frontend UX

### 8.1. Дерево

- один рекурсивный компонент вместо отдельных branch/department блоков;
- произвольное раскрытие до 8 уровней;
- видимый тип, breadcrumb, счётчики потомков/должностей/сотрудников;
- поиск раскрывает путь к совпадению;
- создание дочернего узла доступно на любом узле;
- перемещение использует searchable tree picker и preview последствий;
- central office отмечен отдельным badge, а не особым названием;
- legacy/unassigned записи видимы и объяснены.

### 8.2. Модалка сотрудника

- обязательные поля: табельный номер, имя, фамилия, должность;
- подразделение необязательно;
- список всех существующих должностей доступен сразу;
- подразделение выбирается отдельным tree picker;
- у должности показывается legacy/default breadcrumb только как подсказка;
- можно явно создать новую должность без подразделения;
- отмена не оставляет черновое состояние.

## 9. Проверки и приёмка

### Gate A — чистая архитектурная база

- feature-ветка создана от exact `origin/master`;
- основной dirty checkout не используется;
- plan и ADR описывают compatibility и rollback;
- ни одна production mutation не выполняется.

### Gate B — домен и migration

- RED/GREEN tests: 0/1/2/8 levels, depth 9 rejected;
- self-parent, descendant-parent, cross-tenant и inactive-parent rejected;
- один active head office, root-only;
- existing tenant upgrade сохраняет ID и rule bindings;
- Supabase DEV disposable schema: upgrade, RLS/FORCE RLS, wrong/missing tenant
  negatives, cleanup readback.

### Gate C — API и правила

- nullable unit + required position;
- position usable in two different units;
- subtree move preserves employees and descendants;
- recursive rule preview equals recompute result;
- sibling tenant/unit does not receive assignments;
- old `department_id` client remains compatible;
- historical evidence remains unchanged.

### Gate D — import

- legacy two-level file produces equivalent structure;
- generic four-level file produces exact hierarchy;
- duplicate names under different parents are valid;
- ambiguous parents block approval;
- repeated import is idempotent;
- no writes before approval and atomic commit.

### Gate E — frontend

- component tests for recursive tree, search, breadcrumbs and move preview;
- modal tests: no unit, existing position, new position, cross-unit position;
- typecheck, lint, focused Vitest and full frontend suite;
- browser acceptance in a synthetic tenant only.

### Gate F — root acceptance

Root agent independently:

1. reviews every diff and migration;
2. rejects unrelated changes;
3. runs focused tests, canonical database-free gate and full available suites;
4. runs approved Supabase DEV schema/RLS gate;
5. performs the synthetic human journey;
6. records exact branch SHA and evidence;
7. returns GO/NO_GO for merge; production remains a separate owner decision.

## 10. Распределение работы

| Поток | Исполнитель | Непересекающаяся зона записи | Результат |
|---|---|---|---|
| A | дешёвый backend-agent | migration, domain, organization scope, backend unit tests | произвольная глубина и tenant-safe invariants |
| B | дешёвый API-agent | manual staff/API compatibility, recursive audiences, API tests | независимые position/unit и наследование |
| C | дешёвый frontend-agent | `/staff` recursive UI и Vitest | понятное дерево и модалка |
| D | дешёвый import-agent | import DTO/adapter/commit и tests | legacy + generic import |
| Review | root | integration branch only | code review, conflict resolution, gates, GO/NO_GO |

Каждый агент работает в отдельной forked ветке/workspace, пишет только в свою
зону и возвращает handoff `result / changed / verified / blockers / next` на
английском. Root принимает изменения выборочно после проверки.

## 11. Порядок реализации

1. Domain + additive migration + pure tests.
2. Recursive resolver + API compatibility.
3. Manual employee flow.
4. Recursive training rules/audiences.
5. Generic tree frontend.
6. Import adapter and generic DTO.
7. Full static/integration/DEV/browser acceptance.
8. Только после отдельного согласования: merge, version, changelog, release,
   production deployment и live readback.

## 12. Явно не входит

- несколько одновременных подразделений у сотрудника;
- кадровая история переводов с датами действия;
- автоматическая классификация существующих корней как central office;
- удаление legacy columns/tables;
- изменение тарифов или платных ресурсов;
- production deployment в рамках текущей задачи.
