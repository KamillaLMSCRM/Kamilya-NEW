# Kamilya LMS Core v1.0

> AI-first корпоративная LMS для Казахстана. Полная замена Chamilo 2.0.

---

## Что это

HR загружает документы (PDF/DOCX/TXT) → AI анализирует и генерирует структурированный курс → обучающиеся проходят → тесты → сертификаты. Всё в одном продукте с multi-tenancy и ролевой моделью.

---

## Архитектура

```
┌─────────────────────────────────────────────┐
│  Frontend (Next.js 14, Vercel)              │
│  web-inky-three-48.vercel.app               │
└────────────────────┬────────────────────────┘
                     │ HTTPS
                     ▼
┌─────────────────────────────────────────────┐
│  Backend (FastAPI, Render)                  │
│  kamilya-lms-api.onrender.com               │
└────┬───────────────┬───────────────┬────────┘
     │               │               │
     ▼               ▼               ▼
  Supabase        Upstash          Qwen LLM
  PostgreSQL      Redis            10.66.66.7:8555
```

---

## Стек

### Backend
| Компонент | Технология |
|-----------|-----------|
| Framework | FastAPI |
| ORM | SQLAlchemy 2.0 (async) |
| Migrations | Alembic |
| Queue | Celery + Upstash Redis |
| Auth | JWT HS256 + argon2 |
| AI | Qwen 3.5 (OpenAI-compatible API) |
| PDF/DOCX | pypdf, python-docx |

### Frontend
| Компонент | Технология |
|-----------|-----------|
| Framework | Next.js 14 (App Router) |
| Language | TypeScript strict |
| Styling | Tailwind CSS 3.4 |
| State | Zustand 5 |
| HTTP | Axios |
| Animation | Framer Motion 11.15.0 |
| UI | Custom (Button, Card, Modal, Input, Badge, Table) |

### Инфра
| Сервис | URL |
|--------|-----|
| Database | Supabase PostgreSQL |
| Redis | Upstash |
| AI LLM | Qwen 3.5 @ 10.66.66.7:8555 |
| AI Embeddings | 10.66.66.7:8001 |

---

## Структура проекта

```
lms/
├── apps/
│   ├── api/                        ← FastAPI backend
│   │   ├── app/
│   │   │   ├── main.py             ← entry point
│   │   │   ├── core/               ← auth, config, db, celery, security
│   │   │   ├── models/             ← SQLAlchemy models
│   │   │   └── modules/            ← feature modules
│   │   │       ├── ai/             ← generation pipeline
│   │   │       ├── auth/           ← JWT + Telegram login
│   │   │       ├── courses/        ← course CRUD
│   │   │       ├── lessons/        ← lessons + content blocks
│   │   │       ├── quizzes/        ← quizzes + attempts
│   │   │       ├── documents/      ← file upload + dedup
│   │   │       ├── positions/      ← должности + JD analysis
│   │   │       ├── enrollments/    ← записи на курсы
│   │   │       ├── progress/       ← прогресс обучения
│   │   │       ├── certificates/   ← сертификаты
│   │   │       ├── users/          ← user management
│   │   │       ├── admin/          ← admin endpoints
│   │   │       └── student/        ← student endpoints
│   │   └── alembic/                ← DB migrations
│   │
│   └── web/                        ← Next.js 14 frontend
│       ├── src/
│       │   ├── app/                ← routes (20 pages)
│       │   ├── components/         ← layout + UI
│       │   ├── i18n/               ← RU/KK/EN translations
│       │   ├── lib/                ← api client, auth
│       │   └── store/              ← Zustand stores
│       └── tailwind.config.js
│
└── PROJECT.md                      ← этот файл
```

---

## Функционал

### Включено
| Фича | Статус |
|------|--------|
| JWT Auth + Telegram login | ✅ |
| Multi-tenancy (row-level) | ✅ |
| Course CRUD + structure | ✅ |
| Lesson content blocks | ✅ |
| Quiz engine + attempts | ✅ |
| Document upload (dedup) | ✅ |
| AI generation pipeline | ✅ |
| Position management | ✅ |
| JD analysis (AI) | ✅ |
| Enrollment + auto-assign | ✅ |
| Progress tracking | ✅ |
| Certificates | ✅ |
| Admin panel | ✅ |
| i18n (RU/KK/EN) | ✅ |
| Sidebar (collapsible) | ✅ |
| Command palette (⌘K) | ✅ |
| Rate limiting | ✅ |
| Audit logs | ✅ |

### Не реализовано
| Фича | Приоритет |
|------|-----------|
| Real-time (WebSocket) | medium |
| SCORM support | v1.1 |
| Mobile apps | v2.0 |

---

## Окружение

### Backend (Render)
См. `apps/api/.env` — все переменные хранятся локально.

### Frontend (Vercel)
См. `apps/web/.env.local` — переменные хранятся локально.

### Формат переменных
См. `apps/api/.env.example` и `apps/web/.env.example`.

---

## Деплой

### Frontend (Vercel)
```powershell
cd D:\Камиля\lms
npx vercel deploy --prod --yes --token $env:VERCEL_TOKEN --scope $env:VERCEL_SCOPE
```

### Backend (Render)
```bash
curl -X POST "https://api.render.com/v1/services/$RENDER_SERVICE_ID/deploys" \
  -H "Authorization: Bearer $RENDER_API_KEY" \
  -H "Content-Type: application/json" -d "{}"
```

### Git
```powershell
git add -A && git commit -m "..." && git push origin master
```

---

## База данных

### Таблицы
| Таблица | Описание |
|---------|----------|
| tenants | Организации (multi-tenant) |
| users | Пользователи (telegram_id, role) |
| user_roles | Роли пользователей |
| courses | Курсы (ai_generated, status) |
| modules | Модули курсов |
| lessons | Уроки |
| content_blocks | Блоки контента уроков |
| quizzes | Тесты |
| questions | Вопросы тестов |
| quiz_choices | Варианты ответов |
| quiz_attempts | Попытки прохождения |
| documents | Документы (upload) |
| positions | Должности |
| position_courses | Связь должность-курс |
| enrollments | Записи на курсы |
| progress | Прогресс обучения |
| certificates | Сертификаты |
| ai_jobs | AI задачи |
| generated_content | Сгенерированный контент |
| audit_logs | Аудит |

---

## Быстрые ссылки

| Ресурс | URL |
|--------|-----|
| Production | https://web-inky-three-48.vercel.app |
| API | https://kamilya-lms-api.onrender.com |
| GitHub | https://github.com/KamillaLMSCRM/Kamilya-NEW |
| Supabase | https://supabase.com/dashboard |
| Render | https://dashboard.render.com |
| Vercel | https://vercel.com/kamillalmscrms-projects |

---

*Обновлено: 22 июня 2026*
