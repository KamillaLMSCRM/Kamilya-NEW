# SCORM parser + unit-test fix — handoff

**Дата:** 2026-07-09
**Сессия:** Mavis external P0-agent (продолжение после ревью Askar'а)
**Ветка:** `p0-first-tenant-hardening` (HEAD `da3a7a2` до моих правок)

## TL;DR

Askar сделал code review и нашёл **реальные баги**:

1. **`_walk()` смотрит только `el.tag`, пропускает SCORM 2004 когда namespace живёт
   в атрибуте** (`adlcp2004:scormtype="sco"` → ElementTree кладёт URI в
   `el.attrib.keys()`, не в `el.tag`). Реальные 2004 пакеты могут быть ошибочно
   классифицированы как `scorm_1_2`.

2. **`_zip_with_manifest()` helper не принимает `extra_files`** — тесты
   `test_resource_href_with_query_string`, `test_resource_href_with_hash_fragment`,
   `test_scorm12_explicit_schemaversion_detected` пытаются создать ZIP с
   `index.html` рядом, но helper их игнорирует.

3. **Отчёт содержит неточную формулировку про `npm run typecheck` и qrcode** —
   qrcode `@types/qrcode` оба есть в `package.json`. Ошибка появляется когда
   `node_modules` не установлен/неполный (например, чистый checkout без
   `npm install`). На checkout'е пользователя `npm install` пройден — у него
   typecheck чистый. У агента ошибка воспроизводилась. Это environment delta,
   не "pre-existing баг вне моего контроля".

## Что было сломано

```
$ python -m pytest tests/unit/test_scorm_parse.py -q
4 failed, 8 passed in 2.10s

FAILED test_scorm12_explicit_schemaversion_detected
  - expects entrypoint_exists=True but helper creates ZIP only with imsmanifest.xml
FAILED test_scorm2004_namespace_only_detected
  - real bug: el.attrib not checked, returns scorm_1_2 instead of scorm_2004
FAILED test_resource_href_with_query_string
  - TypeError: _zip_with_manifest() got an unexpected keyword argument 'extra_files'
FAILED test_resource_href_with_hash_fragment
  - same TypeError
```

## Что починено

### `apps/api/app/modules/scorm/router.py` — `_walk()` теперь сканирует attrib

```python
def _walk(el: ET.Element) -> bool:
    # SCORM 2004 marker can appear in element tag names OR in attribute
    # names (e.g. <resource adlcp2004:scormtype="sco">). ElementTree
    # stores namespace URIs in attrib keys as `{URI}localname`.
    tag = el.tag if isinstance(el.tag, str) else ""
    if "adlcp_v1p3" in tag or "adlcp2004" in tag:
        return True
    for attr_key in el.attrib:
        if isinstance(attr_key, str) and ("adlcp_v1p3" in attr_key or "adlcp2004" in attr_key):
            return True
    return any(_walk(child) for child in list(el))
```

Обновил комментарий выше блока чтобы отразить новое поведение.

### `apps/api/tests/unit/test_scorm_parse.py` — `_zip_with_manifest()` принимает `extra_files`

```python
def _zip_with_manifest(
    manifest_xml: str,
    extra_files: list[tuple[str, bytes]] | None = None,
):
    """Return a (zipfile.ZipFile, names) tuple ready for _parse_manifest.
    Pass `extra_files=[("index.html", b"...")]` to add entrypoint files
    alongside imsmanifest.xml so `entrypoint_exists` resolves correctly."""
    data = _make_zip(manifest_xml, extra_files=extra_files)
    zf = zipfile.ZipFile(io.BytesIO(data))
    names = [n.replace("\\", "/") for n in zf.namelist() if n and not n.endswith("/")]
    return zf, names
```

Также прокинул `extra_files` в `_make_zip()` (тот уже принимал, но в `_zip_with_manifest`
раньше не использовался).

## Verification

```
$ python -m pytest tests/unit/test_scorm_parse.py -q
12 passed in 1.85s
```

Полный набор:
- `test_scorm12_explicit_schemaversion_detected` ✅ (после добавления index.html в zip)
- `test_scorm12_no_schemaversion_no_namespace_detected_as_12` ✅
- `test_scorm2004_explicit_schemaversion_detected` ✅
- `test_scorm2004_namespace_only_detected` ✅ (после фикса `_walk`)
- `test_resource_href_with_query_string` ✅
- `test_resource_href_with_hash_fragment` ✅
- `test_resource_href_in_subdirectory` ✅
- `test_resource_href_not_in_zip_marks_entrypoint_missing` ✅
- `test_manifest_missing_imsmanifest_raises` ✅
- `test_manifest_invalid_xml_raises` ✅
- `test_manifest_no_launchable_resource_raises` ✅
- `test_manifest_unsafe_href_raises` ✅

Также:
- `python -m compileall app` → OK
- `python -m alembic -c alembic.ini heads` → `0053` (one head)

## Отчёт

`docs/reports/2026-07-09_p0_hardening_report.md` обновлён:
- Verification section теперь честный: перечисляет что прошло + что упало
  до фикса + что прошло после фикса
- Удалена формулировка "pre-existing qrcode error" — заменена на environment delta:
  на чистом checkout без `npm install` typecheck показывает qrcode module not found;
  если `npm install` пройден (как у Askar'а) — typecheck чистый. Это **не баг кода**,
  это состояние node_modules.

## Коммиты

Один коммит поверх HEAD `da3a7a2`:

```
fix(scorm): detect SCORM 2004 via namespace in attrib + fix test helper
- _walk() now scans el.attrib keys for adlcp_v1p3/adlcp2004 URI
- _zip_with_manifest() accepts extra_files kwarg
- 12/12 unit tests pass
```

Push: `origin/p0-first-tenant-hardening`.

## Что НЕ делалось в этом проходе

- ❌ Integration tests (`test_superadmin_lifecycle` и др.) — требуют Postgres,
  у меня его нет. ConnectionRefusedError ожидаемо. Это окружение, не баг кода.
- ❌ P0.5 Mobile/desktop QA — отложено с прошлого прохода.
- ❌ Re-i18n review (статус/delivery labels hardcoded) — отложено с прошлого прохода.

## PROD state

Ничего не деплоилось. Все правки только в ветке `p0-first-tenant-hardening`.
Прод остаётся в прежнем состоянии.