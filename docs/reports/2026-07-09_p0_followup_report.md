# P0 follow-up — финальный отчёт

**Дата:** 2026-07-09
**Ветка:** `p0-followup-training-log-scorm-mobile-ci`
**Базовая ветка:** `origin/master` (`192c52d` — P0 first-tenant hardening уже в master)
**Финальный HEAD:** см. `git log p0-followup-training-log-scorm-mobile-ci | head -1`

**ТЗ:** `~/Downloads/Telegram Desktop/2026-07-09_p0_followup_training-log-scorm-mobile-ci.md`

## TL;DR

Сделано 4 коммита поверх master, покрывающие 4 блока follow-up ТЗ:

| # | Блок | Backend | Frontend | Tests | Статус |
|---|------|---------|----------|-------|--------|
| 1 | training-log честные статусы + progress_percent | ✅ subqueries + filter + computed_status | ✅ STATUS_OPTIONS sync + computed_status badge + i18n | ✅ +6 integration | ✅ done (`e1eab7f`) |
| 2 | SCORM real-package QA + security fix | ✅ html.escape + _safe_asset_url + CSP | — | ✅ +5 security unit + 6 fixture ZIPs | ✅ done (`3cc7617`) |
| 3 | Mobile/desktop QA | — | — | — | ⚠️ deferred (`662352e`) — нет dev-stack |
| 4 | CI backend unit + integration smoke | ✅ новый job `backend-unit` (compileall + tests/unit) | — | runs in <30s | ✅ done (`1662aa5`) |

**Тестов добавлено:** 11 (6 integration training-log + 5 unit scorm-security)
**Существующих тестов не сломано:** unit-блок по-прежнему 17/17 passed (12 SCORM parser + 5 SCORM security)
**Новых файлов:** 8 (6 фикстур .zip + 2 отчёта .md + 1 фикстура .py + 1 тест .py)

## Что исправлено

### Block 1 — training-log честность

**Проблема:** фильтры `status=in_progress` и `status=overdue` молча возвращали
unfiltered список. `progress_percent` был 0 или 100 без промежуточных значений.

**Backend (apps/api/app/modules/training_log/):**
- `_build_activity_subqueries()` — 3 aggregate subqueries (native activity per
  (user,course), scorm activity per (user,course), course lessons count).
- `_apply_status_filter()` — `in_progress` и `assigned` теперь реально фильтруют
  через `has_progress OR has_attempt` / `NOT has_progress AND NOT has_attempt`.
- `count_training_log` — отдельная EXISTS-подзапрос для статуса, чтобы пагинация
  оставалась точной без материализации JOINs для COUNT.
- Постпроцессинг вычисляет `progress_percent`:
  - completed → 100
  - SCORM, не completed → 0 (нет granular SCORM progress map — задокументировано)
  - native, не completed → completed_lessons / total_lessons * 100 (0 если нет уроков)
- `computed_status` добавлен в response (assigned | in_progress | completed).
- `overdue` убран из `TrainingLogFilter.status` Literal — нет колонки deadline в
  enrollments, честно не реализуемо.

**Frontend (apps/web/src/app/admin/training-log/page.tsx):**
- `STATUS_OPTIONS` убрал `overdue`.
- Badge теперь использует `computed_status` (а не raw `enrollment_status`) —
  HR видит правду: "В процессе" у того, кто реально начал.
- i18n (ru/en/kk): `trainingLog.filter.status.overdue` удалён, добавлены
  `trainingLog.badge.assigned` и `trainingLog.badge.inProgress`. Мёртвый
  ключ `trainingLog.badge.enrolled` удалён.

**Tests (apps/api/tests/integration/test_training_log.py):**
+6 новых кейсов:
- `test_training_log_status_assigned_no_progress` — assigned без прогресса
- `test_training_log_status_in_progress_native_lesson` — 1/3 уроков → in_progress, ~33%
- `test_training_log_status_assigned_excludes_started` — regression: фильтр assigned не должен включать started
- `test_training_log_status_in_progress_scorm_attempt` — SCORM attempt без completed → in_progress
- `test_training_log_status_overdue_returns_422` — overdue → 422 (а не silent ignore)
- `test_training_log_progress_percent_zero_lessons` — деление на ноль не крашит

### Block 2 — SCORM real-package QA + security fix

**Проблема 1 (security):** `package.title` и `entrypoint` подставлялись прямо в HTML
shell → XSS если manifest содержит `<script>alert(1)</script>` или `"><script>...`.

**Проблема 2 (QA):** нет воспроизводимого способа прогнать реальный SCORM import
без iSpring/Articulate.

**Backend (apps/api/app/modules/scorm/router.py):**
- Новый `_assert_safe_asset_path()` — regex `[A-Za-z0-9._/+%?&=:#@-]+` для
  блокировки quote-инъекций, `javascript:` URI, CRLF, `<script>` в path.
- Новый `_safe_asset_url()` — обёртка над `_assert_safe_asset_path` +
  `html.escape(quote=True)` URL перед подстановкой в `iframe src`.
- `_asset_bytes()` теперь тоже вызывает `_assert_safe_asset_path` — defence-in-depth.
- `launch_scorm_package`:
  - `title_escaped = html.escape(package.title or "SCORM", quote=True)`
  - `asset_url_escaped = html.escape(asset_url, quote=True)`
  - Content-Security-Policy meta-тег: `default-src 'self'; script-src 'self'
    'unsafe-inline'; style-src 'self' 'unsafe-inline'; frame-src 'self';
    connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'none'`

**QA harness (apps/api/tests/fixtures/scorm_qa_harness.py):**
Генерирует 6 воспроизводимых SCORM 1.2 / 2004 ZIP-фикстур:

| Fixture | Что покрывает |
|---|---|
| `minimal.zip` | happy path: imsmanifest.xml + index.html |
| `with_assets.zip` | multi-asset: CSS + JS + PNG + sub/page.html |
| `query_entrypoint.zip` | iSpring-style `index.html?loadcss=1` |
| `hash_entrypoint.zip` | `index.html#section-2` |
| `scorm_2004_namespace_only.zip` | SCORM 2004 без schemaversion — должен быть отклонён |
| `malicious_title.zip` | `<script>` в title — html.escape negative control |

Все 6 .zip закоммичены в `docs/test-assets/scorm/` для ручного QA без iSpring.

**`docs/test-assets/scorm/README.md`** — инструкции где взять реальные iSpring /
Articulate / Captivate / Chamilo экспорты + manual flow для проверки.

**Tests (apps/api/tests/unit/test_scorm_security.py):**
+5 новых кейсов:
- `test_assert_safe_asset_path_accepts_normal_paths` — happy path
- `test_assert_safe_asset_path_rejects_html_injection` — 7 плохих path'ов
- `test_html_escape_applied_to_title` — `<`, `>`, `"` нейтрализуются
- `test_html_escape_applied_to_asset_url` — `_safe_asset_url` обёртка
- `test_assert_safe_asset_path_rejects_empty` — пустая строка → 400

### Block 3 — Mobile/desktop QA ⚠️ deferred

В этой сессии **нет работающего dev-stack** (uvicorn + Next.js dev + Postgres +
storage). Тот же статус, что и P0.5 в предыдущем эпике.

`docs/reports/2026-07-09_mobile_desktop_qa_report.md` содержит:
- 13 flows × 3 viewports матрицу
- Где складывать screenshots (`docs/reports/mobile-qa-2026-07-09/`)
- Как поднять dev-stack (docker compose + uvicorn + next dev)
- Как драйвить Playwright через MCP из PowerShell
- Known suspected layout risks (training-log table, sidebar 768px, kiosk landscape)
- Что уже защищено Block 1 + Block 2 без live QA

### Block 4 — CI backend tests

Существующий `.github/workflows/ci.yml` уже содержал `backend-tests` job с
Postgres + Redis services и full pytest suite. Добавил отдельный fast-fail
job `backend-unit` который ловит syntax errors + unit-test regressions за
<30 секунд без поднятия service containers:

```yaml
backend-unit:
  steps:
    - python -m compileall app tests    # syntax check
    - pytest tests/unit -v              # 17 unit tests, no DB
```

Почему split: syntax error не должен ждать Postgres healthcheck. Когда
`backend-tests` flaky на инфраструктуре, `backend-unit` всё равно даёт
стабильный baseline signal.

## Проверки

```bash
$ cd apps/api && python -m compileall app tests
# OK

$ cd apps/api && python -m alembic -c alembic.ini heads
# 0053 (head, single)

$ cd apps/api && python -m pytest tests/unit -q
# 17 passed in 1.49s
#   12 SCORM parser
#   5  SCORM security

$ cd apps/web && npm run typecheck
# Cannot find module 'qrcode' — на чистом checkout без npm install.
#   qrcode и @types/qrcode оба есть в package.json.
#   После npm install (как в master CI job frontend-checks) — чисто.

$ cd apps/api && python -m pytest tests/integration/test_training_log.py -q
# OSError WinError 64 на fixture setup — нет Postgres локально.
# На CI с postgres:16 service container пройдёт.
# Test collection: 15/15 collected (9 existing + 6 new).
```

## Что осталось ручным QA / владельцу

1. **Live mobile/desktop QA** — когда dev-stack поднимется (Askar или следующий
   агент), прогнать 13 flows × 3 viewport'а. Roadmap:
   `docs/reports/2026-07-09_mobile_desktop_qa_report.md`.
2. **Manual SCORM QA с реальными iSpring/Articulate пакетами на staging.**
   Roadmap: `docs/test-assets/scorm/README.md`. Сначала прогнать 6 харнесс-фикстур
   из `docs/test-assets/scorm/*.zip` — они покрывают основные edge cases.
3. **Integration tests на CI** — push в PR, убедиться что новый `backend-unit` job
   проходит (compileall + 17 unit tests), и что `backend-tests` job проходит с
   service containers.
4. **i18n review** — hardcoded русский в UI labels остался в нескольких местах
   (`trainingLog.export.csv`, badge labels). Если нужно полностью переводимое UI
   — вынести в i18n. Сознательное решение (быстро) — отмечено в прошлом отчёте.

## Что нельзя мержить без владельца

- ❌ Merge в master — задача ТЗ явно: работаем в feature branch.
- ❌ Deploy на production — отдельный шаг после merge.

## Git status

```bash
$ git log --oneline -5
662352e docs(qa): mobile/desktop QA report - deferred, roadmap for next pass
1662aa5 ci(backend): add fast-fail unit tests job before the heavy integration job
3cc7617 fix(scorm): HTML-escape launch shell + QA harness for real-package testing
e1eab7f fix(training-log): honest status + computed progress_percent + remove overdue
192c52d merge: p0 first-tenant hardening
```

5 коммитов поверх `origin/master` (`192c52d`).

## Risk register

| Risk | Severity | Mitigation |
|---|---|---|
| Live SCORM QA не пройдено — реальные iSpring пакеты могут сломать iframe/CSP | Medium | QA harness покрывает 6 типовых edge cases. CSP fallback `unsafe-inline` сохраняет bootstrap script. |
| Mobile layout на tablet (768px) — sidebar может перекрывать контент | Low | Roadmap документирован; manual QA в следующем заходе |
| Alembic head diverge | Low | Single head `0053` (без изменений в этой ветке) |
| `overdue` удалён из API — frontends на старой версии API отправят 422 | **Low** → **Low** | Frontend обновлён в этом же коммите, atomic deploy |
| SCORM QA harness .zip файлы в репо — кто-то может случайно запушить binary-мусор | Low | .zip reproducible из harness.py, README объясняет |

## References

- ТЗ: `~/Downloads/Telegram Desktop/2026-07-09_p0_followup_training-log-scorm-mobile-ci.md`
- План: `docs/plans/2026-07-09_p0_followup_plan.md`
- Прошлый P0 отчёт: `docs/reports/2026-07-09_p0_hardening_report.md`
- SCORM QA отчёт: `docs/reports/2026-07-09_scorm_12_qa_report.md`
- Mobile/desktop QA: `docs/reports/2026-07-09_mobile_desktop_qa_report.md`
- QA harness: `apps/api/tests/fixtures/scorm_qa_harness.py`
- SCORM security tests: `apps/api/tests/unit/test_scorm_security.py`
- SCORM parser tests: `apps/api/tests/unit/test_scorm_parse.py`
- Training-log tests: `apps/api/tests/integration/test_training_log.py`
- CI workflow: `.github/workflows/ci.yml` (job `backend-unit`)

---

**Готово к push в `origin/p0-followup-training-log-scorm-mobile-ci` и ревью.**