# SCORM 1.2 end-to-end QA report

Дата: 2026-07-09
Ветка: `p0-first-tenant-hardening`
Основа: `origin/foundation-scorm-kiosk-assistant-2026-07-09` (commit `95a9370`)
Автор QA: Mavis agent (внешний P0-агент)

## Что проверял

Согласно `docs/agent-tasks/2026-07-09_p0_hardening_external_agent_prompt.md`
раздел «P0.1. SCORM 1.2 end-to-end QA»:

1. Импорт SCORM 1.2 ZIP через API.
2. Открытие iframe launch-shell.
3. Загрузка CSS/JS/assets.
4. Runtime bridge: LMSInitialize, LMSSetValue, LMSCommit, LMSFinish.
5. Completion при `cmi.core.lesson_status = completed | passed`.
6. Выдача certificate после completion.
7. SCORM 2004 пакеты отклоняются с понятной ошибкой.
8. Edge cases: entrypoint с query/hash, SCORM 2004 detection через namespace, path traversal.

## Что доступно для тестирования

**Реальных SCORM-пакетов iSpring / Articulate / Captivate / Chamilo в
этой среде нет** — все QA-тесты прогонялись на **синтетических
SCORM 1.2 ZIP-ах**, собранных программно в `tests/integration/test_scorm_e2e.py`
и `tests/unit/test_scorm_parse.py`. Пакеты:

- **Minimal**: `imsmanifest.xml` + `index.html` (сразу вызывает `LMSSetValue("cmi.core.lesson_status", "completed") + LMSCommit + LMSFinish`).
- **With assets**: тот же + `content/styles.css` + `content/script.js`.

Это покрывает **API contract**, **runtime bridge contract**, **asset
proxy**, **completion path**, но **не** гарантирует, что реальные
iSpring-пакеты (с popup-навигацией, индивидуальными `LMSSetValue`,
множественными SCO) будут работать. **Ручная проверка на реальных
пакетах — следующий шаг после merge**, который должен сделать
владелец (Askar) перед первым платным tenant.

## Изменения в репо

### Edge-case fix: entrypoint с query/hash

`apps/api/app/modules/scorm/router.py:128-136` — раньше `entrypoint_exists`
проверялся через `entrypoint in names`, что для SCORM 1.2 пакетов с
href вида `index.html?loadcss=1` (характерно для iSpring/Articulate)
всегда давало `False` — даже если `index.html` физически был в архиве.

**Фикс:** нормализую entrypoint до проверки (отрезаю `?...` и `#...`),
но сохраняю оригинальный href в `entrypoint` для runtime shell.

Тесты:
- `tests/unit/test_scorm_parse.py::test_resource_href_with_query_string`
- `tests/unit/test_scorm_parse.py::test_resource_href_with_hash_fragment`

### Regression fix: SCORM 2004 detection

Зафиксировано в коммите `0481f57` (вне этого эпика) — namespace
detection через tag walk вместо `root.attrib`.

Тесты (regression coverage):
- `tests/unit/test_scorm_parse.py::test_scorm2004_namespace_only_detected`

## Unit-тесты (12 кейсов)

`apps/api/tests/unit/test_scorm_parse.py`:

| Кейс | Что проверяет |
|---|---|
| `test_scorm12_explicit_schemaversion_detected` | Happy path: schemaversion="1.2" → version="scorm_1_2" |
| `test_scorm12_no_schemaversion_no_namespace_detected_as_12` | Bare manifest без schemaversion → 1.2 (default) |
| `test_scorm2004_explicit_schemaversion_detected` | schemaversion="2004 3rd Edition" → 2004 |
| `test_scorm2004_namespace_only_detected` | **Regression**: только namespace без schemaversion → 2004 |
| `test_resource_href_with_query_string` | href=`index.html?loadcss=1` → entrypoint_exists=True |
| `test_resource_href_with_hash_fragment` | href=`index.html#section-2` → entrypoint_exists=True |
| `test_resource_href_in_subdirectory` | href в подпапке → entrypoint корректный путь |
| `test_resource_href_not_in_zip_marks_entrypoint_missing` | Несуществующий href → entrypoint_exists=False (не raise) |
| `test_manifest_missing_imsmanifest_raises` | Нет imsmanifest.xml → 400 |
| `test_manifest_invalid_xml_raises` | Битый XML → 400 (не 500) |
| `test_manifest_no_launchable_resource_raises` | Resources без href → 400 |
| `test_manifest_unsafe_href_raises` | `../../etc/passwd` в href → 400, не silent import |

## Integration тесты (5 кейсов)

`apps/api/tests/integration/test_scorm_e2e.py`:

| Кейс | Что проверяет |
|---|---|
| `test_scorm12_import_happy_path` | Полный e2e: import → launch → asset proxy (CSS/HTML) → commit с completed → certificate issued |
| `test_scorm2004_rejected_with_clear_error` | SCORM 2004 пакет → 400 с упоминанием "SCORM 1.2" |
| `test_scorm_non_zip_rejected` | Битый файл → 400 с упоминанием ZIP |
| `test_scorm12_launch_requires_tenant_match` | Tenant B не может запустить курс Tenant A (403/404) |
| `test_scorm12_in_progress_does_not_complete` | `lesson_status=incomplete` → completed=False, certificate=None |

## Найденные проблемы

| Проблема | Severity | Где | Статус |
|---|---|---|---|
| SCORM 2004 detection via namespace | **High** (security/correctness) | `router.py:_parse_manifest` | ✅ Fixed в `0481f57` |
| Entrypoint с query/hash → entrypoint_exists=False | **Medium** (UX bug для iSpring пакетов) | `router.py:_parse_manifest` | ✅ Fixed в этом эпике |
| Runtime errors не логируются structured | **Low** (observability) | `router.py:commit_scorm_attempt` | ⚠️ Deferred — добавить в P1 |
| Multi-SCO packages: launch сначала на default item | **Low** (UX) | По коду есть fallback, но не тестировалось | ⚠️ Deferred — manual QA с реальными пакетами |

## Что НЕ покрыто этим QA

- **Реальные iSpring / Articulate / Captivate / Chamilo SCORM 1.2 пакеты.**
  Без них невозможно проверить:
  - popup-навигацию между SCO
  - индивидуальные `LMSSetValue` (suspend_data, location, score tracking)
  - работу с manifest, где `default organization` ссылается на
    несколько `<item>` через sequencing rules
  - поведение при объёмных пакетах (>50MB) с множеством ассетов
- **SCORM 2004** — явно вне scope (отклоняется на импорте).
- **xAPI / cmi5 / LTI** — отдельный эпик.
- **Performance на 100+ пользователей** — отдельный load test.

## Рекомендации для владельца

Перед первым платным tenant с SCORM-контентом:

1. **Собрать 2-3 реальных SCORM 1.2 пакета**: один из iSpring (часто
   используется в RU корпоративном сегменте), один экспорт из
   Articulate Storyline или Captivate, один экспорт из Moodle/Chamilo.
2. **Прогнать import → launch → complete** на каждом, обратить внимание
   на:
   - asset paths с query-параметрами (мы это уже починили)
   - multi-SCO navigation (single-SCO → multi-SCO jump)
   - score / time tracking (не должны теряться при suspend/resume)
3. **Если найдены баги** — добавлять кейсы в `test_scorm_parse.py` /
   `test_scorm_e2e.py` перед фиксом (TDD).
4. **Проверить certificate generation** после SCORM completion на
   реальном сертификате (PDF должен содержать имя сотрудника,
   название курса, дату).

## Files modified / added

- `apps/api/app/modules/scorm/router.py` — entrypoint edge-case fix (+5 строк)
- `apps/api/tests/unit/test_scorm_parse.py` — 12 unit-тестов (новый, ~210 строк)
- `apps/api/tests/integration/test_scorm_e2e.py` — 5 integration-тестов (новый, ~280 строк)
- `docs/reports/2026-07-09_scorm_12_qa_report.md` — этот отчёт

## Заключение

API contract SCORM 1.2 import → launch → asset proxy → commit →
certificate **полностью покрыт автотестами**. Реальные пакеты от
конкретных authoring tools требуют ручной проверки перед prod-запуском,
но архитектурные риски (security, multi-tenancy, completion hook)
закрыты. **Готово к merge.**