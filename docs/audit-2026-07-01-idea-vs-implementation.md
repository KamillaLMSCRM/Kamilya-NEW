# Kamilya LMS/CRM - аудит идеи, документов и исполнения на 2026-07-01

Цель аудита: понять, соответствует ли фактический проект замыслу, и где прошлые handoff/документы расходятся с реальным кодом или продом.

Проверено:
- GitHub checkout: `KamillaLMSCRM/Kamilya-NEW`, branch `master`, `HEAD = origin/master = 5c257fda8ec4c77332fcc5c416a9c1dab337c780`.
- Секреты: исходный `secrets.txt` переименован и перенесен в корень репозитория как `.env`; git его игнорирует (`!! .env`), файл не tracked.
- Документы: `README.md`, `PROJECT.md`, `TZ.md`, `PROGRESS.md`, `DESIGN.md`, `docs/PROJECT-CONTEXT.md`, `docs/PROGRESS_2026-06-30.md`, `docs/SMOKE_PROD_2026-06-30.md`, `docs/VPS_CONNECTION_GUIDE.md`, handoff/plans/ADR.
- Код: backend routers/models/config, frontend pages/navigation/staff rules/integrations/auth, CI/render/docker config.
- Прод health: API, frontend, wa-gateway, OpenAPI.

Важно: значения секретов в отчете не раскрываются.

## 1. Мое видение проекта

Kamilya LMS/CRM - это B2B multi-tenant SaaS для корпоративного обучения и онбординга сотрудников, где основная бизнес-идея не просто "загрузить курс", а автоматизировать цепочку:

1. Компания/тенант заводит сотрудников, отделы, должности и правила обучения.
2. Методолог или администратор загружает должностные инструкции, PDF/DOCX/TXT и другие материалы.
3. AI превращает эти материалы в курс: модули, уроки, тесты, задания, проверку качества.
4. Курсы назначаются сотрудникам по правилам: вся компания, отдел, должность, конкретный сотрудник.
5. Сотрудник проходит обучение и тесты, получает прогресс и сертификат.
6. Руководитель/методолог видит структуру штата, назначенные курсы, прогресс, сертификаты и может дорабатывать контент.
7. Доставка приглашений и уведомлений идет через разные каналы: Telegram, WhatsApp, SMTP/email, kiosk links.

То есть ядро продукта - не "LMS как Chamilo", а связка HR/штатка + AI-генерация обучения + назначение курсов + контроль прохождения + multi-channel delivery. CRM-часть пока выглядит не как полноценная sales CRM, а как tenant/admin/staff management вокруг LMS.

## 2. Что реально реализовано

### Backend

Фактически есть модульный FastAPI backend:
- auth: email/password, Telegram code flow, demo-login, superadmin login, refresh/logout.
- users/staff: users CRUD, invitations, bulk invitations, staff import preview/commit, apply-rules status.
- positions/departments: должности, отделы, привязка курсов к должности/отделу, пересчет enrollments.
- courses/lessons/quizzes/progress/student: основной LMS контур.
- AI: generation jobs, chat, regenerate module/lesson, ingestion, embeddings, LLM failover.
- certificates: issue/download/verify.
- integrations: WhatsApp, SMTP, Telegram credentials per tenant, encrypted config.
- admin/superadmin/demo/audit/provider keys.

Хороший признак: почти все важные routers имеют tenant filtering (`tenant_id == user.tenant_id`) и role gates. Есть тесты под auth, tenant isolation, staff import, positions courses, provider keys, storage, telegram webhook, quiz flows.

### Frontend

Фактически есть Next.js app с рабочими экранами:
- login/register/demo/superadmin login/accept invite/kiosk.
- dashboard, courses, course editor, AI generate, documents.
- staff/admin tabs: import, structure, rules, company-courses.
- positions, quizzes, enrollments, certificates, student/my-courses/my-quizzes.
- integrations settings for WhatsApp/SMTP/Telegram.
- role-based sidebar.

Это не пустой шаблон. Продуктовая поверхность широкая и связана с API.

### Infra

Фактическая архитектура гибридная:
- Frontend: Vercel, `https://app.kml.kz`.
- Backend: Render, live service `srv-d8rp8ej7uimc73fglid0`, public URL `https://kamilya-lms-api.onrender.com`.
- DB/storage: Supabase/Postgres/Supabase Storage.
- Redis: Upstash/Redis.
- VPS `173.249.51.164`: docling, wa-gateway, Celery worker, WireGuard to DGX.
- LLM: self-hosted Qwen behind tunnel, fallback DeepSeek/Voyage.

Прод health на 2026-07-01:
- `https://kamilya-lms-api.onrender.com/health` -> 200.
- `https://kamilya-lms-api.onrender.com/api/v1/health` -> 200.
- `https://app.kml.kz` -> 200.
- `https://wa.kml.kz/health` -> 200, `mock=false`, sessions present.
- `https://api.kml.kz/api/v1/health` -> DNS not resolved. Документы/README иногда говорят `api.kml.kz`, но фактически проверенный backend URL - Render URL.
- `https://docling.kml.kz/health` с этой машины дал TLS error. Это может быть локальная TLS/Windows проблема, но как минимум health не подтвержден.

## 3. Где документы соответствуют коду

Соответствует:
- Монорепо структура: `apps/api`, `apps/web`, `packages`, `infra`, `monitoring`, `docs`.
- FastAPI + Next.js + PostgreSQL/Supabase + Redis + Celery + pgvector.
- Multi-tenancy как критическое правило.
- Роли и текущий спор admin/methodologist описаны в ADR-0012 и частично отражены в frontend/backend.
- Staff import + apply rules действительно есть.
- Course assignment к должностям/отделам действительно есть.
- WhatsApp/SMTP/Telegram integrations есть в коде и UI.
- Render startCommand в `render.yaml` уже содержит `alembic upgrade head && uvicorn...`; старый документ от 30 июня про отсутствие миграций в startCommand частично устарел для repo HEAD.
- OpenAPI живой и отдает 145 paths.

## 4. Главные расхождения и риски

### P0/P1. Документы местами заявляют GA/prod-ready сильнее, чем подтверждает код и prod

`TZ.md` и `PROGRESS.md` говорят языком "v1.0 Beta complete", "production-ready", "3-5 tenants use production", "security audit passed", "load testing". Текущие документы от 30 июня сами же признают:
- UI smoke staff/apply-rules не был полностью пройден без участия владельца.
- Cross-tenant isolation tests не закрыты полностью.
- Mobile smoke не проводился.
- KK i18n не измерен.
- OpenAPI/cache/perf остаются follow-up.

Вывод: прошлый агент скорее понял большую идею, но переоценивал готовность. Это не выглядит как "пустой обман", но выглядит как завышенный sign-off.

### P1. Backend live не на последнем repo HEAD

Render deploys показывают live backend на `d7ed4ac`, тогда как GitHub/local HEAD `5c257fd`. Часть свежих commits после `d7ed4ac` - docs/web/nav, поэтому это не обязательно backend blocker, но фраза "repo HEAD == prod" сейчас неверна.

Перед любыми выводами по прод-багам надо различать:
- локальный код/GitHub HEAD;
- live backend Render commit;
- Vercel frontend deploy commit.

### P1. Course router продублирован внутри одного файла

`apps/api/app/modules/courses/router.py` содержит повторный набор routes: `list/create/get/patch/publish/unpublish/duplicate/delete/complete` объявлены дважды. Первый блок содержит reviewer/review/preview additions, второй блок - старые копии без reviewer hydration.

Риск:
- FastAPI зарегистрирует дублирующиеся path+method. Обычно первый route может матчиться раньше, но OpenAPI/поведение становятся неочевидными.
- Поддержка курса будет ломкой: правка может попасть в один блок, а фактически работать будет другой.

Это нужно чистить до серьезной доработки LMS flow.

### P1. Для отделов нет GET `/departments/{id}/courses`, UI показывает badge 0

В backend есть:
- `POST /departments/{department_id}/courses`
- `DELETE /departments/{department_id}/courses/{course_id}`
- `GET /departments` со списком departments и `course_ids`.

Но нет `GET /departments/{id}/courses`. `RulesTab.tsx` прямо говорит пользователю, что список курсов отдела пока не отображается. Из-за этого:
- отделы слева показывают badge `0`;
- после attach mutation работает, но UI не может нормально показать текущие привязки конкретного отдела;
- пользователь может думать, что привязка не сработала.

Минимальная доработка: либо добавить GET endpoint, либо использовать уже существующий `GET /departments` в `RulesTab`.

### P1. Auth/TZ drift: RS256 в TZ, HS256 в коде

`TZ.md` требует JWT RS256, но код явно разрешает только HS256/HS384/HS512 и запрещает asymmetric algorithms. `PROJECT.md` уже обновлен до HS256. Значит источник истины расходится:
- если RS256 был обязательным требованием безопасности - реализация не соответствует TZ;
- если решение сменили на HS256 - TZ устарел и должен быть исправлен, чтобы будущие агенты не "чиняли" в неправильную сторону.

### P1. Rate limiter comment contradicts behavior

`PROJECT.md` говорит fail-closed, но `core/rate_limit.py` в комментариях/логике говорит fail-open/allow request при Redis error. Для production security это существенная разница. Надо принять явное решение:
- fail-open ради доступности;
- fail-closed ради защиты.

Сейчас документы и код не совпадают.

### P1. Superadmin/methodologist role consistency не до конца вычищена

В UI `RulesTab` разрешает `methodologist`, `teacher`, `admin`, `org_admin`, `superadmin`. Backend department attach разрешает `admin`, `methodologist`, `superadmin`, но не `teacher`/`org_admin`. В positions router attach разрешает `methodologist`, `admin`, `superadmin`.

Риск: UI покажет вкладку пользователю, backend вернет 403. Нужно унифицировать ADR-0012 в коде.

### P1. Production API domain mismatch

README заявляет `API: api.kml.kz`, но `https://api.kml.kz/api/v1/health` не резолвится. Реально работает Render URL. Если frontend env указывает на Render URL - ок, но документация и DNS план расходятся.

### P2. Docling health не подтвержден

`https://docling.kml.kz/health` с этой машины вернул TLS channel error. Это может быть не падение сервиса, а проблема TLS negotiation/Cloudflare/Windows, но в аудите сервиса сейчас статус "не подтвержден". Нужна проверка с VPS или `curl`/браузером.

### P2. AI summarizer still has placeholder path

`apps/api/app/modules/ai/ingestion.py` содержит `Summarizer.summarize()` с TODO "Call Qwen 3.5 when available" и возвращает базовый summary по word count/headings. Если этот путь участвует в реальном RAG/course generation, качество AI pipeline ниже, чем заявлено. Если legacy - удалить/пометить.

### P2. `rotate_key_for_testing_only` NotImplemented нормально, но key rotation ops не реализован

Интеграционные секреты шифруются через Fernet и `MASTER_ENCRYPTION_KEY`. Это правильно. Но rotation key оставлен как ручной out-of-scope. Для beta терпимо, для production tenants надо runbook.

### P2. Документы с mojibake/encoding risk

В PowerShell часть документов/комментариев отображается mojibake. Вероятно файлы UTF-8, а консоль читает не тем encoding, но handoff файл и кодовые комментарии выглядят рискованно для будущих агентов. Перед редактированием русских документов лучше явно сохранять UTF-8.

## 5. Что прошлый агент понял правильно

Понял:
- продукт строится вокруг автоматизации обучения по JD/штатке, а не вокруг обычного каталога курсов;
- критична multi-tenancy isolation;
- роли admin/methodologist/teacher/student/superadmin требуют отдельной модели;
- staff import и course assignment - центральный бизнес-флоу;
- прод-проблемы часто живут на стыке DB migrations, Render deploy, Vercel UI и реальной Supabase schema;
- integrations/WhatsApp/Telegram/SMTP - не "nice to have", а часть delivery-модели;
- нужен handoff/lessons/docs, иначе проект уже слишком большой для одного агента без контекста.

## 6. Где прошлый агент переоценил или запутал состояние

Переоценил:
- степень готовности GA;
- полноту smoke/UI verification;
- синхронность repo/prod;
- актуальность некоторых docs после исправлений;
- отсутствие "мелких" UI drift: например, department course bindings работают на mutation, но отображение текущего состояния не закрыто.

Запутал:
- `api.kml.kz` vs Render backend URL;
- RS256 vs HS256;
- Render migrations: старый report говорит "нет в startCommand", repo HEAD уже содержит;
- department course GET: handoff говорит TODO, а рядом появился `GET /departments`, который можно использовать, но `RulesTab` еще живет старой логикой.

## 7. Последовательность доработки, которую я предлагаю

1. Зафиксировать источник истины: обновить `PROJECT.md`/`TZ.md`/`PROJECT-CONTEXT.md` по фактической infra, auth algorithm, demo-login, API domain, Render migration status.
2. Убрать технические противоречия в коде:
   - удалить дубли routes в `courses/router.py`;
   - выровнять роли UI/backend для `methodologist/teacher/org_admin`;
   - решить fail-open/fail-closed для rate limit и обновить docs/code.
3. Закрыть "видимую правду" в UI staff rules:
   - показывать реальные `course_ids` отделов через `GET /departments` или добавить `GET /departments/{id}/courses`;
   - убрать текст "API нет", если используем существующий endpoint;
   - проверить `/admin/staff?tab=rules` и `company-courses` на реальном tenant admin.
4. Проверить prod deployment chain:
   - Render latest deploy vs GitHub HEAD;
   - Vercel latest deploy vs GitHub HEAD;
   - migrations фактически применены к Supabase;
   - OpenAPI не должен тормозить 30-60 секунд.
5. Пройти критические smoke сценарии:
   - login/refresh/logout;
   - staff import preview/commit/apply-rules;
   - attach course company/department/position/user;
   - student course completion/quiz/certificate;
   - invitation accept flow;
   - WhatsApp/Telegram/SMTP test flows.
6. Только после этого делать продуктовые улучшения AI/CRM/UX.

## 8. Уточнения к владельцу

1. Правильный production API должен быть `https://api.kml.kz` или Render URL `https://kamilya-lms-api.onrender.com` допустим как постоянный?
2. JWT должен быть HS256 как сейчас или RS256 как в TZ?
3. Роль `teacher` должна иметь право привязывать курсы к отделам/должностям или только `methodologist/admin/org_admin`?
4. `org_admin` должен иметь те же права на course assignment, что `admin`?
5. Нужно ли считать `/admin/team` устаревшей страницей и удалить/redirect, как написано в handoff?
6. CRM в названии продукта - это пока управление tenant/staff, или планируется отдельный CRM-модуль по клиентам/продажам?
7. Нужно ли держать public demo-login в production для smoke, или production demo должен быть отключен полностью?

## 9. Короткий вывод

Проект не выглядит пустым или фейковым: большая часть архитектурной идеи реально реализована кодом. Но состояние нельзя считать "чисто готовым": документы местами завышают готовность, часть handoff уже устарела, есть реальные расхождения между UI/backend/docs/prod. Перед новыми фичами нужно провести стабилизационный pass: синхронизировать docs, убрать дубли/role drift, довести staff course assignment UI, и пройти реальные smoke сценарии на production-like данных.
