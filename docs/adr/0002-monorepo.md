# ADR-0002: Монорепо

**Дата:** 2026-06-21 · **Статус:** Accepted

## Контекст

Kamilya LMS Core — fullstack проект (Next.js + FastAPI + DB).
Нужно выбрать организацию репозиториев.

## Решение

**Монорепо** (single repository с `apps/` и `packages/`).

### Структура

```
lms/
├── apps/
│   ├── web/        # Next.js
│   └── api/        # FastAPI
├── packages/
│   ├── db-schema/  # Drizzle ORM + миграции
│   ├── shared-types/ # Zod ↔ Pydantic codegen
│   ├── ui-kit/     # Design system
│   └── ml-pipeline/ # AI agents, prompts
└── infra/          # Docker, Caddy, Ansible
```

Инструмент: **Nx** (более мощный, чем Turborepo для mixed-stack).

## Обоснование

| Pro | Con |
|-----|-----|
| Атомарные рефакторы (frontend + backend в одном PR) | Медленнее `git clone` для тех, кому нужен только backend |
| Shared types (Pydantic ↔ Zod) | Нужен монорепо-инструмент (Nx) |
| Единый CI | Чуть сложнее initial setup |
| Версионирование простое (один пакет = одна версия) | Может потребовать CODEOWNERS |
| Атомарные PR не теряют context | CI дольше если не распараллелить |

## Альтернативы

| Вариант | Почему отвергли |
|---------|-----------------|
| **Полирепо** (отдельный frontend и backend) | Atomic refactor невозможен, дублирование типов, рассинхрон API |
| **Nx (не Turborepo)** | Nx — для mixed stack (TS + Python); Turborepo только JS/TS |
| **Pants / Bazel** | Overkill для 5-10 инженеров |
| **Nx Cloud** (платный) | Бюджет — $99/мес не нужен при таких объемах |

## Последствия

- Nx-генераторы для новых модулей (`nx g @nx/react:app`, `nx g @nx/python:app`)
- Workspace-wide `tsconfig.base.json` для path aliases (`@lms/ui-kit`, `@lms/shared-types`)
- Python virtualenv в корне (`lms.venv/`), shared requirements.txt
- CI матрица: lint + typecheck + test для каждого workspace project
- Код-ревью: вся PR в одном review (frontend + backend), рекомендуется ревью от 1 frontend + 1 backend

**Принято:** 2026-06-21
