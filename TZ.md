# Техническое задание: Kamilya LMS Core v1.0

> **Версия:** 1.0 · **Дата:** 21 июня 2026 · **Статус:** готово к разработке
> **Целевой исполнитель:** AI-агент средней мощности (Qwen 3.5 / DeepSeek V3 / Claude Sonnet 4) под супервизией человека-архитектора.
> **Срок реализации MVP:** 12 недель (3 месяца). Beta → 4 недели. GA → 8 недель.

---

## Содержание

1. [Контекст и цели](#1-контекст-и-цели)
2. [Стейкхолдеры и роли пользователей](#2-стейкхолдеры-и-роли-пользователей)
3. [Функциональные требования](#3-функциональные-требования)
4. [Нефункциональные требования](#4-нефункциональные-требования)
5. [Технологический стек](#5-технологический-стек)
6. [Архитектура](#6-архитектура)
7. [Модель данных](#7-модель-данных)
8. [REST API контракт](#8-rest-api-контракт)
9. [Ключевые UI-потоки](#9-ключевые-ui-потоки)
10. [AI-интеграция (Qwen)](#10-ai-интеграция-qwen)
11. [Безопасность и приватность](#11-безопасность-и-приватность)
12. [Performance, кэш, real-time](#12-performance-кэш-real-time)
13. [Локализация (i18n)](#13-локализация-i18n)
14. [Тестирование и качество](#14-тестирование-и-качество)
15. [Этапы разработки (12 недель)](#15-этапы-разработки-12-недель)
16. [Definition of Done](#16-definition-of-done)
17. [Риски и mitigation](#17-риски-и-mitigation)
18. [Приложения](#18-приложения)

---

## 1. Контекст и цели

### 1.1 Что строим

Полноценный LMS-модуль как **первоклассный продукт**, а не обёртка над Chamilo.
Заменяет Chamilo 2.0 во всех точках интеграции Kamilya.

**Не входит в скоуп v1.0:**
- Мобильные приложения (iOS/Android) — только web, адаптивный дизайн
- SCORM 1.2/2004 — поддержка будет в v1.1
- xAPI / LRS — v1.1
- Live streaming (вебинары) — v2.0
- Marketplace курсов (B2C) — отдельный продукт
- Offline-режим (PWA) — v1.1

### 1.2 Ключевые принципы

1. **AI-first, не AI-feature.** Структура курса, контент, тесты, рекомендации — всё генерируется. LMS не хранит статичный контент дольше, чем нужно для отдачи студенту.
2. **Tenant-изолировано с первого коммита.** Kamilya = multi-tenant SaaS. LMS = часть платформы, не отдельный сервис с cross-tenant joins.
3. **Прогресс первичен.** Без понимания, что студент прошёл/не прошёл, LMS — это просто файлообменник. Трекинг событий — на уровне аналитической платформы.
4. **Дешёвая генерация, дорогая персонализация.** AI-генерация должна быть дешёвой (≤ 0.10 USD за курс), но UI, который показывает результат, должен быть качественным.
5. **Не чат.** Kamilya — не чат-бот. LMS — это структурированный learning experience.

### 1.3 Метрики успеха (для v1.0 GA)

| Метрика | Цель |
|---------|------|
| Time to first course (от регистрации до первого курса студента) | ≤ 30 минут |
| AI generation cost per course | ≤ 0.10 USD |
| P50 page load (курс студента) | ≤ 1.0 с |
| P95 page load | ≤ 2.5 с |
| Uptime (включая плановые) | ≥ 99.5% |
| Concurrent active learners | 5000 |
| WCAG AA score | 100% ключевых экранов |
| Languages at GA | RU (primary), KK, EN |

---

## 2. Стейкхолдеры и роли пользователей

### 2.1 Стейкхолдеры

| Роль | Кто | Интересы |
|------|-----|----------|
| Product Owner | Kamilya Product | Time-to-market, scope |
| Tech Lead | TBD | Архитектура, code review |
| Backend (1-2) | TBD | API, AI pipeline, БД |
| Frontend (1-2) | TBD | UI/UX, производительность |
| ML Engineer (0.5) | TBD | Qwen-интеграция, embeddings |
| **Суперадмин Kamilya** | Kamilya | Tenants, глобальные настройки |
| **Tenant-админ** | HR / L&D компании | Курсы, сотрудники, аналитика |
| **Преподаватель** (опц.) | Внутренний эксперт | Создание курсов, проверка AI |
| **Студент** | Сотрудник компании | Прохождение курсов, прогресс |
| **Гость** (опц.) | Неавторизованный | Лендинг курса (preview) |

### 2.2 Permission matrix

| Действие | Superadmin | Tenant Admin | Teacher | Student |
|----------|------------|--------------|---------|---------|
| Управление тенантами | ✅ | ❌ | ❌ | ❌ |
| Создавать курсы | ❌ | ✅ | ✅ | ❌ |
| Редактировать курсы | ❌ | ✅ (свои) | ✅ (свои) | ❌ |
| Генерировать AI-курсы | ❌ | ✅ | ✅ | ❌ |
| Видеть всех сотрудников тенанта | ❌ | ✅ | ❌ | ❌ |
| Записывать на курс | ❌ | ✅ | ❌ | ❌ |
| Проходить курс | ❌ | ✅ | ✅ | ✅ |
| Видеть свой прогресс | ❌ | ❌ | ✅ (свой) | ✅ (свой) |
| Видеть прогресс сотрудников | ❌ | ✅ (анонимизировано) | ❌ | ❌ |
| Биллинг тенанта | ❌ | ✅ | ❌ | ❌ |
| Глобальная аналитика | ✅ | ❌ | ❌ | ❌ |

---

## 3. Функциональные требования

### 3.1 Скоуп v1.0 (MUST)

#### F-001: Аутентификация
- JWT (RS256), интеграция с Kamilya auth (Telegram, email)
- Refresh token rotation (sliding window, 30 дней)
- 2FA опционально (TOTP, через Telegram код)
- Сессия: access 15 мин, refresh 30 дней
- Выход с blacklist refresh token

#### F-002: Управление курсами (CRUD)
- Создание курса вручную или через AI
- Структура: Course → Module → Lesson → Content Block
- Типы content blocks: text (Markdown), video (HLS), PDF embed, quiz, assignment (text), file attachment
- Drag-and-drop reorder для модулей и уроков
- Публикация / unpublish (видимость для студентов)
- Версионирование контента (snapshot при публикации)

#### F-003: AI-генерация курсов
- Pipeline: документы → Architect (Qwen) → структура → Writer (Qwen) → контент → Reviewer (Qwen) → ready
- WebSocket / SSE прогресс генерации
- Cancel generation
- Edit generated content inline
- Re-generate specific module/lesson with feedback
- Generation history (audit log)

#### F-004: Прохождение курса (Student UX)
- Course player: linear navigation (next/prev) + sidebar TOC
- Mark as complete (auto on video end / quiz pass / scroll-end)
- Resume from last position
- Notes per lesson (private to student)
- Bookmarks
- Estimated time remaining

#### F-005: Quizzes / Assessment
- Types: single choice, multiple choice, true/false, short answer, matching, ordering
- Auto-grading (single/multi/TF/matching) + manual (short answer)
- Pass threshold (default 80%, configurable)
- Time limit (опционально)
- Attempt limit (опционально, default 3)
- Question pool (random selection из N вопросов)
- Show correct answers after submission
- Detailed per-question feedback (правильно/неправильно + объяснение)

#### F-006: Enrollments
- Tenant admin / teacher записывает студента на курс
- Self-enrollment (опционально, настройка тенанта)
- Bulk enroll (CSV upload)
- Auto-enroll by position/department
- Unenroll (с подтверждением)

#### F-007: Прогресс и аналитика
- Per-course progress: %, time spent, last accessed
- Per-lesson progress: completed, time spent
- Per-student progress: все курсы, completion rate, time
- Tenant-level dashboard: enrollments by course, completion rate, time-to-completion
- Cohort analysis (опц. v1.1)
- Export CSV / Excel

#### F-008: Видео-хостинг
- Upload MP4 → transcoding → HLS (через FFmpeg, см. § 5.7)
- Adaptive bitrate (3 качества: 360p / 720p / 1080p)
- Watermark (email студента + timestamp)
- DRM-free в v1.0 (подготовка к Widevine в v1.1)
- Subtitle upload (VTT)

#### F-009: Real-time collaboration
- Live progress updates (presence: кто сейчас на каком уроке)
- Comment threads per lesson (text-only в v1.0, markdown в v1.1)
- Notifications (in-app, опц. email): новый комментарий, новый урок, дедлайн

#### F-010: Multi-tenancy
- Row-level security на все таблицы
- Tenant isolation enforced на уровне ORM (Drizzle middleware)
- Per-tenant settings (logo, color, language default)
- Per-tenant feature flags (есть courses, есть analytics, есть video)

#### F-011: Биллинг и подписки
- Plans: starter / business / enterprise
- Subscription lifecycle: trial → active → suspended
- Usage tracking (AI generations, storage, active learners)
- Invoices (отдельный модуль Kamilya, не часть LMS)

#### F-012: Audit log
- Все значимые действия (course create, publish, enroll, role change, billing)
- Immutable log (append-only)
- Per-tenant view + superadmin global view
- Export

#### F-013: Поиск
- Full-text по курсам, урокам, документам
- Filter: по тенанту, типу, дате, автору
- Highlights в результатах

#### F-014: Уведомления
- In-app notification center
- Email (через Kamilya email service)
- Telegram (через Kamilya bot, opt-in)
- Types: assignment due, course completed, comment, certificate earned

#### F-015: i18n
- RU (primary, 100% переведено)
- KK (казахский, ≥ 80% к v1.0)
- EN (≥ 90% к v1.0)
- Right-to-left ready (структура, без активной разработки арабского/иврита в v1.0)
- Числа/даты/валюта — локаль-зависимо

### 3.2 Скоуп v1.1 (SHOULD, не блокирует GA)

- SCORM 1.2/2004 импорт/экспорт
- xAPI statements
- Peer review / assignment grading by teacher
- Certificate generation (PDF) с QR-кодом для верификации
- Webhooks (outbound) для интеграций (Slack, Teams, SAP)
- Live streaming (через Mediasoup/Jitsi)
- Discussion forum per course
- Wiki per course

### 3.3 Скоуп v2.0 (WON'T, потом)

- Live virtual classrooms (Zoom-стиль)
- Mobile native apps
- Marketplace (B2C продажа курсов)
- Skills graph + рекомендательная система
- AI-тьютор в чате
- Marketplace для шаблонов курсов

---

## 4. Нефункциональные требования

### 4.1 Производительность

| Метрика | Цель | Способ измерения |
|---------|------|-------------------|
| P50 page load (студент) | ≤ 1.0 с | RUM, Sentry Performance |
| P95 page load (студент) | ≤ 2.5 с | RUM |
| P50 API response | ≤ 200 мс | server timing |
| P95 API response | ≤ 800 мс | server timing |
| AI generation time (1 курс, 5 модулей) | ≤ 180 с | pipeline metrics |
| WebSocket latency | ≤ 100 мс | server metrics |
| Видео start time | ≤ 2 с | RUM |

### 4.2 Доступность (a11y)

- WCAG 2.1 AA
- Keyboard navigation на всех интерактивных элементах
- Screen reader тестирование (NVDA / VoiceOver)
- Color contrast ≥ 4.5:1
- Focus rings visible
- Alt text обязателен для всех изображений

### 4.3 Безопасность (см. § 11)

- OWASP Top 10 compliance
- CSP headers (no inline scripts, no eval)
- HSTS + HTTPS only
- Rate limiting (per IP, per user)
- SQL injection prevention (parameterized queries)
- XSS prevention (escape all user content)
- CSRF tokens на state-changing operations
- File upload validation (MIME, magic bytes, size, virus scan)
- Watermark на видео

### 4.4 Надёжность

- Uptime SLA: 99.5% (включая плановые)
- RTO (Recovery Time Objective): 4 часа
- RPO (Recovery Point Objective): 1 час
- Backups: ежедневно, retention 30 дней
- Disaster recovery: backup в отдельном регионе

### 4.5 Масштабирование

- 5 000 concurrent active learners на v1.0
- 100 000 enrolled learners на тенант
- 10 000 курсов на тенант
- Horizontal scaling (stateless API, sticky sessions для WebSocket)

### 4.6 Наблюдаемость

- Structured logging (JSON)
- Metrics (Prometheus-compatible)
- Distributed tracing (OpenTelemetry)
- Error tracking (Sentry)
- Audit log (см. F-012)
- Dashboards: Grafana (или эквивалент)

### 4.7 Совместимость браузеров

- Chrome 110+
- Firefox 110+
- Safari 16+
- Edge 110+
- Mobile: iOS Safari 16+, Chrome Android 110+

---

## 5. Технологический стек

### 5.1 Обоснование выбора

**Принцип:** максимум **TypeScript end-to-end** (один язык = меньше context switching),
**PostgreSQL single source of truth**, **AI-first** (Qwen — уже работает в Kamilya).

### 5.2 Frontend

| Категория | Выбор | Обоснование |
|-----------|-------|-------------|
| Framework | **Next.js 14 (App Router)** | SSR, RSC, server actions, уже в Kamilya |
| Language | **TypeScript 5.4 (strict)** | type safety end-to-end |
| Styling | **Tailwind CSS 3.4** | уже в Kamilya, utility-first |
| Component primitives | **Radix UI** | unstyled, accessible (WCAG AA из коробки) |
| Rich text editor | **Tiptap 2** | ProseMirror-based, extensible, AI-friendly (commands) |
| Forms | **react-hook-form + Zod** | type-safe validation |
| State | **Zustand** (client) + **TanStack Query** (server) | минимальный boilerplate |
| Video player | **Mux Player** или **Video.js** | HLS out of the box, custom skin |
| Whiteboard | **tldraw** | для интерактивных уроков v1.1 |
| Charts | **Recharts** | для аналитики |
| i18n | **next-intl** | App Router compatible, type-safe |
| Tables | **TanStack Table** | headless, virtualization |
| Date | **date-fns** | tree-shakeable |
| File upload | **react-dropzone** + custom multipart | прогресс, retry |
| Testing | **Vitest** + **Playwright** | unit + e2e |

### 5.3 Backend

| Категория | Выбор | Обоснование |
|-----------|-------|-------------|
| Language | **Python 3.12** | уже в Kamilya, AI-ecosystem |
| Framework | **FastAPI 0.110+** | async, type hints, OpenAPI из коробки |
| ORM | **SQLAlchemy 2.0 (async)** | mature, async support |
| Migrations | **Alembic** | стандарт в Python |
| Validation | **Pydantic v2** | type safety, perf |
| Auth | **PyJWT** + **python-jose** (optional) | RS256, RFC 7519 |
| Task queue | **Celery** + **Redis** | mature, scalable |
| WebSocket | **FastAPI native** (WebSocket route) | no extra dep |
| Cache | **Redis** | sessions, rate limits, hot data |
| File storage | **S3-compatible (AWS S3 / MinIO)** | videos, attachments |
| Search | **PostgreSQL full-text + pgvector** | one DB, no extra dep |
| API docs | **OpenAPI 3.1** (auto-generated) | Swagger UI, codegen |
| Testing | **pytest** + **pytest-asyncio** | standard |

### 5.4 Database

| Категория | Выбор | Обоснование |
|-----------|-------|-------------|
| Primary | **PostgreSQL 16** | уже в Kamilya, JSONB, FTS, pgvector, RLS |
| Migration | **Alembic** | SQLAlchemy native |
| ORM | **Drizzle** (TypeScript) для read-views, **SQLAlchemy** для write | оптимизация под стек |
| Connection pool | **PgBouncer** (опц., при > 100 RPS) | reduce PG connections |

### 5.5 AI / ML

| Категория | Выбор | Обоснование |
|-----------|-------|-------------|
| LLM | **Qwen 3.5 (через WireGuard)** | уже работает, fine-tuned на казахский |
| Embeddings | **Qwen3-Embedding-8B** | уже работает |
| Vector store | **pgvector** | один PostgreSQL, не отдельный Qdrant |
| Image generation | **не входит в v1.0** | дорого, не критично |
| TTS | **не входит в v1.0** | v1.1 если спрос |

### 5.6 Infrastructure

| Категория | Выбор | Обоснование |
|-----------|-------|-------------|
| Hosting | **VPS (Hetzner/Contabo)** | уже работает, Kamilla дешевле AWS |
| Containerization | **Docker + Docker Compose** | v1.0; K8s в v2.0 |
| Reverse proxy | **Caddy 2** (preferred) или Nginx | auto-TLS, simple config |
| CI/CD | **GitHub Actions** | бесплатно, уже интегрирован |
| Мониторинг | **Prometheus + Grafana** | OSS, self-hosted |
| Logs | **Loki + Promtail** | OSS |
| Errors | **Sentry** (self-hosted) | OSS версия |
| Backups | **restic + B2** | encrypted, incremental |

### 5.7 Video pipeline

| Компонент | Выбор | Примечание |
|-----------|-------|-----------|
| Upload | Direct PUT to S3 (multipart) | presigned URL |
| Transcoding | **FFmpeg** в worker pool (Celery) | HLS, 3 битрейта |
| Storage | S3 + CloudFront CDN (опц. v1.1) | v1.0 отдаём через API |
| Player | Mux Player / Video.js | adaptive HLS |

**FFmpeg команда** (для worker):
```bash
ffmpeg -i input.mp4 \
  -filter_complex "[0:v]split=3[v1][v2][v3];[v1]scale=w=640:h=360[v1out];[v2]scale=w=1280:h=720[v2out];[v3]scale=w=1920:h=1080[v3out]" \
  -map "[v1out]" -c:v:0 libx264 -b:v:0 800k \
  -map "[v2out]" -c:v:1 libx264 -b:v:1 2500k \
  -map "[v3out]" -c:v:2 libx264 -b:v:2 5000k \
  -map 0:a -c:a aac -b:a 128k \
  -f hls -hls_time 6 -hls_playlist_type vod \
  -hls_segment_filename "stream_%v/data%03d.ts" \
  -master_pl_name master.m3u8 \
  -var_stream_map "v:0,a:0,agroup:aud,name:360p v:1,a:0,agroup:aud,name:720p v:2,a:0,agroup:aud,name:1080p" \
  stream_%v/playlist.m3u8
```

---

## 6. Архитектура

### 6.1 High-level

```
                       ┌──────────────────────────────────────────┐
                       │          Cloudflare (CDN + WAF)         │
                       │   app.lms.kml.kz → Kamilya reverse proxy │
                       │   cdn.lms.kml.kz → video CDN            │
                       └─────────┬────────────────────────────────┘
                                 │
                ┌────────────────┴────────────────┐
                │                                 │
       ┌────────▼─────────┐              ┌────────▼─────────┐
       │  Next.js 14 web  │              │  Next.js 14 admin │
       │  (student/teacher)│              │  (tenant admin)   │
       │  Port 3000       │              │  Port 3001         │
       └────────┬─────────┘              └────────┬──────────┘
                │                                  │
                └─────────────┬────────────────────┘
                              │
                ┌─────────────▼──────────────┐
                │   FastAPI backend (8000)    │
                │   - REST API                │
                │   - WebSocket               │
                │   - OpenAPI docs at /docs   │
                └────┬────────┬────────┬─────┘
                     │        │        │
            ┌────────▼─┐  ┌───▼────┐  ┌▼──────────┐
            │PostgreSQL│  │ Redis  │  │ S3 (MinIO)│
            │  16 +    │  │ 7.x    │  │           │
            │ pgvector │  │        │  │           │
            └──────────┘  └────────┘  └───────────┘
                                    │
                            ┌───────▼────────┐
                            │ Celery workers │
                            │ - AI pipeline  │
                            │ - Video transcode│
                            │ - Email/Telegram│
                            └───────┬────────┘
                                    │
                            ┌───────▼────────┐
                            │ Qwen 3.5 (VPS) │
                            │ 10.66.66.7     │
                            └────────────────┘
```

### 6.2 Монорепо vs полирепо

**Решение: монорепо** (Nx или Turborepo).

Обоснование:
- Frontend и backend разделяют типы (Pydantic ↔ Zod через codegen)
- Унифицированные CI
- Проще atomic refactor
- ADR: [`docs/adr/0002-monorepo.md`](./docs/adr/0002-monorepo.md)

**Структура** (повтор):
```
lms/
├── apps/
│   ├── web/        # Next.js — student/teacher
│   └── admin/      # Next.js — tenant admin (опц., v1.1 — одна web вместо двух)
├── packages/
│   ├── db-schema/  # Drizzle ORM
│   ├── shared-types/ # Zod → TS codegen
│   └── ui-kit/     # Design system
└── infra/
```

**v1.0 упрощение:** одна Next.js app (`apps/web`) с role-based UI. В v1.1, если понадобится, разделим на web/admin.

### 6.3 Backend: модульная монолитная архитектура

**Не микросервисы в v1.0** (overhead). Модули внутри FastAPI:

```
backend/app/
├── core/                 # config, auth, db, errors
├── modules/
│   ├── courses/          # Course CRUD, structure, publish
│   ├── lessons/          # Lesson CRUD, content blocks
│   ├── enrollments/      # Enroll, unenroll, bulk
│   ├── progress/         # Track events, compute %
│   ├── quizzes/          # Quiz CRUD, attempt, grade
│   ├── ai/               # Generation pipeline (Qwen client)
│   ├── video/            # Upload, transcode, streaming
│   ├── files/            # Generic file upload
│   ├── search/           # FTS queries
│   ├── notifications/    # In-app, email, telegram
│   ├── analytics/        # Aggregations, exports
│   ├── audit/            # Immutable log
│   └── billing/          # Subscription, usage
├── workers/              # Celery tasks
│   ├── ai_generation/
│   ├── video_transcode/
│   └── notifications/
├── api/                  # FastAPI routers (one per module)
└── main.py
```

Каждый модуль:
- Своя папка с `models.py`, `schemas.py`, `service.py`, `router.py`
- Свои тесты в `tests/`
- Чёткие boundaries (зависимости через DI, не через прямой импорт других модулей)

### 6.4 Frontend: feature-based

```
apps/web/src/
├── app/                  # Next.js App Router pages
│   ├── (auth)/           # login, logout
│   ├── (student)/        # course player, dashboard
│   ├── (teacher)/        # course editor
│   ├── (admin)/          # tenant admin
│   └── api/              # BFF (Backend-For-Frontend) routes
├── features/             # Feature modules
│   ├── courses/
│   ├── lessons/
│   ├── ai-generator/
│   ├── player/
│   ├── quiz/
│   └── analytics/
├── components/           # Shared UI (from ui-kit)
├── lib/                  # api client, auth, utils
├── stores/               # Zustand
└── styles/               # globals.css
```

### 6.5 Multi-tenancy

**Стратегия:** Shared database, shared schema, **row-level isolation через tenant_id**.

Все таблицы имеют `tenant_id UUID NOT NULL`. Все запросы фильтруют по `tenant_id`. Это enforced:

1. **ORM level:** middleware в SQLAlchemy, автоматически подставляет `tenant_id` в WHERE
2. **DB level:** Row-Level Security policy в PostgreSQL (для defense in depth)
3. **API level:** JWT содержит `tenant_id`, middleware проверяет что path/body не пытается использовать другой `tenant_id`

Суперадмин Kamilya может переключаться между тенантами через специальный токен (impersonation).

### 6.6 Real-time

WebSocket через FastAPI:
- `/ws/courses/{id}` — live progress, presence, comments
- `/ws/notifications` — global notification stream
- Подключение: JWT в query param `?token=...`
- Heartbeat каждые 30 сек
- Auto-reconnect с exponential backoff на клиенте

События (server → client):
- `progress.lesson.completed` { lesson_id, course_id, percent }
- `presence.joined` / `presence.left` { user_id, lesson_id }
- `comment.created` { comment_id, lesson_id }
- `notification.new` { notification }

События (client → server):
- `subscribe` { topic }
- `unsubscribe` { topic }
- `ping` → `pong`

---

## 7. Модель данных

### 7.1 ERD (ASCII)

```
┌──────────────┐       ┌──────────────────┐       ┌──────────────┐
│   tenants    │──┬───│      users        │───┬───│  user_roles  │
│  id (PK)     │  │   │  id (PK)          │   │   │  user_id (FK)│
│  name        │  │   │  tenant_id (FK)   │   │   │  role        │
│  slug        │  │   │  email            │   │   │  (enum)      │
│  status      │  │   │  telegram_id      │   │   └──────────────┘
│  plan        │  │   │  password_hash    │   │
│  settings    │  │   │  first_name       │   │  ┌──────────────┐
└──────┬───────┘  │   │  last_name        │   │  │  enrollments  │
       │          │   │  status           │   │  │  id (PK)      │
       │          │   │  created_at       │   │  │  tenant_id    │
       │          │   └────────┬─────────┘   │  │  course_id    │
       │          │            │              │  │  user_id (FK) │
       │          │            │              │  │  status       │
       │          │            │              │  │  enrolled_at  │
       │          │            ▼              │  │  completed_at │
       │          │   ┌──────────────────┐    │  └──────┬───────┘
       │          │   │  user_sessions    │    │         │
       │          │   │  id (PK)          │    │         │
       │          │   │  user_id (FK)     │    │         ▼
       │          │   │  refresh_token    │    │  ┌──────────────┐
       │          │   │  expires_at       │    │  │   courses    │
       │          │   │  user_agent       │    │  │  id (PK)     │
       │          │   │  ip               │    │  │  tenant_id   │
       │          │   └──────────────────┘    │  │  title       │
       │          │                          │  │  description │
       │          │                          │  │  status      │
       │          │   ┌──────────────────┐    │  │  thumbnail   │
       │          │   │    courses        │◄───┘  │  created_by  │
       │          │   │  id (PK)          │       │  created_at  │
       │          │   │  tenant_id (FK)   │       │  updated_at  │
       │          │   │  title            │       │  published_at│
       │          │   │  description      │       └──────┬───────┘
       │          │   │  status           │              │
       │          │   │  thumbnail_url    │              │
       │          │   │  created_by (FK)  │              ▼
       │          │   │  created_at       │       ┌──────────────┐
       │          │   │  updated_at       │       │   modules    │
       │          │   │  published_at     │       │  id (PK)     │
       │          │   │  ai_generated     │       │  course_id   │
       │          │   │  source_doc_ids[] │       │  title       │
       │          │   └────────┬─────────┘       │  description │
       │          │            │                 │  order_index │
       │          │            ▼                 │  ai_generated│
       │          │   ┌──────────────────┐       └──────┬───────┘
       │          │   │    lessons        │              │
       │          │   │  id (PK)          │              ▼
       │          │   │  module_id (FK)   │       ┌──────────────┐
       │          │   │  title            │       │   lessons    │
       │          │   │  content_type     │       │  id (PK)     │
       │          │   │  content          │       │  module_id   │
       │          │   │  duration_seconds │       │  ...         │
       │          │   │  order_index      │       └──────┬───────┘
       │          │   │  ai_generated     │              │
       │          │   │  published_at     │              ▼
       │          │   └────────┬─────────┘       ┌──────────────┐
       │          │            │                 │content_blocks│
       │          │            ▼                 │  id (PK)     │
       │          │   ┌──────────────────┐       │  lesson_id   │
       │          │   │   quizzes         │       │  type (enum) │
       │          │   │  id (PK)          │       │  content     │
       │          │   │  lesson_id (FK)   │       │  order_index │
       │          │   │  title            │       │  metadata    │
       │          │   │  pass_score       │       └──────────────┘
       │          │   │  time_limit       │
       │          │   │  attempt_limit    │   ┌──────────────┐
       │          │   └────────┬─────────┘   │   quizzes    │
       │          │            │                 │  id (PK)     │
       │          │            ▼                 │  lesson_id   │
       │          │   ┌──────────────────┐       │  ...         │
       │          │   │   questions       │       └──────┬───────┘
       │          │   │  id (PK)          │              │
       │          │   │  quiz_id (FK)     │              ▼
       │          │   │  text             │       ┌──────────────┐
       │          │   │  type             │       │  questions   │
       │          │   │  points           │       │  id (PK)     │
       │          │   │  explanation      │       │  quiz_id     │
       │          │   │  order_index      │       │  ...         │
       │          │   │  pool_group       │       └──────┬───────┘
       │          │   └────────┬─────────┘              │
       │          │            │                        ▼
       │          │            ▼                 ┌──────────────┐
       │          │   ┌──────────────────┐       │ quiz_choices │
       │          │   │   choices         │       │  id (PK)     │
       │          │   │  id (PK)          │       │  question_id  │
       │          │   │  question_id (FK) │       │  text        │
       │          │   │  text             │       │  is_correct  │
       │          │   │  is_correct       │       │  order_index │
       │          │   │  order_index      │       └──────────────┘
       │          │   └──────────────────┘
       │          │                          ┌──────────────┐
       │          │   ┌──────────────────┐  │   progress   │
       │          │   │  quiz_attempts    │  │  id (PK)     │
       │          │   │  id (PK)          │  │  tenant_id   │
       │          │   │  quiz_id (FK)     │  │  user_id     │
       │          │   │  user_id (FK)     │  │  course_id   │
       │          │   │  started_at       │  │  lesson_id   │
       │          │   │  finished_at      │  │  percent     │
       │          │   │  score            │  │  time_spent  │
       │          │   │  passed           │  │  completed   │
       │          │   │  answers (jsonb)  │  │  last_at     │
       │          │   └──────────────────┘  └──────────────┘
       │          │
       │          └─ → → → → → → → → → → → → ┐
       │                                     │
       ▼                                     ▼
┌──────────────┐                  ┌──────────────────┐
│   audit_log  │                  │  notifications   │
│  id (PK)     │                  │  id (PK)         │
│  tenant_id   │                  │  tenant_id       │
│  user_id     │                  │  user_id         │
│  action      │                  │  type            │
│  resource    │                  │  title           │
│  old_value   │                  │  body            │
│  new_value   │                  │  link            │
│  ip          │                  │  read_at         │
│  user_agent  │                  │  created_at      │
│  created_at  │                  └──────────────────┘
└──────────────┘
```

### 7.2 Полный DDL (PostgreSQL)

См. [`docs/diagrams/erd.sql`](./docs/diagrams/erd.sql) — полный DDL скрипт.

### 7.3 Row-Level Security

```sql
ALTER TABLE courses ENABLE ROW LEVEL SECURITY;
CREATE POLICY courses_tenant_isolation ON courses
  USING (tenant_id = current_setting('app.tenant_id')::UUID);

ALTER TABLE enrollments ENABLE ROW LEVEL SECURITY;
CREATE POLICY enrollments_tenant_isolation ON enrollments
  USING (tenant_id = current_setting('app.tenant_id')::UUID);
-- ... для всех tenant-scoped таблиц
```

Middleware в SQLAlchemy устанавливает `app.tenant_id` перед каждым запросом.

---

## 8. REST API контракт

### 8.1 Базовые правила

- Base URL: `https://api.lms.kml.kz/v1`
- Auth: `Authorization: Bearer <jwt>`
- Content-Type: `application/json` (кроме upload: `multipart/form-data`)
- Errors: HTTP код + JSON `{ "error": "code", "message": "...", "details": {...} }`
- Pagination: `?page=1&per_page=20`, response includes `total`, `has_more`
- Versioning: URL path (`/v1/`), breaking changes → `/v2/`
- OpenAPI 3.1 spec: `/openapi.json`, Swagger UI: `/docs`

### 8.2 Основные endpoints

**Auth:**
- `POST /auth/login` — email/password, returns tokens
- `POST /auth/refresh` — refresh access token
- `POST /auth/logout` — blacklist refresh token
- `POST /auth/telegram` — Telegram OAuth callback
- `GET /auth/me` — current user

**Courses:**
- `GET /courses` — list (filter: status, search, page)
- `POST /courses` — create
- `GET /courses/{id}` — get with structure
- `PATCH /courses/{id}` — update
- `DELETE /courses/{id}` — soft delete
- `POST /courses/{id}/publish` — publish (snapshot content)
- `POST /courses/{id}/unpublish`
- `POST /courses/{id}/duplicate`
- `GET /courses/{id}/structure` — full tree (modules → lessons → blocks)

**Modules / Lessons:**
- `POST /courses/{id}/modules` — create module
- `PATCH /modules/{id}` — update
- `DELETE /modules/{id}` — delete
- `POST /modules/{id}/reorder` — change order
- (same for lessons)
- `POST /lessons/{id}/content` — update content blocks
- `POST /lessons/{id}/regenerate` — AI regen with feedback

**AI Generation:**
- `POST /ai/generate-course` — start generation (returns job_id)
- `GET /ai/jobs/{id}` — status
- `GET /ai/jobs/{id}/events` — SSE stream
- `POST /ai/jobs/{id}/cancel`

**Enrollment:**
- `GET /courses/{id}/enrollments` — list enrolled
- `POST /courses/{id}/enrollments` — enroll user(s)
- `DELETE /enrollments/{id}` — unenroll
- `POST /courses/{id}/enrollments/bulk` — bulk via CSV

**Progress:**
- `POST /progress/events` — record event (lesson_view, lesson_complete, video_progress)
- `GET /courses/{id}/progress` — my progress in course
- `GET /users/{id}/progress` — user progress (admin)

**Quizzes:**
- `POST /quizzes/{id}/attempts` — start attempt
- `PATCH /attempts/{id}` — save answer
- `POST /attempts/{id}/submit` — submit + auto-grade
- `GET /attempts/{id}` — get result

**Files:**
- `POST /files/upload` — multipart upload, returns file_id + URL
- `GET /files/{id}` — get metadata
- `DELETE /files/{id}` — soft delete

**Video:**
- `POST /videos/upload` — initiate multipart upload, returns upload_id
- `POST /videos/{id}/complete` — notify upload complete, start transcode
- `GET /videos/{id}/manifest.m3u8` — HLS playlist
- `GET /videos/{id}/status` — transcode status
- `POST /videos/{id}/subtitles` — upload VTT

**Notifications:**
- `GET /notifications` — my notifications (paginated)
- `PATCH /notifications/{id}/read` — mark as read
- `POST /notifications/read-all`

**Search:**
- `GET /search?q=...&type=course,lesson,document` — full-text + suggestions

**Analytics (tenant admin):**
- `GET /analytics/overview` — totals
- `GET /analytics/courses/{id}` — per-course
- `GET /analytics/users/{id}` — per-user (с anonymization)
- `GET /analytics/export?format=csv` — экспорт

**Tenant admin:**
- `GET /tenants/me` — current tenant info
- `PATCH /tenants/me/settings` — update settings
- `GET /tenants/me/users` — list users in tenant
- `POST /tenants/me/users` — invite user
- `DELETE /tenants/me/users/{id}` — remove user

**Audit (superadmin):**
- `GET /audit?from=...&to=...&user=...&action=...`
- `GET /audit/export`

**Billing (read-only в v1.0):**
- `GET /billing/subscription` — current plan
- `GET /billing/usage` — current usage metrics

### 8.3 WebSocket API

`wss://api.lms.kml.kz/ws?token=<jwt>`

Channels (subscribe via `{"action":"subscribe","channel":"progress.123"}`):

```typescript
type ServerMessage = 
  | { event: "progress.update"; data: { lesson_id: string; percent: number } }
  | { event: "presence.joined"; data: { user_id: string; lesson_id: string } }
  | { event: "presence.left"; data: { user_id: string; lesson_id: string } }
  | { event: "comment.created"; data: { comment: Comment } }
  | { event: "notification.new"; data: { notification: Notification } }
  | { event: "ai.progress"; data: { job_id: string; stage: string; percent: number } }
  | { event: "pong" };
```

---

## 9. Ключевые UI-потоки

### 9.1 AI-генерация курса (tenant admin)

```
1. /courses/new
   ↓ [+ Создать с AI]
2. /courses/new/ai
   - Drop zone: загрузить документы
   - Textarea: описание целевой аудитории
   - Settings: язык, кол-во модулей, тон
   ↓ [Сгенерировать]
3. /courses/new/ai/progress  (live SSE/WebSocket)
   - Этапы: "Анализ документов" → "Проектирование структуры" → "Генерация контента" → "Генерация тестов" → "Финализация"
   - Cancel button
   ↓ (готово)
4. /courses/{id}/edit
   - Структура видна, можно править
   - "Регенерировать модуль с замечаниями" inline
   ↓ [Опубликовать]
5. /courses/{id}  (course detail)
```

### 9.2 Прохождение курса (student)

```
1. /dashboard — список enrolled курсов
   ↓ [Open course]
2. /courses/{id} — TOC + intro
   ↓ [Start lesson]
3. /courses/{id}/lessons/{lid} — content
   - Scroll / video play / quiz inline
   - Auto-mark complete on threshold
   - Note-taking sidebar
   ↓ [Next lesson]
4. ... continue
   ↓ (course complete)
5. /courses/{id}/certificate — PDF + share link
```

### 9.3 Quiz attempt (student)

```
1. /courses/{id}/lessons/{lid} — show quiz block
   ↓ [Начать тест]
2. /quizzes/{qid}/attempt — timer if any, question 1
   ↓ [Save & next]
3. ... questions
   ↓ [Завершить]
4. /quizzes/{qid}/attempt/{aid}/result
   - Score, pass/fail
   - Per-question feedback
   - "Попробовать снова" if attempts left
```

### 9.4 Course editor (admin/teacher)

```
1. /admin/courses/{id} — overview + structure
   ↓ [Edit]
2. /admin/courses/{id}/edit
   - Outline panel (left)
   - Editor panel (center): Tiptap
   - Settings panel (right)
   - Drag-and-drop reorder
   - Inline "AI: rewrite this" / "Generate quiz"
   ↓ [Save draft] or [Publish]
```

### 9.5 Live progress view (admin)

```
1. /admin/courses/{id}/analytics
   - Funnel: enrolled → started → 50% → 100%
   - Per-leçon completion heatmap
   - Time-to-complete histogram
   - Stuck-on-lesson list (students + lesson)
   ↓ [Export CSV]
```

---

## 10. AI-интеграция (Qwen)

### 10.1 Pipeline

```
Documents (PDF/DOCX/TXT/MD)
    │
    ▼ [Architect agent — Qwen 3.5]
Target audience description
    │
    ▼
Course structure (modules + lesson titles + descriptions)
    │
    ▼ [Writer agent — parallel per module]
Lesson content (Markdown) + Quiz questions
    │
    ▼ [Reviewer agent — quality check]
Edits if low quality (score < 0.7)
    │
    ▼
Persisted as draft, presented to admin
```

### 10.2 Prompts (хранятся в `packages/ml-pipeline/prompts/`)

`architect.md`:
```markdown
You are a curriculum architect. Given source documents and target audience,
design a structured course outline.

# Input
- Documents: {documents_summary}
- Audience: {target_audience}
- Number of modules: {num_modules}
- Language: {language}

# Output (JSON)
{
  "course": {
    "title": "...",
    "description": "...",
    "modules": [
      {
        "title": "...",
        "description": "...",
        "learning_outcomes": ["..."],
        "lessons": [
          { "title": "...", "description": "...", "type": "theory|practice|quiz" }
        ]
      }
    ]
  }
}

# Constraints
- Each module 30-90 min study time
- Each lesson 5-20 min
- Lessons progress logically
- 80% of content from source documents, 20% bridging
- Kazakhstan corporate training context (if language=ru)
```

`writer.md`, `reviewer.md` — аналогично.

### 10.3 Concurrency

- 1 worker на структуру (Architect)
- N workers параллельно для контента (Writer), где N = `min(num_modules, 4)`
- Quality check синхронный (быстрый, 1-2 сек на модуль)

### 10.4 Cost estimation

| Tokens per course (5 modules, 3 lessons each) | ~80 000 |
| Qwen 3.5 cost per 1M tokens | ~0.20 USD (input), 0.40 (output) |
| **Total per course** | ~0.05 USD |
| With retries + review | ~0.10 USD |

### 10.5 Caching

- Cache Architect output by (documents_hash, audience, num_modules) — TTL 7 days
- Cache embedding lookups for repeated queries
- Disable cache for: per-tenant overrides, after model update

---

## 11. Безопасность и приватность

### 11.1 Authentication

- **JWT (RS256)**, signed by Kamilya key
- Access token: 15 min, contains `user_id`, `tenant_id`, `roles[]`
- Refresh token: 30 days, stored httpOnly cookie + DB
- Logout: blacklist refresh token

### 11.2 Authorization

- **Row-level isolation:** все queries filter by `tenant_id` from JWT
- **Role-based:** каждой роли свой набор endpoints (см. § 2.2)
- **Resource-level:** admin может управлять только курсами своего тенанта
- **Suadmin override:** отдельный `X-Superadmin-Override` header + audit log

### 11.3 Input validation

- Pydantic schemas на backend (type-safe)
- Zod schemas на frontend (type-safe, share with backend via codegen)
- File upload:
  - MIME type check (magic bytes, not just extension)
  - Size limits (10 MB docs, 2 GB videos)
  - Virus scan (ClamAV в worker pool)
  - Filename sanitization

### 11.4 Output sanitization

- React по умолчанию escapes (XSS-safe)
- Markdown рендеринг: `react-markdown` с запрещёнными тегами (`script`, `iframe`)
- Video URLs: signed, expiring (15 min), domain-restricted

### 11.5 Headers

```nginx
Strict-Transport-Security: max-age=31536000; includeSubDomains
Content-Security-Policy: default-src 'self'; script-src 'self' 'nonce-...'; style-src 'self' 'unsafe-inline'; img-src 'self' https://cdn.lms.kml.kz; media-src https://cdn.lms.kml.kz; connect-src 'self' wss://api.lms.kml.kz
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
Referrer-Policy: strict-origin-when-cross-origin
Permissions-Policy: geolocation=(), microphone=(), camera=()
```

### 11.6 Rate limiting

- Per IP: 100 req/min
- Per user: 300 req/min
- Per tenant: 5000 req/min
- AI generation: 10 / hour per tenant (configurable)
- Video upload: 5 / day per tenant

### 11.7 Data retention

- Audit log: 5 years
- Course content: indefinite (пока tenant платит)
- Student progress: 3 years after last activity, then anonymized
- Backups: 30 days, encrypted at rest

### 11.8 GDPR / 152-ФЗ (Казахстан)

- Right to access (export personal data)
- Right to erasure (delete + anonymize progress)
- Right to portability (JSON export)
- Data residency: Kazakhstan (VPS в Алматы)
- DPO contact в настройках тенанта

---

## 12. Performance, кэш, real-time

### 12.1 Кэш стратегия

| Слой | Что кэшируем | TTL | Инвалидация |
|------|--------------|-----|-------------|
| Browser | Static assets (1 year), HTML (no-cache) | — | deploy |
| CDN (Cloudflare) | Static + image transformations | 30 days | purge API |
| Redis | Course structure, user permissions, plan limits | 5-15 min | tenant settings change |
| PostgreSQL | Materialized views для analytics | 1 hour | refresh on write |
| In-memory (per-request) | JWT claims, current user | request | — |

### 12.2 Database optimization

- Индексы: `(tenant_id, course_id)`, `(user_id, course_id)`, `(course_id, order_index)` в modules/lessons
- Partial indexes для soft-deleted (`WHERE deleted_at IS NULL`)
- GIN index для FTS (`tsvector` колонка в courses.title, lessons.content)
- pgvector index (ivfflat) для embeddings
- Materialized view для analytics (`mv_course_completion_by_tenant`)

### 12.3 Real-time

- WebSocket: 1 connection per user, multiplexed channels
- Pub/sub: Redis pub/sub для fan-out across workers
- Backpressure: client sends `subscribe` с `last_event_id`, server replays from log

### 12.4 CDN

- Cloudflare в режиме "orange cloud" (proxy)
- Cache static + image transformations
- Video CDN: опц. v1.1 (Bunny.net / Cloudflare Stream)

---

## 13. Локализация (i18n)

### 13.1 Архитектура

- **next-intl** для Next.js
- **i18next** в shared components (если есть)
- Все strings в `apps/web/messages/{locale}.json`
- Translations хранятся в Git (для v1.0), в будущем — Crowdin/POEditor

### 13.2 Локали v1.0

- `ru` — primary, 100% (default)
- `kk` — казахский, ≥ 80% (manual + AI-assisted)
- `en` — английский, ≥ 90%

### 13.3 Формат

```json
{
  "courses": {
    "title": "Курсы",
    "create": "Создать курс",
    "empty": "Пока нет ни одного курса"
  },
  "common": {
    "save": "Сохранить",
    "cancel": "Отмена"
  }
}
```

### 13.4 Pluralization

- ru: один / несколько / много (1, 2-4, 5+)
- kk: аналогично
- en: one / other

Используем ICU MessageFormat через `next-intl`.

### 13.5 RTL-ready (но не v1.0)

- CSS `dir="rtl"` поддерживается
- Логика не hard-coded на LTR
- В v1.0 не активируем RTL

---

## 14. Тестирование и качество

### 14.1 Уровни

| Уровень | Инструмент | Покрытие | Где запускается |
|---------|-----------|----------|-----------------|
| Unit | pytest / Vitest | ≥ 80% | CI, pre-commit |
| Integration | pytest + httpx / Vitest + MSW | ≥ 60% | CI |
| E2E | Playwright | critical paths | CI (smoke), staging (full) |
| Visual | Playwright screenshots | key pages | PR review |
| Load | k6 | 1000 RPS / 5000 concurrent | pre-release |
| Security | OWASP ZAP | weekly | staging |
| Accessibility | axe-core | key pages | CI |

### 14.2 Test data

- `packages/fixtures/` — статические JSON
- `tests/factories.py` — factory_boy для генерации
- Snapshot tests для API responses
- Каждый тест использует изолированный tenant (UUID)

### 14.3 CI Pipeline

```yaml
# .github/workflows/ci.yml
on: [push, pull_request]
jobs:
  test:
    steps:
      - lint: ruff, eslint, prettier
      - type-check: mypy, tsc
      - unit: pytest --cov, vitest --coverage
      - integration: pytest -m integration
      - e2e: playwright (smoke)
      - build: docker build
      - security: bandit, npm audit
```

### 14.4 Definition of Done (per feature)

- [ ] Unit tests ≥ 80% coverage
- [ ] Integration tests для critical paths
- [ ] E2E test для happy path
- [ ] OpenAPI spec обновлён
- [ ] i18n: все строки в RU/KK/EN
- [ ] WCAG AA: axe-core passes
- [ ] Performance: P95 ≤ 2.5s на главной странице
- [ ] Audit log пишется
- [ ] CHANGELOG.md обновлён
- [ ] Code review от 1 senior
- [ ] Деплой на staging → проверка вручную → GA

---

## 15. Этапы разработки

### v1.0 Beta (12 недель) — ВЫПОЛНЕНО (2026-06-29)

Все 12 недель завершены. Подробная история — в `PROGRESS.md` и `git log`.

| Неделя | План | Статус |
|--------|------|--------|
| W1-2 | Foundation: монорепо, Docker, CI/CD, auth, design system | ✅ |
| W3-4 | Course CRUD + structure editor (Tiptap) | ✅ |
| W5-6 | AI generation pipeline (architect/writer/assessor/reviewer) | ✅ |
| W7-8 | Student UX + Quizzes + Certificates + auto-issue | ✅ |
| W9-10 | Analytics + Admin + Audit + bulk enroll | ✅ |
| W11 | Performance + Security + i18n + WCAG AA + load testing | ✅ |
| W12 | Beta launch: onboarding wizard, admin/user guides (RU/KK), provider-keys UI, LLM failover | ✅ |

**Deliverables — фактическое состояние:**
- 35 Alembic-миграций, 17 модулей backend, 16+ frontend страниц
- 711/711 i18n ключей (ru/kk/en parity)
- 53 backend unit tests passing; axe-core a11y tests; E2E happy-path (Playwright)
- LLM/Embeddings failover chain (Qwen → DeepSeek/Voyage, ADR-0007)
- Multi-tenancy: ORM row-level + Postgres RLS + app role (ADR-0003/0004)
- Per-tenant LLM budget (миграция 0034)

### v1.1 (планируется, post-beta)

### Неделя 1-2: Foundation ✅

- [x] Setup монорепо (Nx, TypeScript, ESLint, Prettier) — в pnpm workspaces + Nx
- [x] Docker setup (web, api, postgres, redis, minio) — см. `docker-compose.yml`
- [x] CI/CD (GitHub Actions, деплой на staging) — GitHub Actions + Render autoDeploy
- [x] Дизайн-система v1 — см. `DESIGN.md` + `packages/ui-kit/`
- [x] DB migrations: tenants, users, courses — 35 миграций, включая initial
- [x] Auth: register, login, JWT, refresh, Telegram — `modules/auth/` (3 login flows)

**Deliverable:** можем зарегистрироваться, залогиниться, увидеть пустую страницу.

### Неделя 3-4: Course CRUD + Structure ✅

- [x] Courses API (CRUD)
- [x] Modules + Lessons API
- [x] Content blocks (text, video stub, pdf stub)
- [x] UI: course list, course detail, course editor
- [x] UI: module/lesson editor (Tiptap)
- [x] Drag-and-drop reorder
- [x] Publish/unpublish flow

**Deliverable:** можно создать курс вручную, опубликовать, увидеть в каталоге.

### Неделя 5-6: AI Generation ✅

- [x] Qwen client (LLM + Embeddings) — с failover chain
- [x] Document upload + parse (PDF/DOCX) — Docling интеграция
- [x] Architect agent: структура курса
- [x] Writer agent: контент уроков + тесты
- [x] Reviewer agent: quality check (LLM-as-judge)
- [x] Pipeline: SSE/WebSocket прогресс
- [x] UI: AI generation wizard
- [x] Inline edit + regen

**Deliverable:** можно загрузить документ → AI генерирует курс за 2-3 минуты → admin редактирует → публикует.

### Неделя 7-8: Student UX + Quizzes ✅

- [x] Course player (sidebar + content)
- [x] Progress tracking (events API)
- [x] Quizzes CRUD + attempt flow
- [x] Auto-grading
- [x] Certificate generation (PDF) — fpdf2 + Supabase Storage
- [x] Auto-issued certificate (закреплён в `POST /courses/{id}/complete`)
- [x] Quiz deferral window enforcement

**Deliverable:** студент может пройти курс целиком, пройти тесты, получить сертификат.

### Неделя 9-10: Analytics + Multi-tenant + Admin ✅

- [x] Tenant dashboard (analytics overview)
- [x] Per-course analytics (funnel, heatmap)
- [x] Per-user progress (с anonymization)
- [x] Export CSV/Excel
- [x] Audit log (с middleware hooks)
- [x] Tenant settings (logo, colors, language default)
- [x] User management (invite, roles)
- [x] Bulk enroll (через positions + kiosk flow)
- [x] Staff import (Excel/CSV) + org structure tree (ADR-0011)
- [x] Provider-keys UI (encrypted Fernet)

**Deliverable:** tenant admin может видеть полную картину, экспортировать отчёты, управлять командой.

### Неделя 11: Performance + Security + i18n ✅

- [x] Performance optimization (async pool config, N+1 fixes)
- [x] Security audit + fixes — критичные бизнес-флоу закрыты
- [x] WCAG AA compliance — Modal focus trap, SkipLink, axe-core tests
- [x] i18n: KK + EN переводы — 711/711 keys parity
- [x] Load testing (k6) — `tests/load/k6-test.js`
- [x] Backups setup — `scripts/backup.sh`, `restore.sh`
- [x] Monitoring (Prometheus + alerts) — `monitoring/`
- [x] Multi-tenancy hardening — RLS + app role (ADR-0003/0004)

**Deliverable:** production-ready infrastructure.

### Неделя 12: Beta launch ✅

- [x] Onboarding flow для tenant admin — `OnboardingWizard.tsx`
- [x] Documentation (admin guide, user guide) — RU + KK
- [x] API reference — `docs/api-reference.md`
- [x] Per-tenant LLM budget — migration 0034
- [x] LLM/Embeddings failover chain — ADR-0007
- [x] Bug bash + fixes (multiple critical fixes: auto-certificate, deferral, position re-enroll, audit log)

**Deliverable:** 3-5 tenants используют систему в production.

### v1.1 — следующая итерация (roadmap)

---

## 16. Definition of Done

**Для каждой feature:**
1. Код написан, peer-reviewed, в master
2. Unit tests ≥ 80% coverage
3. Integration test проходит
4. E2E test для happy path проходит
5. OpenAPI spec обновлён
6. i18n: строки в RU (обязательно), KK/EN (если возможно)
7. WCAG AA: нет critical issues
8. Performance: P95 ≤ 2.5s
9. Audit log пишется для значимых действий
10. CHANGELOG.md обновлён
11. Деплой на staging → manual smoke test
12. PR одобрен senior-инженером

**Для релиза v1.0 (GA):**
- Все MUST-фичи реализованы и протестированы
- 0 critical bugs в течение 1 недели после beta
- Performance SLA достигнуто (99.5% uptime, P95 ≤ 2.5s)
- Security audit пройден
- Backup/restore протестирован
- Documentation готова (admin guide, user guide, API docs)
- 3+ тенанта в production ≥ 1 месяц без критических багов

---

## 17. Риски и mitigation

| Риск | Вероятность | Импакт | Mitigation |
|------|-------------|--------|-----------|
| Qwen rate limits / downtime | M | H | Fallback на OpenAI; кэш результатов; retry with backoff |
| Видео-транскодинг медленный | M | M | Worker pool + GPU опц.; async upload; HLS ready time acceptable 5-10 мин |
| Postgres overload | L | H | Connection pooling (PgBouncer), read replicas, monitoring |
| Cost overrun (Qwen) | M | M | Кэш, лимиты на тенант, alert при > $X/день |
| Данные теряются при backup | L | H | Encrypted backups в 2 регионах, еженедельный restore test |
| Chamilo migration breaks | M | M | Run в parallel 1 месяц, постепенный cutover per tenant |
| Малый adoption | M | H | Beta с 3-5 лояльными клиентами, A/B test UX |
| Безопасность: утечка tenant data | L | Critical | RLS на DB, тесты на cross-tenant, регулярный аудит |
| i18n не complete | M | M | AI-перевод KK с human review; fallback на RU |
| Talent (не наймем Flutter-дев) | M | M | Mobile — PWA в v1.0, native — v2.0 |

---

## 18. Приложения

### A. Глоссарий

| Термин | Определение |
|--------|------------|
| Tenant | Изолированная организация в Kamilya SaaS |
| Course | Единица обучения, содержит Modules → Lessons |
| Module | Тематический раздел курса |
| Lesson | Минимальная единица контента, 5-20 мин |
| Content Block | Атомарная часть урока (text/video/quiz/...) |
| Enrollment | Связь user ↔ course |
| Progress | % прохождения курса/урока |
| Quiz | Набор вопросов с auto-grading |
| Attempt | Одна попытка прохождения quiz |
| Certificate | PDF после завершения курса |
| SCORM | Sharable Content Object Reference Model (legacy) |
| xAPI | Experience API (современная замена SCORM) |
| HLS | HTTP Live Streaming (adaptive bitrate video) |
| RLS | Row-Level Security (Postgres feature) |
| SSE | Server-Sent Events (one-way real-time) |
| WebSocket | Full-duplex real-time protocol |
| ADR | Architecture Decision Record |

### B. Ссылки

- [Chamilo 2.0 docs](https://docs.chamilo.org/) — для reference функциональности
- [FastAPI docs](https://fastapi.tiangolo.com/)
- [Next.js 14 docs](https://nextjs.org/docs)
- [Drizzle ORM](https://orm.drizzle.team/)
- [Qwen 3.5](https://qwenlm.github.io/)
- [WCAG 2.1 AA](https://www.w3.org/WAI/WCAG21/quickref/?currentsidebar=%23col_overview&versions=2.1&levels=aaa)

### C. ADR (Architecture Decision Records)

Все ADR лежат в [`docs/adr/`](./docs/adr/):

- [0001 — Выбор технологического стека](./docs/adr/0001-stack-choice.md)
- [0002 — Монорепо](./docs/adr/0002-monorepo.md)
- [0003 — Multi-tenancy strategy](./docs/adr/0003-multitenant.md)
- [0004 — Видео pipeline](./docs/adr/0004-video-pipeline.md) *(будет создан в Неделе 7)*
- [0005 — AI pipeline architecture](./docs/adr/0005-ai-pipeline.md) *(будет создан в Неделе 5)*

### D. Структура репозитория

```
lms/
├── TZ.md                          # Этот документ
├── README.md                      # Краткий overview
├── apps/
│   ├── web/                       # Next.js 14 (frontend)
│   └── api/                       # FastAPI (backend)
├── packages/
│   ├── db-schema/                 # Drizzle + миграции
│   ├── shared-types/              # Zod ↔ Pydantic codegen
│   ├── ui-kit/                    # Design system components
│   └── ml-pipeline/               # AI agents, prompts
├── infra/
│   ├── docker/                    # Dockerfiles
│   ├── caddy/                     # Reverse proxy configs
│   └── ansible/                   # VPS provisioning
├── docs/
│   ├── adr/                       # Architecture Decision Records
│   ├── diagrams/                  # C4, sequence, ERD
│   └── runbooks/                  # Operations
├── .github/
│   └── workflows/                 # CI/CD
└── scripts/                       # Dev utilities
```

### E. Open Questions (для архитектора)

1. **Q: Где хранить видео — S3 напрямую или через CDN?**
   A: S3 + Cloudflare R2 опц. v1.1. v1.0 — S3 через nginx.
2. **Q: Делать ли свой WYSIWYG или использовать Tiptap?**
   A: Tiptap (decision в § 5.2).
3. **Q: Чат-тьютор в v1.0 или v1.1?**
   A: v1.1 (доп. ресурсы, нет критичной ценности на старте).
4. **Q: Multi-region?**
   A: Нет в v1.0. VPS в Алматы, backup в EU.
5. **Q: Pricing model для подписок?**
   A: Starter (5 courses, 50 learners), Business (50 courses, 500 learners), Enterprise (custom). Детально в [docs/billing.md](./docs/billing.md) (отдельный документ).

---

## Changelog

- **2026-06-21 v1.0** — Initial ТЗ. Готов к разработке.
- **2026-06-15 v0.5** — Draft для review с командой.
- **2026-06-10 v0.1** — Initial outline.

---

*Документ обновляется по мере изменений. Версия в `git log` репозитория. ADR — отдельные файлы в `docs/adr/`.*
