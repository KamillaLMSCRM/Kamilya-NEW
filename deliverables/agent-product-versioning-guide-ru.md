# Версионирование продукта в проектах с AI-агентами

Переносимая практическая инструкция для любого программного проекта.

Версия документа: 1.0  
Дата: 2026-08-29  
Статус: универсальный рекомендуемый стандарт  
Связанный документ: [Система управления разработкой проекта с AI-агентами](agent-project-development-governance-guide-ru.md)

---

## 1. Назначение

Версия продукта должна отвечать не только на вопрос «какой код сейчас в Git»,
но и на более важные вопросы:

1. Какой набор функций и исправлений получил пользователь?
2. Какая версия фактически развернута в конкретном окружении?
3. Какие миграции, настройки и зависимости относятся к этому выпуску?
4. Можно ли воспроизвести, проверить и откатить выпуск?
5. Кто имел право изменить номер версии, создать тег и выполнить deployment?
6. Как другой агент отличит незавершенную работу от опубликованного продукта?

Git commit, branch, container image, deployment ID и версия продукта связаны,
но не взаимозаменяемы. Версия описывает пользовательский выпуск. Commit
идентифицирует состояние исходного кода. Image digest идентифицирует артефакт.
Runtime readback доказывает, что конкретный артефакт действительно работает в
целевом окружении.

Главный принцип:

> Версия является проверяемым контрактом между кодом, документацией, сборкой,
> deployment и пользовательским поведением, а не декоративной строкой в UI.

---

## 2. Минимальная модель

Для большинства проектов достаточно пяти элементов:

| Элемент | Роль |
|---|---|
| `VERSION` | Единственный канонический номер продукта |
| `CHANGELOG.md` | Состав незавершенного и опубликованных выпусков |
| Манифесты приложений | Технические версии package/build systems |
| CI version gate | Исполняемая проверка согласованности |
| `docs/releases/` | Человекочитаемые release notes и evidence выпуска |

Рекомендуемая структура:

```text
project/
|-- VERSION
|-- CHANGELOG.md
|-- AGENTS.md
|-- apps/
|   |-- api/
|   |   `-- pyproject.toml
|   `-- web/
|       `-- package.json
|-- docs/
|   `-- releases/
|       |-- README.md
|       |-- RELEASE_NOTE_TEMPLATE.md
|       `-- v1.4.0.md
|-- scripts/
|   |-- validate_version.py
|   `-- tests/
|       `-- test_validate_version.py
`-- .github/
    `-- workflows/
        `-- ci.yml
```

Для single-app проекта список манифестов сокращается. Для monorepo сначала
нужно выбрать одну из моделей из раздела 15, а не автоматически присваивать
всем пакетам одинаковую версию.

---

## 3. Один источник истины

В корне репозитория создается текстовый файл `VERSION`:

```text
1.4.0
```

Требования к файлу:

- одна строка;
- UTF-8;
- без префикса `v`;
- без пояснений и даты;
- формат соответствует принятой SemVer-политике;
- изменение выполняется только в рамках release-процедуры.

Манифесты не являются независимыми источниками истины. Их значения должны
совпадать с `VERSION` либо детерминированно генерироваться из него.

Не следует определять текущую версию по последнему Git-тегу во время обычной
сборки. Shallow clone, отсутствующие теги и сборка из detached commit делают
такой подход нестабильным. Тег должен подтверждать уже подготовленную версию,
а не создавать ее неявно.

---

## 4. Semantic Versioning как продуктовая политика

Базовый формат:

```text
MAJOR.MINOR.PATCH
```

| Изменение | Компонент | Пример |
|---|---|---|
| Несовместимое изменение публичного контракта | `MAJOR` | `2.3.1 -> 3.0.0` |
| Новая обратно совместимая функция | `MINOR` | `2.3.1 -> 2.4.0` |
| Обратно совместимое исправление | `PATCH` | `2.3.1 -> 2.3.2` |

К публичному контракту относятся не только HTTP API. Контрактом могут быть:

- пользовательский flow;
- формат импорта или экспорта;
- CLI flags;
- события интеграции;
- webhook payload;
- schema, доступная клиентам;
- поддерживаемая конфигурация;
- обещанное поведение ролей и прав;
- формат сохраняемых документов;
- SDK interface.

### 4.1. Практическая матрица решений

| Ситуация | Обычно |
|---|---|
| Добавлен новый экран без поломки старых | `MINOR` |
| Добавлен optional API field | `MINOR` |
| Исправлен 500 без изменения контракта | `PATCH` |
| Исправлен текст или верстка | `PATCH` |
| Удален endpoint | `MAJOR` |
| Обязательное поле изменило смысл | `MAJOR` |
| Изменен default с заметным влиянием | review; часто `MAJOR` |
| Добавлена миграция без изменения внешнего поведения | зависит от функции |
| Обновлена внутренняя библиотека | версия по пользовательскому эффекту |
| Изменен только CI | версия продукта обычно не меняется |

Версия классифицирует результат, а не объем diff. Однострочная несовместимая
правка может требовать `MAJOR`, а большой внутренний refactor может не требовать
новой версии до появления пользовательского выпуска.

### 4.2. Проекты до `1.0.0`

SemVer допускает нестабильность `0.x.y`, но команда должна явно определить
свою политику. Рекомендуемый вариант:

- `0.MINOR.0` для заметной новой функции или несовместимого изменения;
- `0.MINOR.PATCH` для исправления;
- release notes явно отмечают несовместимость;
- переход на `1.0.0` происходит после фиксации поддерживаемых контрактов.

Нельзя использовать статус `0.x` как оправдание отсутствия changelog,
миграционного плана или rollback.

### 4.3. Prerelease

Если prerelease действительно нужен, политика задается заранее:

```text
1.5.0-alpha.1
1.5.0-beta.1
1.5.0-rc.1
```

Validator, manifests, container tags и deployment tooling должны принимать
один и тот же формат. Нельзя начать создавать `-rc.1`, если действующий gate
разрешает только `X.Y.Z`.

Build metadata, например `1.5.0+build.42`, не заменяет commit SHA. Если
инфраструктура плохо обрабатывает `+`, лучше хранить build identity отдельно.

---

## 5. Changelog: незавершенная работа и история выпусков

Рекомендуется формат Keep a Changelog:

```markdown
# Changelog

## [Unreleased]

### Added

### Changed

### Deprecated

### Removed

### Fixed

### Security
```

Правила записи:

- запись добавляется в том же change set, что и пользовательское изменение;
- текст описывает результат для пользователя или оператора;
- внутренние имена классов не заменяют объяснение эффекта;
- одна запись не обещает непроверенный результат;
- security detail не раскрывает эксплуатационные секреты до исправления;
- одинаковые записи объединяются;
- `[Unreleased]` всегда существует;
- опубликованные секции не переписываются без отдельной процедуры исправления истории.

Хорошая запись:

```markdown
- Added course generation from up to five compatible source documents with
  explicit mixed-language confirmation.
```

Плохая запись:

```markdown
- Updated router.py and fixed stuff.
```

### 5.1. Формирование секции выпуска

При выпуске `1.4.0` содержимое `[Unreleased]` переносится в:

```markdown
## [1.4.0] - 2026-08-29
```

После этого создается новый пустой `[Unreleased]`. Дата должна отражать дату
публикации выпуска, а не дату первого commit.

Comparison links добавляются только для реально существующих тегов и
правильного repository URL. Первый выпуск не обязан иметь compare link.

---

## 6. Полномочия агентов

Версионирование требует разделения обычной разработки и release authority.

### 6.1. Любой coding agent

Coding agent обязан:

- записать пользовательское изменение в `[Unreleased]`;
- не менять опубликованные release notes;
- не повышать `VERSION` без release-поручения;
- не создавать Git-тег;
- не объявлять deployment выпуском;
- передать root orchestrator результаты тестов и migration notes.

### 6.2. Test agent

Test agent обязан:

- проверять exact commit или immutable artifact;
- не менять номер версии;
- фиксировать test scope, окружение и результат;
- отделять `VERIFIED`, `PARTIALLY VERIFIED`, `NOT VERIFIED` и `BLOCKED`;
- не считать changelog доказательством runtime-поведения.

### 6.3. Release agent

Release agent может выполнять только заранее подготовленный release packet:

- exact source SHA;
- ожидаемая версия;
- target environment;
- migration command;
- deploy order;
- smoke checks;
- rollback target;
- stop conditions.

Release agent не должен самостоятельно менять состав выпуска. При расхождении
packet и фактического состояния он останавливается и возвращает blocker.

### 6.4. Root orchestrator

Только назначенный root/release owner:

- принимает решение о номере версии;
- замораживает состав выпуска;
- переносит changelog entries;
- синхронно меняет `VERSION` и manifests;
- создает release commit и tag;
- разрешает deployment;
- принимает production evidence;
- публикует release notes.

Эту модель нужно явно записать в `AGENTS.md`.

---

## 7. Минимальный блок для `AGENTS.md`

```markdown
## Product versioning

- `VERSION` is the canonical product version.
- Every user-visible change must update `CHANGELOG.md` under `[Unreleased]`.
- Coding and test agents must not bump versions, create tags, publish releases,
  or deploy unless the owner gives an exact release instruction.
- Only the root orchestrator chooses the next version and synchronizes all
  manifests.
- A release is not complete until exact artifact identity and user-visible
  production behavior are independently read back.
```

Проект может добавить свои manifests и команды, но не должен помещать в
`AGENTS.md` текущий номер версии. Текущий номер принадлежит `VERSION`.

---

## 8. Детерминированный version gate

CI должен проверять минимум:

1. `VERSION` существует и соответствует принятому формату.
2. Все product manifests содержат то же значение.
3. `CHANGELOG.md` содержит `[Unreleased]`.
4. Validator завершает работу с ненулевым exit code при расхождении.
5. Есть негативные тесты validator, а не только проверка happy path.

Пример универсального Python-скрипта:

```python
#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path

SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    canonical = (root / "VERSION").read_text(encoding="utf-8").strip()
    api = tomllib.loads(
        (root / "apps/api/pyproject.toml").read_text(encoding="utf-8")
    )["tool"]["poetry"]["version"]
    web = json.loads(
        (root / "apps/web/package.json").read_text(encoding="utf-8")
    )["version"]
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")

    errors = []
    if not SEMVER.fullmatch(canonical):
        errors.append("VERSION must use X.Y.Z")
    if len({canonical, api, web}) != 1:
        errors.append(f"version mismatch: VERSION={canonical}, api={api}, web={web}")
    if "## [Unreleased]" not in changelog:
        errors.append("CHANGELOG.md has no [Unreleased]")

    for error in errors:
        print(f"VERSION ERROR: {error}", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Скрипт адаптируется к конкретным manifests. Он не должен обращаться к сети,
Git provider или production. Это быстрый deterministic gate.

### 8.1. Обязательные тесты validator

- согласованные значения проходят;
- пустой `VERSION` не проходит;
- неверный SemVer не проходит;
- расхождение одного manifest не проходит;
- отсутствующий manifest не проходит;
- отсутствующий `[Unreleased]` не проходит;
- prerelease проходит только если политика его разрешает;
- парсинг выполняется TOML/JSON parser, а не хрупким regex replace.

### 8.2. Место в CI

Version gate должен выполняться до дорогих build/deploy jobs. Если версия
структурно неверна, дальнейшая сборка не имеет смысла.

```yaml
- name: Product version consistency
  run: python scripts/validate_version.py

- name: Version gate tests
  run: python -m pytest -q scripts/tests/test_validate_version.py
```

CI configuration также полезно покрыть contract-тестом: он проверяет, что
workflow действительно вызывает validator и что gate не стал optional.

---

## 9. Повседневный цикл разработки

### Шаг 1. Определить пользовательский эффект

До редактирования агент формулирует, что изменится для пользователя,
интеграции или оператора. Если эффекта нет, changelog entry может не требоваться.

### Шаг 2. Внести код и тесты

Изменение выполняется без bump версии. Рабочая версия остается версией
последнего подготовленного release cycle.

### Шаг 3. Обновить `[Unreleased]`

Entry добавляется в `Added`, `Changed`, `Fixed`, `Security` или другую
принятую секцию.

### Шаг 4. Запустить version gate

Gate подтверждает, что агент случайно не рассинхронизировал manifests и не
сломал changelog contract.

### Шаг 5. Передать release impact

Handoff должен содержать:

- рекомендуемый SemVer impact: none, patch, minor или major;
- changelog entry;
- migration requirement;
- configuration changes;
- compatibility risks;
- выполненные тесты;
- невыполненные проверки.

Рекомендация агента не является решением о версии. Решение принимает root.

---

## 10. Подготовка выпуска

Root orchestrator выполняет последовательность:

1. Фиксирует exact scope выпуска.
2. Проверяет, что все пользовательские изменения отражены в `[Unreleased]`.
3. Классифицирует максимальный SemVer impact среди изменений.
4. Выбирает новый номер версии.
5. Переносит записи в датированную release section.
6. Создает новый пустой `[Unreleased]`.
7. Меняет `VERSION` и все product manifests одним change set.
8. Обновляет lockfiles только если этого требует package manager.
9. Создает release notes по шаблону.
10. Запускает version gate и полный release CI.
11. Создает immutable commit и тег `vX.Y.Z`.
12. Передает exact-SHA packet release agent.

Номер версии нельзя менять отдельными commits в разных manifests. Временное
расхождение усложняет cherry-pick, bisect и работу параллельных агентов.

---

## 11. Release notes

Changelog и release notes решают разные задачи.

| Документ | Аудитория | Содержание |
|---|---|---|
| `CHANGELOG.md` | разработчики и операторы | краткая полная история изменений |
| `docs/releases/vX.Y.Z.md` | владелец, клиент, support, release runner | итог, влияние, проверка, migration и rollback |

Минимальный release note:

```markdown
# Release Notes - 1.4.0

Release date: 2026-08-29
Product version: 1.4.0
Git tag: v1.4.0
Source SHA: <exact SHA>
Artifact identity: <image digest or deployment ID>

## Summary

## Added

## Changed

## Fixed

## Security

## Upgrade and deployment notes

## Verification

## Known limitations

## Rollback
```

Release notes не должны содержать credentials, raw tenant data, персональные
данные или неотредактированные production logs.

---

## 12. Release evidence

Зеленый CI подтверждает исходный код, но не production runtime. Для закрытия
выпуска нужны разные уровни evidence:

| Уровень | Что доказывает |
|---|---|
| Source | exact commit содержит ожидаемые изменения |
| Build | immutable artifact собран из exact commit |
| Deploy | target использует ожидаемый artifact |
| Schema | миграции находятся на ожидаемой revision |
| Runtime | процессы и workers запущены без скрытого старого экземпляра |
| Business smoke | пользовательский flow действительно работает |

Корректный отчет не смешивает эти уровни:

```text
Source SHA: VERIFIED
Image digest: VERIFIED
Database revision: VERIFIED
Worker identity: VERIFIED
User-visible smoke: PARTIALLY VERIFIED
External email delivery: NOT VERIFIED
```

HTTP 200, успешный deploy command или совпавший номер версии по отдельности не
доказывают выпуск.

---

## 13. Миграции и совместимость

Версия приложения и revision базы не должны подменять друг друга. Release note
фиксирует обе.

Безопасная модель:

- миграции additive или expand-compatible;
- старый и новый runtime временно совместимы со schema;
- destructive cleanup выполняется отдельным поздним выпуском;
- migration command известен заранее;
- backup/restore требования определены;
- rollback учитывает необратимые data transformations.

Если rollback к предыдущему image невозможен после миграции, нельзя писать
«rollback: redeploy previous tag». Нужно явно указать forward-fix или restore.

---

## 14. Rollback contract

Каждый release packet отвечает на вопросы:

1. Какой предыдущий artifact является rollback target?
2. Совместим ли он с новой schema?
3. Нужно ли откатывать конфигурацию?
4. Есть ли фоновые workers со старым task protocol?
5. Какие данные могли быть записаны новым форматом?
6. Как проверить успешность rollback?
7. Какова stop condition?

Rollback сам является production mutation и требует полномочий. Его нельзя
автоматически запускать только потому, что один smoke check дал ошибку, если
причина и data risk не классифицированы.

---

## 15. Monorepo: единая или независимые версии

### 15.1. Единая product version

Подходит, когда backend, frontend и workers выпускаются как один продукт.

Преимущества:

- пользователю легко назвать версию;
- один changelog;
- простой release packet;
- легче сопоставить support case и runtime.

Недостатки:

- пакет может получить новую версию без собственных изменений;
- независимый deployment требует дополнительной artifact identity.

### 15.2. Независимые package versions

Подходит для библиотек и сервисов с независимыми consumers и release cycles.

Тогда нужны:

- отдельный источник версии на пакет;
- отдельный changelog или changesets;
- dependency compatibility matrix;
- product-level release manifest, связывающий версии компонентов.

Пример product release manifest:

```json
{
  "product": "2.1.0",
  "api": "4.3.2",
  "web": "3.8.0",
  "worker": "4.3.2"
}
```

Нельзя случайно смешивать модели: общий `VERSION` и независимые package tags
без manifest связи создают неоднозначность.

---

## 16. Внедрение в существующий проект

### Этап 1. Инвентаризация

Найти все текущие версии:

- manifests;
- UI footer/about screen;
- image labels;
- Helm/chart values;
- deployment variables;
- mobile build numbers;
- tags и releases;
- API `/version` или `/health`;
- документация.

Нельзя автоматически считать максимальное найденное число правильным.

### Этап 2. Выбор baseline

Baseline подтверждается владельцем. Если продукт никогда не выпускался
формально, допустим `0.1.0`. Если клиенты уже используют публичные версии,
новая схема должна продолжать существующую последовательность.

### Этап 3. Создание foundation

Одним change set добавляются:

- `VERSION`;
- `CHANGELOG.md` с `[Unreleased]`;
- release policy;
- release note template;
- validator и тесты;
- CI gate;
- authority rules в `AGENTS.md`.

### Этап 4. Проверка без выпуска

Foundation не обязана немедленно создавать новый tag. Сначала validator должен
пройти на текущем baseline. Первый формальный release выполняется отдельной
процедурой.

### Этап 5. Runtime identity

При следующем release версия в `/health` или UI связывается с commit SHA и
artifact digest. Номер версии не должен быть единственным runtime identifier.

---

## 17. Hotfix

Hotfix не отменяет обычные правила:

1. Воспроизводится production defect.
2. Готовится минимальное исправление.
3. Добавляется regression test.
4. Добавляется `[Unreleased] -> Fixed` или `Security`.
5. Root выбирает следующий `PATCH`.
6. Выполняются version gate и release gates.
7. Создается новый tag.
8. Проверяется production runtime и конкретный defect flow.

Нельзя незаметно перезаписать существующий tag или release artifact. Версия
должна быть immutable.

---

## 18. Security releases

Security changelog должен быть полезным, но не создавать новый exploit guide.

До раскрытия деталей рекомендуется фиксировать:

- затронутый компонент;
- класс риска;
- наличие обязательного обновления;
- совместимость;
- необходимые operator actions.

CVE, детальный abuse path и proof-of-concept публикуются по отдельной disclosure
policy. Secret rotation не записывает значения секретов.

---

## 19. Автоматизация и инструменты

Для больших monorepo могут использоваться Changesets, semantic-release,
release-please, conventional commits или собственный tooling. Инструмент не
заменяет policy.

Перед автоматизацией нужно решить:

- кто классифицирует SemVer impact;
- кто имеет tag/release credentials;
- как предотвращается повторный release;
- как подписываются tags/artifacts;
- как формируется rollback packet;
- что происходит при частично успешном deployment;
- как release связывается с migration revision;
- как human owner может остановить процесс.

Для agent-managed проекта безопасный default: автоматизировать deterministic
validation и сбор evidence, но оставить решение о номере и production mutation
за root/owner.

---

## 20. Антипаттерны

### Версия только в `package.json`

Не работает для multi-app продукта и создает случайный источник истины.

### Версия равна номеру deployment

Deployment может повторяться без продуктового изменения. Это разные сущности.

### Автоматический bump на каждый merge

Создает шум и не отражает пользовательский release scope.

### Changelog после deployment

Состав выпуска становится реконструкцией истории вместо проверяемого input.

### Агент сам выбирает версию и пушит tag

Отчет агента не дает release authority и может не учитывать параллельные ветви.

### Перезапись существующего тега

Разрушает воспроизводимость и доверие к release artifacts.

### Номер версии без exact SHA

Два разных артефакта могут ошибочно называться одной версией.

### Зеленый CI равен успешному production release

CI не доказывает target, runtime identity, migrations и бизнес-flow.

### Откат версии без отката данных

Старый runtime может быть несовместим с новой schema или записанными данными.

### Compare link на несуществующий tag

Создает солидно выглядящую, но ложную документацию.

---

## 21. Чек-лист обычного агента

- Определен пользовательский эффект.
- Изменение записано в `[Unreleased]`.
- SemVer impact рекомендован, но версия не повышена.
- Манифесты не рассинхронизированы.
- Version validator выполнен.
- Добавлены пропорциональные тесты.
- Migration/config impact передан root.
- Tag и release не создавались без authority.
- В отчет не попали secrets или PII.

---

## 22. Чек-лист root orchestrator перед release

- Scope выпуска заморожен.
- Все entries `[Unreleased]` проверены.
- Breaking changes явно классифицированы.
- Новый номер версии выбран по policy.
- `VERSION` и manifests совпадают.
- Release section датирована.
- Новый пустой `[Unreleased]` создан.
- Lockfiles согласованы.
- CI и security gates зелёные.
- Migration и deploy order определены.
- Exact SHA и artifact identity зафиксированы.
- Rollback target и data caveats определены.
- Release note заполнен.
- Production acceptance checklist подготовлен.

---

## 23. Чек-лист после deployment

- Target environment независимо подтвержден.
- Runtime показывает ожидаемые version и SHA.
- Все нужные services и workers используют согласованный artifact.
- Database revision соответствует packet.
- Критический пользовательский flow пройден.
- Внешние интеграции проверены либо честно отмечены `NOT VERIFIED`.
- Ошибки и rollback conditions не сработали.
- Release notes опубликованы.
- Следующий `[Unreleased]` готов к работе.

---

## 24. Итоговая модель

Устойчивое версионирование строится как цепочка:

```text
user-visible change
  -> CHANGELOG [Unreleased]
  -> tests and CI gates
  -> root version decision
  -> synchronized VERSION and manifests
  -> immutable commit, tag and artifact
  -> controlled deployment
  -> independent runtime and business readback
  -> published release notes
```

Если один элемент отсутствует, версия может существовать формально, но выпуск
не является полностью доказанным. Для AI-агентов особенно важно отделять право
редактировать код от права объявлять, публиковать и развертывать release.
