# Mobile / desktop QA report — P0 follow-up

**Дата:** 2026-07-09
**Статус:** ⚠️ Deferred — нет работающего dev-stack'а в этой сессии
**Ветка:** `p0-followup-training-log-scorm-mobile-ci`

## TL;DR

Live mobile/desktop QA (Playwright screenshots, реальный UI) **не выполнено** в этом проходе. В этой среде нет поднятого `apps/api` (uvicorn) + `apps/web` (Next.js dev) + Postgres + Storage, поэтому Playwright через MCP получит либо белые страницы, либо fallback'и авторизации.

Это **тот же статус**, что и `P0.5 Mobile/desktop QA` в предыдущем эпике (`docs/reports/2026-07-09_p0_hardening_report.md`). План ниже — это roadmap для следующего захода с поднятым стэком.

## Что нужно прогнать

### Viewports

| Viewport | Разрешение | Use case |
|---|---|---|
| Desktop | `1280×800` | Admin/HR work, training log, superadmin |
| Mobile | `390×844` | iPhone 14/15 baseline, learner daily usage |
| Tablet | `768×1024` | Kiosk identify / course open / logout |

### Flows (13 штук из ТЗ)

| # | Flow | URL | Viewport | Priority |
|---|---|---|---|---|
| 1 | Login / email OTP | `/login` | desktop + mobile | high |
| 2 | Trial tenant admin dashboard | `/admin` | desktop + mobile | high |
| 3 | Onboarding checklist | `/admin` (widget) | desktop | medium |
| 4 | Staff import page | `/admin/staff` | desktop + mobile | high |
| 5 | Courses list + SCORM import card | `/courses` (admin) | desktop + mobile | high |
| 6 | Training log | `/admin/training-log` | desktop only | high |
| 7 | Learner my-courses | `/my-courses` | desktop + mobile | high |
| 8 | Native course player | `/courses/[id]` | desktop + mobile | high |
| 9 | SCORM player | `/courses/[id]` (scorm delivery) | desktop + mobile | high |
| 10 | Quiz take | `/quizzes/[id]/take` | desktop + mobile | high |
| 11 | Certificate view | `/certificates` | desktop + mobile | medium |
| 12 | Kiosk identify + course open | `/kiosk/[token]` | tablet (768×1024) | high |
| 13 | Logout from shared device | `/kiosk/[token]` | tablet | high |

### Что искать

- **Горизонтальный скролл** (типичная проблема таблиц на mobile — проверять Training log, my-courses)
- **Перекрытие кнопок** (toolbar в admin dashboard, sidebar overlay)
- **Tap targets** < 44×44 px (Apple HIG minimum)
- **Text overflow** (длинные имена курсов, длинные ФИО)
- **Sidebar/topbar** ломаются на tablet/mobile
- **Logout/loading hang** на kiosk (важно — shared device)
- **CSP-блокировка SCORM launch shell** (Block 2 добавил Content-Security-Policy — нужно проверить что runtime всё ещё работает)

### Screenshots (куда складывать)

```
docs/reports/mobile-qa-2026-07-09/
├── desktop/
│   ├── 01-login.png
│   ├── 02-admin-dashboard.png
│   ├── ...
├── mobile/
│   ├── 01-login.png
│   ├── ...
└── tablet/
    ├── 12-kiosk-identify.png
    └── ...
```

## Как поднять dev-stack

```bash
# Terminal 1: Postgres + storage
docker compose up postgres minio redis -d

# Terminal 2: backend
cd apps/api
python -m alembic upgrade head
uvicorn app.main:app --reload --port 8000

# Terminal 3: frontend
cd apps/web
npm install        # if node_modules is stale
npm run dev        # http://localhost:3000

# Terminal 4: seed data (optional)
cd apps/api
python -m scripts.seed_demo_tenant
```

После подъёма проверить `curl http://localhost:8000/health` и `curl http://localhost:3000/`.

## Как прогонять через Playwright MCP

```powershell
# Mobile viewport
$payload = @{
  url = "http://localhost:3000/login"
  viewport = @{ width = 390; height = 844 }
} | ConvertTo-Json
mavis mcp call playwright browser_navigate $payload

# Screenshot
mavis mcp call playwright browser_screenshot '{"filename":"01-login-mobile.png"}'
```

## Что уже защищено этим проходом (без live QA)

Block 1 (training-log) и Block 2 (SCORM security) — это изменения которые
**уменьшают** вероятность багов на mobile/desktop:

- **Block 1:** computed_status теперь честный, frontend использует его в
  badge — на mobile не будет пустых/неправильных статусов.
- **Block 2:** launch shell теперь html.escape() + CSP — даже если найду
  broken layout, XSS через title пакета не сработает.

## Известные потенциальные проблемы (без проверки)

- **Training log table** (`/admin/training-log`): на mobile таблица может
  потреблять горизонтальный скролл. В коде есть `<div className="overflow-x-auto">`
  вокруг `<Table>` (page.tsx:313), но tap targets в ячейках не оптимизированы.
- **Sidebar** на tablet (768×1024): если он collapsible, может перекрывать
  контент на узких viewport'ах.
- **Kiosk identify** на tablet: в landscape-режиме iframe + bar могут
  налезать друг на друга.

Эти риски — кандидаты на ручной QA в следующем заходе.

## References

- ТЗ: `~/Downloads/Telegram Desktop/2026-07-09_p0_followup_training-log-scorm-mobile-ci.md`
- Прошлый P0.5 deferral: `docs/reports/2026-07-09_p0_hardening_report.md#p05--mobile-desktop-qa--deferred`
- Block 1 (training-log): commit `e1eab7f`
- Block 2 (SCORM security): commit `3cc7617`