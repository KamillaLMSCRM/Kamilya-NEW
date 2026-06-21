# Kamilya LMS Foundation — Week 1-2

> Этот файл обновляйте при каждом коммите

## 🟢 Completed
- [x] Монорепо: Nx, pnpm workspaces
- [x] Docker Compose: postgres, redis, minio, api, web
- [x] CI/CD: GitHub Actions (lint, typecheck, test, build)
- [x] DB Schema: Drizzle ORM (tenants, users, courses, modules, lessons, quizzes, progress)
- [x] Alembic: мигарации (initial + tenants, users, user_roles, user_sessions, tenant_settings)
- [x] Auth: login, register, refresh, logout, JWT RS256, roles
- [x] Courses: CRUD API endpoints
- [x] UI Kit: Button, Card, Input, Modal, Badge, Table
- [x] Frontend: login, register, dashboard, landing
- [x] Stores: Zustand authStore
- [x] Libs: api (axios), auth, utils
- [x] Middleware: route protection
- [x] Shared types: Zod schemas
- [x] Test заготовки: auth + courses

## 🔴 Pending (Week 3-4)
- [ ] Module CRUD
- [ ] Lesson CRUD  
- [ ] Content blocks
- [ ] Drag-and-drop reorder
- [ ] Course editor UI (Tiptap)
- [ ] Publish/unpublish flow

## 📦 Structure
```
lms/
├── apps/
│   ├── api/          # FastAPI backend (33 files)
│   └── web/          # Next.js frontend (20 files)
├── packages/
│   ├── db-schema/    # Drizzle ORM (8 files)
│   ├── ui-kit/       # UI components (9 files)
│   ├── shared-types/ # Zod schemas (2 files)
│   └── ml-pipeline/  # AI agents (TBD)
└── infra/
    ├── docker-compose.yml
    ├── Caddyfile
    └── init.sql
Total: 91 project files
```
