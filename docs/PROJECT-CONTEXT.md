# Kamilya LMS: текущий контекст проекта

> Living document. Значения секретов здесь не хранятся.
> Обновлено: 2026-08-17.

## Источники правды

| Область | Документ |
|---|---|
| Продукт и функциональные границы | [`PROJECT.md`](../PROJECT.md) |
| Текущий production и release-gates | [`PRODUCTION_READINESS.md`](PRODUCTION_READINESS.md) |
| Открытый backlog | [`PRODUCT_BACKLOG.md`](PRODUCT_BACKLOG.md) |
| Роли admin/methodologist | [`ADR-0012`](adr/0012-rbac-admin-vs-methodologist.md) |
| Auth/session/active role | [`ADR-0008`](adr/0008-auth-strategy.md) |
| Пользовательские сценарии | [`USER_DOCUMENTATION_RU.md`](USER_DOCUMENTATION_RU.md) |
| Внутренняя архитектура | [`PROJECT_INTERNAL_DOCUMENTATION.md`](PROJECT_INTERNAL_DOCUMENTATION.md) |
| Эксплуатация worker | [`INFRA_CELERY_WORKER.md`](INFRA_CELERY_WORKER.md) |
| Доступ и сервисы VPS | [`VPS_CONNECTION_GUIDE.md`](VPS_CONNECTION_GUIDE.md) |
| Backup и restore | [`BACKUP_RESTORE_RUNBOOK.md`](BACKUP_RESTORE_RUNBOOK.md) |
| OCR и KZ infrastructure migration | [`INFRA_KZ_OCR_MIGRATION_ANALYSIS.md`](INFRA_KZ_OCR_MIGRATION_ANALYSIS.md) |
| Подтверждённые ошибки и профилактика | [`ERRORS.md`](../ERRORS.md) |
| Правила для агентов | [`AGENTS.md`](../AGENTS.md) |

Старые планы, аудиты, отчёты веток и ТЗ не являются источниками текущего
поведения.

## Репозиторий и сервисы

| Контур | Текущее размещение |
|---|---|
| Monorepo | `KamillaLMSCRM/Kamilya-NEW`, branch `master` |
| Production frontend | Next.js, Vercel project `web`, branch `master`, `https://app.kml.kz` |
| Dev frontend | Vercel project `kamilya-lms-dev`, branch `dev`, `https://kamilya-lms-dev.vercel.app` |
| API | FastAPI, Render, `https://kamilya-lms-api.onrender.com` |
| PostgreSQL/pgvector | Supabase, общий dev/test и controlled-pilot контур |
| Object storage | Supabase Storage, общий dev/test и controlled-pilot контур |
| Broker/cache | Valkey TLS на VPS |
| Background jobs | Три Celery worker на VPS: AI, documents и notifications/maintenance |
| Email | Resend, домен `notify.kml.kz` |
| Telegram | Kamilya bot/auth flow |
| Document conversion | Ограниченный локальный сервис: MarkItDown для Office/PDF с текстом, Docling для сканов/OCR, LibreOffice для старого `.doc` |

Текущая Supabase используется для разработки, интеграционных тестов и
контролируемой демонстрации. Реальные данные коммерческого клиента в этот
контур не загружаются. Для первого клиента до запуска создаётся отдельный
PostgreSQL и object storage в Казахстане; параметры подключения, backup,
restore и cutover проходят отдельный release-gate.

## Карта окружений и доступов

Этот раздел — краткий канонический ответ на вопросы «где взять доступ» и
«через какой узел идёт запрос». Значения токенов, паролей, private keys и DB URL
здесь не хранятся.

### Vercel

Vercel account/team: user `kamillalmscrm`, team
`kamillalmscrms-projects` (`team_EknCOCWEL771BUDea5UFM2Ba`).

| Назначение | Project | Git branch | Domain/alias | Backend сейчас |
|---|---|---|---|---|
| Production frontend | `web` (`prj_hJMzgp9QNFCwUMrsDEBZINpJJzBp`) | `master` | `app.kml.kz` | KZ production API `https://api.kml.kz/api` |
| Dev frontend | `kamilya-lms-dev` (`prj_JN1xM4BMmhoHzDt6joPaCBXvOSLk`) | `dev` | `kamilya-lms-dev.vercel.app` | KZ staging `https://api.kml.kz/api` |

Канонический источник API-токена — корневой `.env`, имя `vercel_token`.

Для отдельного репозитория публичного лендинга provider credentials берутся
только из `C:\Kamilya New\kamilya-landing\.env.local`: GitHub token имеет имя
`github_landing_token`, Vercel token — `vercel_landing_token`. Не подменять их
`GITHUB_TOKEN` или Vercel credentials из `Kamilya-NEW`; перед mutation проверять
только наличие нужного имени без вывода значения.
Наличие одноимённой переменной в другом локальном env-файле не меняет источник
и не разрешает перебирать старые файлы.
Алгоритм работы агента:

1. проверить наличие имени переменной, не печатая значение;
2. загрузить значение в память процесса и использовать Vercel REST API с
   authorization header, а не передавать token в URL/CLI arguments;
3. перед мутацией прочитать project id, Git repository, production branch,
   domains, env targets и последний deployment;
4. после мутации повторно прочитать те же поля и проверить deployment exact
   SHA, состояние `READY` и HTTP/business smoke;
5. не использовать локальный `.vercel/project.json` как доказательство
   правильного проекта и не выполнять `vercel link` вслепую.

Dev project собирает только ветку `dev`; custom domain не назначен. Production
project `web`, его branch `master` и `app.kml.kz` нельзя менять в рамках dev
задачи. Dev deployment содержит только committed Git SHA: dirty worktree в
Vercel не попадает.

Зона `kml.kz` использует authoritative nameservers Cloudflare
`sureena.ns.cloudflare.com` и `syeef.ns.cloudflare.com`. Vercel verified domain
не означает управление DNS-записями: Vercel DNS records для зоны пусты. DNS
нужно менять только через подтверждённый Cloudflare account/API.

### Управляющие каналы VPS и Proxmox

| Target | Канонический источник доступа | Назначение и граница |
|---|---|---|
| Public proxy VPS, reachable target `92.38.49.167` | `C:\Kamilya New\.env`: `PROXY_VPS_HOST`, `PROXY_VPS_LOGIN`, `PROXY_VPS_PASSWORD` | SSH к proxy; target и host key проверяются до auth, пароль не выводится и не передаётся аргументом |
| Proxmox API | корневой `.env`: `VPS_URL`, `PVE_API_TOKEN_ID`, `PVE_API_TOKEN_SECRET` | VM/CT metadata и только явно разрешённые API/QGA operations; не является guest SSH |
| Legacy/общий VPS доступ | корневой `.env`: `VPS_LOGIN`, `VPS_PASSWORD`, `vps_root_password` | использовать только после точного сопоставления target; не подставлять для proxy/VM126/CT125 по догадке |
| Guest VM126/CT125 | подтверждённый host-specific SSH/WireGuard path | routine administration; если путь не подтверждён, это access gap, а не разрешение искать пароль |

Состояние на 18.08.2026: SSH-аутентификация к public proxy подтверждена,
`wg-quick@wg0` active, `10.77.77.2:8000/health` отвечает 200. На proxy создан
host-specific key `/root/.ssh/kamilya-vm126-admin`; через однократный
Proxmox/QGA bootstrap его public key установлен непривилегированному
пользователю `kamilya-admin` на VM126. Цепочка proxy ->
`kamilya-admin@10.77.77.2` с проверкой host key и `sudo -n` подтверждена.
`PermitRootLogin no` сохранён, ненужная копия ключа из root authorized_keys
удалена. Routine administration выполняется по SSH/WireGuard; console и QGA
остаются recovery/bootstrap-каналами, а не обычным способом deployment.

После двух последовательных ошибок одного доступа агент останавливается по
правилу `AGENTS.md`. Запрещено проверять старые `.env`, backup-файлы, соседние
репозитории, другие логины/пароли/порты или обходить host-key verification.
Встроенная Proxmox console/noVNC допускается только для явно разрешённого
bootstrap/recovery; она не является обычным способом deployment.

Историческое provider-имя `vds36463.vpsza500.kz` на 17.08.2026 возвращает
NXDOMAIN. Рабочий SSH/HTTP target берётся из `PROXY_VPS_HOST`; нельзя снова
переключаться на неразрешаемое имя. На 18.08.2026 новый Proxmox API token
подтверждён чтением VM126 и QGA `agent/info`; значения token id/secret в
документации и логах не сохраняются.

### Трафик: текущее состояние

```text
Production browser
  -> app.kml.kz
  -> Vercel project web / master
  -> https://api.kml.kz/api
  -> proxy Nginx / TLS
  -> WireGuard -> VM126 FastAPI/workers/Valkey/file runtime
  -> private DB path -> CT125 PostgreSQL/pgvector

Dev browser
  -> kamilya-lms-dev.vercel.app
  -> Vercel project kamilya-lms-dev / dev
  -> https://api.kml.kz/api
  -> proxy Nginx / exact CORS allowlist
  -> WireGuard -> VM126 FastAPI

KZ production management/ingress path
  -> public proxy VPS (TLS/Nginx + WireGuard hub 10.77.77.1)
  -> WireGuard
  -> VM126 / 10.77.77.2:8000
       API + Celery workers + Valkey + local file runtime
  -> private DB path
  -> CT125: native PostgreSQL 17 + pgvector + encrypted backup
```

Для KZ production подтверждены API/worker/broker/file runtime на VM126 и database,
RLS, backup/restore на CT125. На proxy добавлен отдельный virtual host
`api.kml.kz`, который через WireGuard проксирует на `10.77.77.2:8000`.
17.08.2026 в authoritative Cloudflare создан DNS-only A-record на proxy,
выпущен сертификат Let's Encrypt, открыт HTTPS listener `443`, HTTP настроен на
redirect и внешний HTTPS `/health` вернул 200. После tenant/business smoke и
подготовки rollback production environment Vercel project `web` переключён на
`https://api.kml.kz/api`; новый deployment `dpl_5fYKAQhbzgDT3PfpmtvopJq8hre5`
имеет состояние `READY` и собран из того же exact SHA
`69ef25c3383ddd35443e621618c640d708c867ba`, что и предыдущий frontend.
Render/Supabase остаются dev/demo-контуром и не являются production backend
для `app.kml.kz`.

### Действующая production-схема после cutover 2026-08-17

Vercel можно сохранить как frontend. После подтверждённого cutover меняется
только backend destination конкретного Vercel environment:

```text
app.kml.kz on Vercel
  -> отдельный публичный API hostname с TLS на proxy VPS
  -> proxy Nginx
  -> WireGuard 10.77.77.1 -> 10.77.77.2:8000
  -> VM126 API/workers/storage runtime
  -> CT125 PostgreSQL/pgvector по private-only DB path
```

Cutover подтверждён внешним `/health`, production login bundle, API login,
`/users/me`, courses, documents, training log и staff-structure smoke под
контролируемой учётной записью tenant `too-lombard-sandyk`. CT125 имеет schema
head `0111`, private runtime roles без SUPERUSER/BYPASSRLS и активный ежедневный
encrypted backup. Render/Supabase сохранены как dev/demo-контур и rollback
destination; смешивать их очереди, данные или storage с KZ production нельзя.

19.08.2026 отдельно подтверждён candidate assessment production flow. Vercel
frontend содержит manager/public candidate routes на SHA `7b44f11`; VM126 API и
workers работают на image `kamilya-api:db797fd`, CT125 остаётся на `0111`.
Полный disposable journey на опубликованном release tenant Sandyk прошёл от
создания кампании и protected link/PIN до consent, результата и CSV; candidate
не создаёт staff user. Все synthetic записи после проверки удалены. Candidate
retention timer включён, активен и имеет последний успешный recovery run.

## Исторический Render/Supabase baseline (dev/demo fallback)

Application release `c4a5eb8bf58989eff4f4338272dc68941bd416bd`
был production baseline на 2026-08-06 и после KZ cutover сохранён только как
историческая dev/demo/rollback-точка:

- GitHub CI `31092967471` passed; production smoke `31092967755` passed;
- Vercel deployment `dpl_AYjE7QGd1n9hRv5tARDfvYx1WUAP` READY;
- Render deployment `dep-d9q623bm8hqs73e1r40g` live, health HTTP 200;
- VPS checkout `/opt/kamilya-worker` на exact application release;
- три Celery nodes `fast`, `documents`, `ai` отвечают и потребляют только свои
  очереди; AI concurrency 2, document concurrency 1;
- API допускает не более двух активных AI-задач на tenant; третья получает
  стабильный `429` с `Retry-After`, а UI показывает очередь только своей компании;
- converter routing `1.2`: digital PDF/Office идут через MarkItDown, сканы
  через Docling OCR; тяжёлая конвертация ограничена одним процессом;
- Architect/Writer удерживают взаимно исключающие границы уроков по всему
  курсу, а OCR lexical fallback приоритетно использует точные заголовки
  разделов;
- watchdog каждые пять минут проверяет сервисы, три worker и глубину очередей;
- dev/test Supabase остаётся текущей БД; KZ DB/storage для коммерческого клиента
  является отдельным release gate.

Проверка 50 одновременных digital-PDF запросов к converter прошла без ошибок.
Это не подтверждает SLA для 50 многостраничных сканов или 50 одновременных
генераций курсов. Проверенные пределы и расчёты находятся в
[`INFRA_CELERY_WORKER.md`](INFRA_CELERY_WORKER.md).

Технический и прикладной P0 закрыты для контролируемого первого pilot.
Отдельные условные gates сохраняются для SCORM, kiosk, KZ data residency и SLA
массовой нагрузки. Полный список находится в
[`PRODUCTION_READINESS.md`](PRODUCTION_READINESS.md).

## Роли

| Роль | Ответственность |
|---|---|
| `superadmin` | Платформа, tenants, AI providers, операционные действия |
| `admin` | Организация tenant, системная команда, интеграции и доступы |
| `methodologist` | Источники, курсы, тесты, сотрудники, правила обучения, назначения, результаты |
| `student` | Обучение, тесты, программы и сертификаты |

Удалённые роли `teacher` и `org_admin` не поддерживаются. Один пользователь
может иметь несколько назначенных ролей, но в сессии выбирает одну активную
роль. Навигация и API не объединяют полномочия всех ролей.

Канонические границы:

- tenant admin не создаёт курсы, тесты, обучающихся и назначения;
- methodologist владеет staff import, приглашениями и журналом обучения;
- `/admin/team` содержит только системную команду tenant;
- `/admin/enrollments` является legacy redirect, а не отдельной функцией;
- superadmin не получает tenant-возможности без контролируемого tenant context.

## Основные продуктовые потоки

### Регистрация tenant

1. Компания заполняет `/register-tenant`.
2. Если переход выполнен с публичного лендинга, UTM-метки, CTA-источник и
   referrer передаются в API и сохраняются в настройках tenant, lead и audit.
3. Создаются tenant, первый `admin` и trial limits.
4. Вход выполняется по email OTP через Resend или настроенному Telegram-flow.
5. Администратор создаёт системного пользователя с ролью `methodologist`.
6. Admin onboarding завершается после формирования системной команды; учебные
   шаги показываются только methodologist.

### Подготовка структуры

1. Методолог открывает `Сотрудники и структура`.
2. Сотрудники добавляются вручную или через Excel/CSV preview и mapping.
3. Backend нормализует `Department -> Position -> User`.
4. После commit отображается организационная структура.
5. Правила организации, отдела и должности материализуют назначения через
   общий recompute kernel.

### Курс из документов

1. Методолог загружает документы в каноническую библиотеку.
2. Ingestion извлекает текст и embeddings.
3. Совместимость источников проверяется до генерации.
4. Методолог выбирает один смысловой кластер либо явно задаёт цель объединения.
5. Для нового курса backend tenant-scoped проверяет, не использованы ли уже
   выбранные источники. Повторное использование требует явной причины до
   резервирования лимита; существующий draft с `course_id` продолжает штатную
   регенерацию без этого gate создания нового курса.
6. AI job создаёт независимый draft курса и тестов с трассировкой к источникам
   и, при повторном использовании, сохраняет `reuse_reason` в provenance.
7. В списке курсов непроверенный AI-draft имеет статус **Требует проверки**:
   прямое действие публикации недоступно до явного одобрения методологом.
8. Методолог проверяет, редактирует, одобряет и затем публикует курс.
9. В редакторе AI-помощник может дать read-only рекомендацию аудитории по
   текущей структуре tenant. Рекомендация не создаёт назначения или правила;
   для опубликованного курса она только ведёт на контекстный экран
   `/assignments?course_id=...`.

### Должностная инструкция

1. Инструкция привязывается к должности.
2. Из неё создаётся отдельный grounded-курс с provenance/version.
3. Курс входит в профиль квалификации должности.
4. Назначения пересчитываются для сотрудников этой должности.

### Отраслевая заготовка для финансовой организации

1. Методолог открывает карточку заготовки из списка курсов и выбирает русский
   или казахский вариант.
2. Версия `2026.1` создаёт обычный tenant-scoped draft: один модуль, восемь
   тематически разделённых уроков, восемь тестов и шестнадцать вопросов.
3. «70% готово» является продуктовой оценкой базового содержания, а не
   юридической оценкой соответствия. Оставшиеся восемь обязательных пунктов
   описывают системы, данные, доступы, удалённую работу, носители, проверку
   операций, канал инцидентов и различия филиалов/ролей конкретной компании.
4. Методолог может выбрать готовые документы своего tenant как источники для
   проверки. Их текст не вставляется автоматически и выбор не означает
   юридической экспертизы.
5. Повторное безопасное заполнение обновляет только неизменённый draft. Если
   структура или текст уже правились вручную, дальнейшая работа выполняется в
   редакторе курса без автоматической перезаписи.
6. Одобрение блокируется до 100% checklist. Затем действуют обычные review,
   publish, immutable release, assignment и evidence-контуры.

### Доставка и подтверждение

1. Отдельный курс назначается из карточки курса или сотрудника либо
   автоматическим правилом организации, отдела или должности.
2. Программа назначается человеку, группе, отделу или должности; cohort хранит
   только состав аудитории.
3. При подтверждении ручного назначения backend создаёт Enrollment, а для
   существующего сотрудника без подтверждённого способа входа создаёт связанную
   `UserInvitation` без второго `User`. Ссылка создаётся строго по выбранному
   `user_id`; нормализованный email уникален внутри тенанта. Bulk endpoint
   ставит доставку ссылки в Celery. UI показывает delivery status и сохраняет
   персональную ссылку для manual fallback при недоступном provider/broker.
4. Обучающийся открывает ссылку, проверяет кадровые данные в режиме чтения и
   подтверждает рабочий email шестизначным OTP. ФИО, табельный номер и пароль
   повторно не вводятся. Неверный или истёкший код показывает ошибку на том же
   экране и не сбрасывает пользователя на общий login. Успешная проверка
   создаёт access-сессию и защищённую refresh-cookie, после чего открывается
   единственный назначенный курс либо кабинет обучающегося.
5. Проходит уроки и обязательные тесты. После результата теста может вернуться
   в тот же курс или, при успешной попытке, сразу открыть следующий урок.
6. Backend сохраняет прогресс и завершает курс идемпотентно.
7. При выполнении условий выдаётся сертификат. В момент выдачи фиксируются имя
   сотрудника, название курса, настройки эмитента, срок действия и версия
   PDF-шаблона. Последующее изменение настроек tenant не меняет уже выданный
   документ.
8. Журнал обучения показывает назначение, его источник, прогресс, результат и
   доказательство.

### Процедуры, restricted share и retention

1. Methodologist создаёт versioned tenant procedure в `draft`, заполняет
   approval, legal/local basis, confirmation method и retention metadata.
2. `internal_attestation` нельзя активировать без snapshot rules состава,
   quorum и записи решения; `admission_decision` — без authority, записи
   решения и effective date. Это configuration gate, не workflow решения.
3. Generic evidence create/correction отклоняет `training`, `knowledge_check`,
   `internal_attestation` и `admission_decision`: system и regulated события
   создаются только соответствующим доверенным workflow.
4. Evidence share материализует точные PDF/ZIP bytes, SHA-256 и source event
   ids; ссылка имеет expiry <= 31 дня, download cap, revoke, Redis rate limit и
   non-PII access log.
5. Retention policy задаётся по procedure type. Dry-run/manual purge ограничен
   `max_roots <= 100`, использует persistent tenant cursor и не удаляет active
   legal hold или активную share-ссылку.
6. Scheduled purge и backup retention остаются backlog.

Сертификат формируется в A4 landscape, содержит номер, даты, QR-код и
каноническую ссылку `/verify/certificate/{number}`. Публичная проверка не требует
авторизации и возвращает только данные, напечатанные на сертификате, и статус
`active`, `expired` или `revoked`; email, внутренние идентификаторы и служебная
причина отзыва наружу не выдаются. PDF хранится с версией шаблона и SHA-256,
поэтому восстановление из storage выполняется только из снимка на момент выдачи.

Администратор tenant настраивает эмитента, подписанта, срок и примечание и видит
реальный PDF-предпросмотр без сохранения тестового сертификата. Методолог может
необратимо отозвать сертификат в tenant-контуре; операция и внутренняя причина
фиксируются в журнале аудита.

Самостоятельные пункты меню `/competencies`, `/training-rules`, `/invitations`
и `/assignments` скрыты: они остаются каноническими deep-link/API-контурами,
но открываются из должности, отдела, курса или сотрудника. Отдельное назначение
`Quiz` не используется: тест урока наследует доступ назначенного курса.

## Ключевые технические инварианты

- Каждая tenant-сущность имеет `tenant_id`, backend-проверку и RLS/FORCE RLS.
- Runtime использует роль БД без `BYPASSRLS`; миграции используют отдельный URL.
- Course/user/position/document IDs валидируются в текущем tenant.
- Завершённое обучение не удаляется при изменении автоматического правила.
- Повторный recompute не создаёт дублирующее назначение.
- Сертификат создаётся backend и идемпотентно.
- Несвязанные документы не смешиваются в один курс молча.
- При отсутствии релевантного источника grounded generation останавливается.
- AI generation и document ingestion показывают состояния queue/running/error,
  stalled и безопасное повторение действия.
- `/admin/super/operations` доступен только superadmin и показывает агрегаты
  очереди, документов, DB pool и процесса без tenant PII.
- Секреты хранятся только в `.env` и provider secrets.

## Локальная среда и секреты

- Локальный `.env` находится в корне репозитория и игнорируется Git.
- Runtime и migration DB URLs разделены.
- Render, Vercel, GitHub, Resend, Supabase и VPS credentials не печатаются в
  документацию или логи задачи.
- Перед добавлением новой переменной проверяется `.env.example`; значения не
  коммитятся.

## Правило документации

После изменения поведения:

1. обновить `PROJECT.md` или внутреннюю документацию;
2. обновить пользовательское руководство, если меняется UI/flow;
3. обновить ADR, если меняется долговечное архитектурное решение;
4. обновить `PRODUCTION_READINESS.md`, если меняется release gate;
5. обновить `PRODUCT_BACKLOG.md`, если задача открыта или закрыта;
6. не создавать отдельный исторический отчёт, дублирующий эти документы.
## Current exact KZ release — 2026-08-24

- `GIT-DERIVED`: backend application release
  `d17a9206086d8557f797a13563353c406d0ce9f4`; GitHub CI run `32743293275`
  passed all backend, unit, PostgreSQL 17 + pgvector RLS, release/security,
  frontend, quality and secrets jobs.
- `RUNTIME-DERIVED`: VM126 API and all three application workers use
  `kamilya-api:d17a9206086d`; public and private `/health` report
  `kz-production` and the full release SHA. All four application containers are
  running with zero restarts and no error-pattern matches after deployment.
- `RUNTIME-DERIVED`: live Alembic remains `0131 (head)`. This release did not
  run a migration and did not change CT125, tenant data, blob data, Valkey,
  Docling or the frontend. The prior exact release
  `760eeb72cac972a9ff2b2763d770f9cfc31d15eb` remains available as the rollback
  image and source directory.
- `RUNTIME-DERIVED`: the exact-SHA public endpoint verifier passed. A
  no-credential, no-file probe of `/api/v1/documents/upload` returned the
  expected HTTP 401 instead of edge HTTP 503 and created no application data.
  The first authenticated production upload is intentionally deferred to the
  owner-controlled synthetic tenant rehearsal.
- `RUNTIME-DERIVED`: the VM126 operational watchdog now expects the exact new
  SHA and image; its service and timer are successful, enabled and active.
- `BLOCKED`: the current push-capable GitHub PAT cannot read or update repository
  Actions Variables (`HTTP 403`), so no provider variable or manual workflow
  dispatch was changed. Scheduled `production-smoke.yml` does not consume that
  variable; it continues its independent public endpoint check.
