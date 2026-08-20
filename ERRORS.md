# Журнал ошибок и предотвращения повторов

Актуально на: 2026-08-20.

Это единственный оперативный журнал подтверждённых ошибок рабочего процесса,
неверных предположений, исправлений и профилактических проверок Kamilya LMS.
Открытые продуктовые задачи хранятся в `docs/PRODUCT_BACKLOG.md`, текущее
устройство системы — в `PROJECT.md` и `docs/PROJECT-CONTEXT.md`, история
изменений — в Git.

Секреты, токены, пароли, строки подключения, cookies, приватные ключи,
персональные данные и необработанные логи сюда не помещать.

## Как пользоваться

- Читать файл полностью до анализа, кодирования, миграций, provisioning,
  тестирования, build, deployment, commit и push.
- Перед рискованной процедурой повторно читать относящиеся к ней категории.
- При совпадении симптома сначала выполнять указанную профилактическую
  проверку, а не повторять неудачный путь.
- Новую запись добавлять только после подтверждения причины, исправления и
  проверки. Неподтверждённую причину явно помечать как гипотезу.
- Повтор прежней причины обновляет существующую запись, а не создаёт дубль.
- Устаревшую запись удалять или переписывать под действующий источник истины;
  неверное legacy не сохранять даже с пометкой «устарело».
- Для параллельной работы основной агент владеет итоговым изменением журнала.
  Другие агенты передают черновик из полей ниже либо меняют только заранее
  согласованную уникальную секцию. Перед patch нужно перечитать текущий файл.

Формат записи: уникальный `CATEGORY-NNN`, дата, наблюдаемый симптом,
подтверждённая причина, действующее исправление, фактическая проверка и
конкретная профилактика. Если исправление ещё не завершено, дополнительно
указываются статус, безопасный временный путь и условие пересмотра.

## TOOL-001 — Скриншот или браузерный контекст ошибочно принят за scope проекта

- Дата: 2026-08-13.
- Симптом: агент начал работу в другом репозитории после скриншота интерфейса,
  хотя пользователь явно не менял проект с Kamilya LMS.
- Причина: ambient browser state и визуальное сходство интерфейса были ошибочно
  приняты за разрешение сменить рабочую область.
- Исправление: проект по умолчанию ограничен `Kamilya-NEW` и
  `kamilya-landing`; другой репозиторий допустим только при прямом указании в
  текущем запросе.
- Проверка: корневое workspace-правило и `AGENTS.md` требуют проверить scope и
  рабочее дерево до изменений; текущая процедура не изменила внешний проект.
- Профилактика: перед первым чтением или patch разрешить абсолютный путь цели и
  остановиться, если он находится вне двух каталогов Kamilya и не назван
  пользователем прямо.

## SECRET-001 — Диагностика или документация раскрывает значение секрета

- Дата: 2026-08-13.
- Симптом: диагностический traceback либо старый технический журнал мог
  содержать полную строку подключения или другое значение credential.
- Причина: команда выполнялась без проверки безопасного формата вывода, а
  исторический журнал сохранял необработанные операционные детали.
- Исправление: текущий журнал хранит только имена переменных и безопасные
  факты; старый смешанный журнал удалён из рабочего дерева. Появившееся в
  выводе значение считается скомпрометированным и требует отдельной ротации у
  владельца секрета.
- Проверка: CI запускает `detect-secrets`, а release-contract gate проверяет
  `ERRORS.md` на приватные ключи, credential URL и известные secret prefixes,
  не выводя найденное значение.
- Профилактика: до команды с `.env` или provider API определить её stdout и
  stderr; выводить только имена, количество, статус и маскированные
  идентификаторы. При случайном раскрытии немедленно прекратить копирование,
  сообщить владельцу и не считать инцидент закрытым без подтверждённой ротации.

## MIGRATION-001 — Зелёный deploy и health скрыли отставшую схему БД

- Дата: 2026-08-13 (исходный случай 2026-06-29).
- Симптом: API возвращал health HTTP 200, но первый путь, использующий новые
  таблицы или колонки, падал; `alembic_version` был ниже repository head.
- Причина: миграции не имели подтверждённого владельца выполнения, а готовность
  приложения ошибочно вывели из deploy status и health endpoint.
- Исправление: Render применяет миграции в `preDeployCommand`, Docker запускает
  их fail-closed до Uvicorn, HTTP lifespan миграции не выполняет.
- Проверка: `python scripts/ci/release-contract-gate.py` проверяет одного
  владельца миграций и линейную цепочку; release отдельно сверяет
  `alembic current`, `alembic heads` и затронутую схему.
- Профилактика: перед объявлением schema-changing release готовым сверить live
  revision с head, проверить нужные таблицы/колонки/ограничения и только затем
  выполнить бизнес-smoke, который использует изменение.

## MIGRATION-002 — Offline SQL не проходит через историческую миграцию 0003

- Дата: 2026-08-13.
- Симптом: `alembic upgrade ... --sql` останавливается на revision `0003` при
  попытке инспектировать `MockConnection`.
- Причина: историческая миграция условно изменяет схему через
  `sa.inspect(op.get_bind())`, а Alembic offline mode не предоставляет реальное
  соединение для inspector.
- Исправление: состояние цепочки проверяется AST-gate и `alembic heads`, а
  фактический upgrade — на разрешённой PostgreSQL БД с последующими
  schema/RLS-тестами.
- Проверка: исходник `0003_add_enrollment_progress_documents.py` содержит
  inspector-зависимую развилку; release-contract gate независимо подтверждает
  единственную линейную цепочку.
- Профилактика: не использовать offline SQL как единственное доказательство
  применимости полной истории. Изменение уже применённой миграции допустимо
  только по отдельному compatibility-плану; до этого обязательна реальная
  PostgreSQL migration test.

## TENANT-001 — Привилегированная DB-сессия дала ложный успех RLS-проверки

- Дата: 2026-08-13.
- Симптом: direct query в интеграционном тесте видел tenant-данные, которые
  runtime-приложение не должно читать напрямую.
- Причина: fixture использовала владельца миграций; owner/bypass-права не
  воспроизводили ограничения роли приложения `lms_app`.
- Исправление: данные fixture создаются привилегированной сессией, но security
  assertion выполняется после `SET LOCAL ROLE lms_app` и установки точного
  tenant context.
- Проверка: DB/RLS suites явно переключаются на runtime-роль; release evidence
  различает миграционное создание данных и runtime-проверку видимости.
- Профилактика: любой тест RLS, прямых grants или cross-tenant denial обязан
  доказать текущую роль и tenant context до запроса; успешный тест под owner не
  является security evidence.

## DEPLOY-001 — Worker остался на другом release, чем web и API

- Дата: 2026-08-13.
- Симптом: Vercel и Render были готовы на новом commit, но отдельный VPS Celery
  worker продолжал исполнять прежний код или не регистрировал новую задачу.
- Причина: worker разворачивается отдельным процессом и не обновляется
  автоматически вместе с Git push, Vercel или Render.
- Исправление: release manifest независимо фиксирует GitHub CI, Vercel commit,
  Render commit, Alembic revision, checkout worker и обязательные Celery tasks.
- Проверка: worker проверяется по exact commit, active/enabled units, Celery
  ping, registered tasks и очередям; только после этого выполняется business
  smoke.
- Профилактика: не называть release готовым по HTTP 200 или provider status.
  Перед production sign-off сверить exact SHA всех исполняемых контуров и
  отдельно подтвердить DB и пользовательский flow.

## WORKER-001 — Celery task использовал несовместимый asyncio event loop

- Дата: 2026-08-13 (исходный случай 2026-06-29).
- Симптом: реальная Celery-задача с DB-доступом сообщала ошибку о Future,
  прикреплённом к другому loop; внешний task state при этом мог оставаться
  успешным, хотя доменное изменение не произошло.
- Причина: Celery prefork, импортированный async SQLAlchemy/asyncpg engine и
  вручную созданный event loop имели разный lifecycle; дополнительно task
  перехватывал ошибку элемента и возвращал summary вместо падения всей задачи.
- Исправление: sync task запускает coroutine через `asyncio.run()`, а сессия БД
  создаётся внутри этого coroutine; результат задачи содержит явные
  `failed_user_ids` и ошибки элементов.
- Проверка: focused test подтверждает регистрацию задачи, а production worker
  smoke использует непустой disposable input и проверяет не только Celery
  state, но и summary и фактический доменный side effect.
- Профилактика: после изменения async background job запускать её через реальный
  prefork worker; `SUCCESS` без проверки возвращённого результата и данных не
  считать доказательством выполнения.

## TEST-001 — Smoke для mutation проверял только SELECT

- Дата: 2026-08-13 (исходный случай 2026-06-30).
- Симптом: read-only smoke был зелёным, а первое реальное создание сущности
  завершилось HTTP 404/500 из-за несоответствия обязательных колонок и ORM.
- Причина: проверка не выполнила тот INSERT/UPDATE и тот application service,
  которые менялись; mock-тесты также не воспроизводили фактическую схему.
- Исправление: mutation smoke проходит реальный сервисный путь на disposable
  fixture и откатывает или удаляет созданные данные; обязательные колонки
  сверяются с PostgreSQL schema.
- Проверка: для новых mutation используются DB-backed integration tests и
  наблюдаемый API flow, а не только SELECT, план запроса или mock.
- Профилактика: тест исправления должен повторять глагол и boundary дефекта:
  INSERT проверяется INSERT, очередь — реальным worker, export — реальным
  файлом, UI — наблюдаемым действием.

## TEST-002 — Недоступная PostgreSQL была ошибочно заменена mock-доказательством

- Дата: 2026-08-13.
- Симптом: локальная DB-backed suite не стартовала с connection refused, после
  чего route seam или AsyncMock могли выглядеть как полное подтверждение RLS,
  concurrency либо транзакционной атомарности.
- Причина: разные уровни тестов не были явно разделены; отсутствие локального
  PostgreSQL приняли за разрешение ослабить acceptance gate.
- Исправление: unit/route-contract тесты используются как отдельное
  доказательство, а DB gate честно остаётся blocked до запуска на доступной
  мигрированной PostgreSQL.
- Проверка: отчёт обязан назвать, какие тесты действительно выполнились и какие
  остановились в fixture setup; DB/RLS/concurrency утверждения делаются только
  после реального integration pass.
- Профилактика: при connection refused не переписывать security test под mock.
  Проверить target/revision без вывода credentials, затем запустить исходный
  тест на разрешённой БД либо оставить release gate открытым.

## WIN-001 — Frontend build script использует POSIX env-синтаксис в PowerShell

- Дата: 2026-08-13.
- Симптом: `npm run build` на Windows не запускал Next.js, потому что script
  начинается с `NEXT_TELEMETRY_DISABLED=1`.
- Причина: inline assignment переменной окружения является POSIX-синтаксисом и
  не интерпретируется PowerShell как команда запуска приложения.
- Исправление: в PowerShell выполнять `$env:NEXT_TELEMETRY_DISABLED='1'`, затем
  `npx next build`; CI/Linux может использовать package script.
- Проверка: `apps/web/package.json` сохраняет POSIX script, а каноническая
  Windows-команда зафиксирована в `AGENTS.md` и проходит production build.
- Профилактика: на Windows использовать команды из `AGENTS.md`, а не механически
  копировать Linux shell snippets; перед объявлением build-pass проверить код
  завершения именно процесса Next.js.

## API-001 — Одна legacy NULL-строка ломала весь response list

- Дата: 2026-08-13 (исходный случай 2026-06-30).
- Симптом: list endpoint возвращал HTTP 422 и пустой UI, хотя записи существовали
  и другой endpoint их показывал.
- Причина: Pydantic response требовал непустой timestamp/legacy field, тогда как
  фактическая историческая строка содержала `NULL`; одна строка срывала
  сериализацию всего списка.
- Исправление: совместимый response schema допускает подтверждённую legacy
  форму, а данные исправляются forward migration/backfill, а не только
  ослаблением валидации.
- Проверка: schema `PositionResponse` допускает фактические nullable legacy
  поля; интеграционный тест list endpoint должен включать legacy-shape row.
- Профилактика: перед ужесточением response field сверить nullable/default в
  live/test schema и исторических миграциях; для list endpoint добавить хотя бы
  одну строку старой формы и проверить сериализацию полного ответа.

## AI-001 — HTTP 200 от LLM не означал завершённый структурированный ответ

- Дата: 2026-08-14.
- Симптом: `morosystems/ThinkingCap-Qwen3.6-27B-NVFP4` через текущий vLLM
  endpoint при `response_format=json_schema` начинал корректный JSON, затем
  заполнял остаток ответа пробелами и завершался по лимиту токенов. Повтор с
  лимитом 8192 занял 156 секунд, вернул `finish_reason=length` и невалидный
  JSON, несмотря на HTTP 200.
- Причина: подтверждена несовместимость именно текущей пары
  model/runtime/request со строгим structured-output режимом. Тот же
  production-подобный Architect prompt без `response_format` завершился за
  19 секунд и вернул валидную структуру курса.
- Исправление: для ThinkingCap сохраняется действующий путь Kamilya — обычный
  JSON prompt, локальный разбор по схеме, валидация и контролируемый retry.
  `response_format=json_schema` для этой модели не включается до отдельной
  повторной квалификации после обновления model/runtime.
- Проверка: строгий режим воспроизвёл дефект при лимитах 5000 и 8192; обычный
  Architect prompt сформировал 2 модуля и 4 урока с четырьмя уникальными
  исходными заголовками; Assessment prompt сформировал 5 корректных MCQ.
- Профилактика: provider qualification проверяет не только HTTP status, но и
  `finish_reason`, число output tokens, время ответа и фактический schema parse.
  HTTP 200 с `finish_reason=length` не считается успешной генерацией.

## DEPLOY-002 — Официальный API Dockerfile не собирался из корня репозитория

- Дата: 2026-08-17.
- Симптом: первая clean-SHA сборка либо не находила общий пакет `packages`,
  либо Poetry завершалась с `No file/folder found for package api`; в ранее
  собранном обходном образе импорт приложения требовал ручной `PYTHONPATH`.
- Причина: Dockerfile смешивал build context `apps/api` и корень репозитория,
  копировал `../../packages`, а dependency-layer пытался установить root-пакет
  до копирования исходников.
- Исправление: официальный build выполняется из корня; Dockerfile сначала
  копирует `apps/api/pyproject.toml`, lock и `/packages`, устанавливает
  зависимости с `--no-root`, затем копирует `apps/api` и задаёт
  `PYTHONPATH=/app`.
- Проверка: image `e9fc8f3` собран официальным Dockerfile на VM126; импорт
  FastAPI прошёл, Alembic показал `0110 (head)`, staging API отвечает health и
  выполнил реальные registration/public-lead mutation flows.
- Профилактика: Dockerfile имеет source-contract тест; release gate обязан
  включать реальный `docker build` из документированного build context и импорт
  приложения внутри нового image до замены контейнера.

## MIGRATION-003 — Чистый Alembic head не обеспечил runtime-права bounded-функций

- Дата: 2026-08-17.
- Симптом: свежая PostgreSQL достигла head, но `lms_app` получила permission
  denied на legacy-таблицах; после узкого grant регистрация всё ещё возвращала
  HTTP 500 `lead tenant mismatch`.
- Причина: миграция 0033 имела фиксированный неполный список runtime-таблиц, а
  SECURITY DEFINER функции 0094 на свежем least-privilege кластере принадлежали
  migration-роли. FORCE RLS-политики были назначены только `lms_app`, поэтому
  владелец функции не видел только что вставленный lead и outbox.
- Исправление: 0109 выдаёт `lms_app` права только на `tenants`,
  `content_blocks`, `questions`, `quiz_choices`; 0110 добавляет политики только
  фактическому владельцу bounded CRM-функции. Прямые grants на outbox и
  BYPASSRLS приложению не выдаются.
- Проверка: реальная `lms_app` читает нужные таблицы, direct SELECT обеих
  outbox-таблиц отклоняется, registration и public lead возвращают 201,
  cross-tenant users/settings остаются невидимыми и недоступными для UPDATE.
- Профилактика: fresh-cluster gate после `upgrade head` обязан выполнять
  catalog privilege audit, SECURITY DEFINER mutation, public function flow и
  cross-tenant RLS attack от реальной runtime-роли; managed-provider grants не
  считаются частью миграционной истории.

## STORAGE-001 — Local storage жил внутри одного контейнера

- Дата: 2026-08-17.
- Симптом: staging API был healthy, но при `STORAGE_BACKEND=local` файлы
  документов, evidence и сертификатов сохранялись в writable layer API;
  workers не разделяли этот каталог, а recreate удалил бы данные.
- Причина: compose не монтировал общий персистентный storage root во все
  процессы, использующие `get_storage()`.
- Исправление: API и три worker используют общий bind-mount
  `/opt/kamilya-runtime/blob-storage:/app/storage/certificates`; host-root имеет
  `0700 root:root`. Воспроизводимый topology-файл добавлен в `infra/compose`.
- Проверка: API-контейнер записал тестовый объект, document-worker прочитал его,
  ops-worker удалил, после чего host-path подтвердил отсутствие тестового файла.
- Статус: runtime persistence исправлена. Ежедневный
  `kamilya-blob-backup.timer` включён на VM126; зашифрованный архив создан на
  CT125 с правами `0600`, SHA-256 проверен, расшифровка и чтение списка tar
  успешно выполнены. Production cutover по-прежнему запрещён до отдельной
  проверки ingress/мониторинга и утверждённого переноса production-данных.
- Профилактика: перед release выполнить cross-container storage smoke, recreate
  smoke, backup/restore drill и проверку заполнения диска; health API без этих
  шагов не считается доказательством сохранности файлов.

## ACCESS-001 — Verified domain ошибочно принят за authority управления DNS

- Дата: 2026-08-17.
- Симптом: `kml.kz` отображался verified в Vercel, но Vercel DNS records были
  пусты; историческое provider-имя proxy возвращало NXDOMAIN, а `api.kml.kz`
  не существовал.
- Причина: привязка домена к Vercel project была ошибочно смешана с
  authoritative DNS ownership. Фактические NS зоны принадлежат Cloudflare;
  provider hostname proxy больше не разрешается.
- Исправление: canonical proxy target берётся из `PROXY_VPS_HOST`; через
  подтверждённую Cloudflare-сессию создан DNS-only A-record `api.kml.kz`,
  после authoritative/public DNS проверки на proxy выпущен TLS-сертификат.
- Проверка: обе authoritative Cloudflare NS и Google Public DNS вернули
  `92.38.49.167`; proxy SSH и WireGuard active; `443` слушает; внешний
  `https://api.kml.kz/health` с проверкой имени сертификата вернул HTTP 200;
  HTTP возвращает redirect на HTTPS.
- Профилактика: до DNS mutation отдельно проверять NS/authoritative provider,
  существующую record и authority текущего credential. Verified domain,
  HTTP 200 по Host header и открытый firewall port не считать DNS/TLS/production
  evidence.

## DEPLOY-003 — Dev frontend указывал на неполный API base и неизвестный CORS origin

- Дата: 2026-08-17.
- Симптом: первый KZ dev deployment был собран с `NEXT_PUBLIC_API_URL` без
  суффикса `/api`; после исправления URL браузерный preflight нового Vercel
  origin возвращал 400.
- Причина: frontend добавляет к base URL пути `/v1/...`, поэтому Vercel value
  должен оканчиваться на `/api`. Новый отдельный project alias также не входил
  в существующий точный backend CORS allowlist.
- Исправление: dev value изменён на `https://api.kml.kz/api` и создан новый
  exact-SHA deployment. На proxy добавлен точный allowlist известных Kamilya
  origins с единым набором CORS headers; в source backend добавлен стабильный
  dev origin для следующего image deploy.
- Проверка: собранный login chunk содержит KZ API base и не содержит Render;
  dev/app/www preflight возвращает один allow-origin/credentials header,
  неизвестный origin — 400; invalid-login запрос дошёл до FastAPI и вернул 401.
- Профилактика: перед deployment читать фактический frontend URL contract,
  отдельно проверять compiled chunk, CORS preflight и actual response; HTTP
  health одного backend не доказывает работоспособность browser flow.

## TOOL-002 — Backend-команда запущена из неверного каталога monorepo

- Дата: 2026-08-17.
- Симптом: `poetry run alembic heads` из корня monorepo завершился сообщением,
  что `pyproject.toml` не найден.
- Причина: рабочий каталог составной диагностической команды был выбран как
  repository root, хотя backend Poetry project находится в `apps/api`.
- Исправление: backend Poetry/Alembic команды выполняются с `workdir=apps/api`;
  repository и documentation команды — из корня.
- Проверка: из `apps/api` команда `poetry run alembic heads` вернула единственный
  head `0111`.
- Профилактика: перед объединённой командой разделять repo-level и app-level
  operations по рабочим каталогам; не считать ошибку инструмента дефектом
  миграции.

## PROVISION-001 — Привилегированного пользователя создали через learner invitation

- Дата: 2026-08-18.
- Симптом: владелец получил письмо и код с формулировкой «пройти обучение», но
  обычная форма входа не отправляла код для ролей `admin` и `methodologist`.
- Причина: operational bootstrap ошибочно вызвал bulk learner-invitation с
  привилегированной ролью. Этот поток предназначен только для `student`,
  создаёт неактивную identity и требует отдельного принятия приглашения;
  канонические admin/user flows создают привилегированную identity активной.
- Исправление: существующая identity сохранена с теми же двумя ролями,
  переведена в `active`, ошибочное learner-приглашение отозвано, а владение
  адресом подтверждается стандартным login OTP. Пароль не задавался и не
  передавался.
- Проверка: production user имеет роли `admin` и `methodologist`, статус
  `active`; pending learner invitation отсутствует, а login lookup возвращает
  ровно одну активную identity с основной ролью `admin`.
- Профилактика: bulk `/users/invitations` использовать только для `student`.
  Для `admin`/`methodologist` применять admin/user service и перед отправкой
  проверять role, `is_active`, login mechanism и точный public URL.

## AUTH-001 — Email login нейтрально отвечал 200, но не создавал OTP в KZ production

- Дата: 2026-08-18.
- Симптом: `/auth/email/request-code` возвращал HTTP 200 и UI показывал
  «код отправлен», но письмо не могло прийти; в Valkey отсутствовал ключ
  `auth:email:login`.
- Причина: `lookup_login_user_by_email()` — bounded SECURITY DEFINER-функция —
  на fresh least-privilege PostgreSQL принадлежала `kamilya_migrator`.
  Таблица `users` использует FORCE RLS, а политика для фактического владельца
  функции отсутствовала, поэтому lookup всегда возвращал ноль строк. Managed
  provider скрывал дефект привилегиями владельца функции.
- Исправление: миграция `0111` динамически определяет фактического владельца
  bounded-функции и добавляет ему только SELECT policy на `users`. Прямая
  видимость для `lms_app`, изменение ролей и обход RLS не выдаются; приложение
  сохраняет только EXECUTE функции.
- Проверка: CT125 перешёл с `0110` на единственный head `0111`; runtime lookup
  вернул одну активную identity, реальный request-code создал login OTP в
  Valkey с TTL около 300 секунд и нулём неудачных попыток. Семь целевых
  migration/security тестов и Ruff прошли.
- Профилактика: fresh-cluster release gate обязан проверять не только grants и
  HTTP 200, но и side effect нейтральных anti-enumeration endpoints: lookup
  result, наличие purpose-bound OTP и фактическую доставку. SECURITY DEFINER
  функции под FORCE RLS тестировать от реальной runtime-роли и фактического
  владельца функции.

## CANDIDATE-001 — Ссылка кандидата создавалась, но публичный обмен PIN возвращал 404

- Дата: 2026-08-19.
- Симптом: методолог мог создать и активировать кампанию оценки, добавить
  кандидата и получить защищённую ссылку/PIN, однако публичный exchange не
  находил существующий credential и отвечал `404`.
- Причина: начальная tenant lookup-функция выполнялась до установки tenant
  context. Таблица credentials защищена `RLS` + `FORCE RLS`, а владелец
  `SECURITY DEFINER`-функции намеренно не имеет `BYPASSRLS`, поэтому запись была
  невидима до определения tenant.
- Исправление: новый capability token содержит открытый tenant UUID только как
  неавторитетный routing prefix и независимый криптографически случайный secret.
  API сначала разбирает UUID и устанавливает tenant context, затем внутри этого
  tenant проверяет полный SHA-256 token hash, expiry и revoke state. Неверный
  tenant prefix, token hash, PIN или отозванный credential доступа не дают;
  `BYPASSRLS` и расширенные grants не выдавались.
- Проверка: 27 candidate-focused tests и Ruff прошли. KZ production API и три
  worker развёрнуты на exact image `kamilya-api:db797fd`; PostgreSQL остался на
  head `0111`. Полный удаляемый production journey на опубликованном release
  tenant `too-lombard-sandyk` прошёл создание/активацию кампании, защищённое
  приглашение, PIN/consent exchange, детерминированный результат, manager result
  и CSV. Кандидат не появился в `users`; после проверки все synthetic записи
  удалены, residual state отсутствует.
- Сопутствующий эксплуатационный дефект: retention task был зарегистрирован в
  Celery, но host timer не был активирован. Unit переведён на запуск recovery
  внутри `worker-ops`; production timer теперь `enabled`/`active`, последний
  service result — `success`.
- Профилактика: public capability flow, которому tenant ещё неизвестен, должен
  использовать отдельно спроектированный неавторитетный routing key и выполнять
  полную авторизацию только после установки tenant context. Наличие route/UI и
  создание credential не являются production evidence без реального exchange,
  tenant-isolation проверки, cleanup и проверки retention scheduler.

## AI-002 — Retry теста потерял источник, а свободная цитата сделала grounding ненадёжным

- Дата: 2026-08-20.
- Симптом: первый disposable production-курс успешно создался, но два теста
  спрашивали о JSON, HTTP и REST вместо регламента. После первоначального
  исправления новый production job уже не сохранил плохие вопросы, однако пять
  раз отклонил ответы модели и завершился ошибкой примерно через 347 секунд:
  модель изменяла свободно копируемую `source_quote` или морфологию вопроса.
  После evidence-bank исправления полный job снова fail-closed завершился
  ошибкой через 198 секунд: модель пять раз возвращала описание JSON Schema
  (`type/properties/required`) вместо экземпляра с вопросами, поэтому валидатор
  справедливо видел `MCQ count is 0`. После structured-output фикса следующий
  полный job сформировал структуру, но fail-closed отклонил две парафразы
  правильного ответа как не являющиеся дословной частью evidence. После
  server-owned answer фикса ещё один job отклонил один семантически связанный,
  но не содержащий общего лексического стема вопрос. Первый полностью успешный
  job затем показал quality-edge: один выбранный evidence заканчивался
  двоеточием перед перечнем и был формально grounded, но неполон как ответ.
- Причина: исходный retry действительно терял урок и использовал прошлый ответ;
  последующая защита устранила эту ошибку, но возложила на модель хрупкую задачу
  дословно повторять цитату и два лексических префикса. Семантически близкий
  ответ не мог пройти строгий substring-gate, хотя источник был доступен.
- Исправление: retry каждый раз строится из неизменного урока без сырого
  прошлого ответа. Сервер сам формирует из того же ограниченного 8000-символьного
  источника банк доказательств `E01...E24`; модель выбирает только существующий
  `source_quote_id`, а сервер подставляет авторитетную цитату. Правильный вариант
  остаётся дословным фрагментом этой цитаты, вопрос и объяснение обязаны
  использовать её термины, мета-термины JSON/HTTP/REST/API/schema/«формат» без
  источника запрещены. Assessment выполняется отдельным детерминированным
  клиентом с temperature `0.2`; lesson data остаются недоверенными, title
  принадлежит серверу, response body не журналируется. Дополнительно запрос
  использует provider-level `response_format=json_schema`, а prompt явно требует
  экземпляр данных и запрещает возвращать описание схемы. Модель выбирает
  evidence ID, формулирует вопрос и три дистрактора, но текст единственного
  правильного варианта и объяснение сервер детерминированно подставляет из
  выбранного evidence; дистрактор, совпадающий с evidence, отклоняется. Если
  вопрос модели не содержит ни одного evidence-стема, сервер заменяет только
  его формулировку на локализованный вопрос по короткой теме из evidence.
  Незавершённые фрагменты с финальным двоеточием исключаются из банка, а
  Markdown-разметка evidence снимается детерминированно перед показом ответа.
- Проверка: unit-suite `267 passed`; focused assessment/failover/release tests
  прошли. На том же production Qwen provider диагностический запрос без
  structured output вернул ключи схемы и `mcq=0`; с `json_schema` первая попытка
  вернула ровно 5 MCQ, пустые true/false и matching. Полный production job
  повторяется после выпуска exact commit; прямой Qwen 3.8 endpoint с VM126 пока
  недоступен, поэтому его free-pool нельзя включать до отдельного сетевого gate.
- Профилактика: успешный job и валидный JSON не являются quality evidence.
  Перед публикацией AI-курса проверять источник каждого вопроса и выполнять
  disposable production generation; fallback/retry обязан сохранять тот же
  source boundary и не обучаться на собственном невалидном ответе.

## API-002 — NULL email одного kiosk-пользователя ломал admin dashboard

- Дата: 2026-08-20.
- Симптом: stats, trial usage и users возвращали `200`, но весь admin dashboard
  отвечал `500` после появления student, созданного без email.
- Причина: kiosk/staff provisioning допускает `users.email = NULL`, тогда как
  dashboard response `UserListItem.email` требовал строку; Pydantic срывал
  сериализацию всего списка recent users.
- Исправление: dashboard-совместимый входной validator нормализует подтверждённый
  legacy `NULL` в пустую строку, не выдумывая адрес и не изменяя DB evidence.
- Проверка: regression test воспроизводит kiosk/student с `email=None`; пять
  admin P0 tests и полная unit-suite прошли. Production route повторяется после
  выпуска exact commit.
- Профилактика: list/dashboard response тестировать с каждой допустимой формой
  identity, включая kiosk и link-only learner без email; одна nullable строка
  не должна обрушать весь агрегированный экран.

## LEARNING-001 — Повторное назначение воскрешало завершённую программу

- Дата: 2026-08-20.
- Симптом: повторное назначение той же аудитории считало завершённую программу
  новой (`added=1`) и переводило assignment обратно в active.
- Причина: идемпотентный guard пропускал только status `active`; ветка
  reactivation применялась и к `completed`, хотя повторно активировать допустимо
  только явно отменённое назначение.
- Исправление: `active` и `completed` считаются skipped; `completed_at` и
  результат сохраняются. Только `cancelled` остаётся доступным для явной
  повторной активации.
- Проверка: 11 focused tests подтверждают `added=0/skipped=1` для completed,
  неизменность `completed_at`, отсутствие sync enrollment и разрешённую
  reactivation cancelled; полная unit-suite `261 passed`.
- Профилактика: идемпотентность назначения проверять отдельно для active,
  completed и cancelled. Завершённый learner outcome нельзя сбрасывать тем же
  массовым audience action, которым создаётся первое назначение.

## SECURITY-001 — Содержание урока исполнялось как сохранённый HTML

- Дата: 2026-08-20.
- Симптом: сохранённая строка урока с HTML-тегами превращалась в реальные DOM
  элементы на странице курса; обработчики событий и активные URL попадали в
  браузерный execution context.
- Причина: самописный `simpleMarkdown()` не экранировал вход, а его результат
  передавался в React `dangerouslySetInnerHTML`.
- Исправление: содержание урока строится только как React text nodes и
  ограниченные элементы `strong`, `em`, `br`. Raw HTML не парсится, поэтому
  теги из editor, документа или LLM остаются видимым безопасным текстом.
- Проверка: regression test сначала воспроизвёл DOM injection, затем подтвердил
  отсутствие `img`, `script` и `javascript:` link при сохранении базового
  выделения. Focused suite `5 passed`, typecheck и lint прошли, production build
  сформировал 57 страниц. Полная web-suite дала один несвязанный flaky failure
  contextual assignment; его отдельный повтор прошёл `9 passed`.
- Профилактика: не передавать persisted/API/LLM content в HTML sinks. Rich text
  добавлять только через безопасный AST/component renderer либо отдельно
  проверенный allowlist sanitizer с XSS corpus и CSP defense-in-depth.

## SECURITY-002 — Табельный номер использовался как единственный секрет киоска

- Дата: 2026-08-20.
- Симптом: знание общей ссылки киоска и табельного номера позволяло получить
  обычный пользовательский access JWT; разные ошибки дополнительно раскрывали
  существование, статус и соответствие должности сотрудника.
- Причина: табельный номер ошибочно считался credential, отдельного секрета,
  блокировки перебора и серверной привязки сеанса к активному киоску не было;
  новые журналы также сохраняли номер без маскирования.
- Исправление: администратор выпускает отдельный шестизначный PIN, в БД хранится
  только Argon2-хеш. Публичный exchange имеет нейтральную ошибку, пять попыток,
  15-минутный lockout и fail-closed IP rate limit через Valkey. JWT имеет тип
  `kiosk_access` и на каждом запросе сверяется с активными credential, киоском,
  тенантом, сотрудником и должностным scope. Миграция `0120` включает RLS,
  ownership trigger и маскирует исторические номера в журнале.
- Проверка: security/API suite `43 passed`, полный доступный API suite
  `998 passed`; 48 DB-backed тестов не стартовали из-за недоступного локального
  PostgreSQL. Web suite `317 passed`, typecheck, lint и production build
  (57 страниц) прошли. Alembic head — `0120`.
- Профилактика: публичный идентификатор никогда не считать аутентификатором.
  Capability-сеансы должны иметь независимый секрет, попытки/lockout,
  server-side revocation, tenant ownership, нейтральные ошибки и тест
  деградации rate limiter до release.

## SECURITY-003 — SCORM был заблокирован headers либо исполнялся бы на trusted API origin

- Дата: 2026-08-20.
- Симптом: frontend встраивал SCORM launch без `sandbox`, а общий API middleware
  одновременно отвечал `X-Frame-Options: DENY` и `frame-ancestors 'none'`.
  Простое снятие этих headers дало бы tenant-uploaded HTML/JavaScript доверенный
  API origin.
- Причина: launch shell, package assets, commit API и основной API не имели
  явной browser trust boundary; launch URL строился из `request.base_url`.
- Исправление: launch URL строится только из `SCORM_CONTENT_ORIGIN`; production
  без настройки отвечает `503`, а package/asset/commit на другом Host — `421`.
  Приложение использует sandboxed iframe. Статусный bridge версионирован и
  проверяет exact origin, frame source, случайный channel, type и status schema.
  Только точный SCORM host/path получает frameable CSP; app/API сохраняют DENY.
- Проверка: SCORM/API security suite `36 passed`; frontend role/SCORM suite
  `7 passed`; typecheck и lint прошли. Production DNS/proxy и malicious-package
  browser E2E остаются обязательным release gate и локальными тестами не
  заменяются.
- Профилактика: недоверенный executable content всегда выносить на отдельный
  cookieless origin. Не исправлять frame conflict глобальным снятием XFO/CSP;
  ingress должен публиковать только минимальный scoped route allowlist.

## SECURITY-004 — OOXML и converter не имели единого ограниченного trust boundary

- Дата: 2026-08-20.
- Симптом: API считывал upload целиком в память и проверял DOCX/XLSX только по
  префиксу `PK`. Existing/internal documents могли попасть прямо в локальный
  parser fallback; converter допускал запуск без ключа и systemd запускал его
  от root без ресурсных и filesystem ограничений.
- Причина: лимит размера сжатого файла ошибочно считался достаточным для ZIP-
  контейнера, а upload, storage и conversion использовали разные enforcement
  points. Аутентификация converter была условной: пустая настройка отключала
  проверку вместо отказа запуска production.
- Исправление: upload хешируется и сохраняется потоково. DOCX/XLSX до storage и
  повторно перед любым remote/local conversion проходят bounded central-directory
  preflight: обязательные части, unsafe paths, symlink, encryption, entry count,
  individual/total expanded size и compression ratio. Legacy DOC output также
  проверяется до parser. Converter всегда требует header, production не стартует
  с отсутствующим/коротким ключом; Docker/systemd используют пользователя
  `docling`, пустые capabilities, private tmp, strict filesystem, state directory,
  umask и CPU/RAM/task limits.
- Проверка: targeted document/converter suite `80 passed`; полный backend
  unit-suite `292 passed`; scoped Ruff `E9,F,I` прошёл. Реальный production
  rollout и adversarial archive/OCR smoke остаются отдельным gate.
- Профилактика: ZIP prefix и MIME не являются доказательством безопасного
  документа. Каждый parser boundary обязан повторять budgets; production helper
  service должен fail closed по auth и работать в sandbox с измеренными limits.

## SECURITY-005 — Production smoke подтверждал старый Render вместо KZ runtime

- Дата: 2026-08-20.
- Симптом: GitHub smoke и host watchdog считали production доступным при HTTP
  200 от исторического Render endpoint; ответ health не содержал deployment или
  release identity.
- Причина: доступность URL использовалась как эквивалент идентичности runtime,
  а канонический переход на `api.kml.kz` не был перенесён в monitoring contract.
- Исправление: health возвращает `app_environment`, `deployment_environment` и
  полный `release_sha` с `no-store`. KZ compose требует exact SHA; Render явно
  маркирован development. Общий verifier не следует redirects и сверяет KZ
  deployment/release; его используют GitHub smoke и системный watchdog.
- Проверка: monitoring TDD suite `6 passed`; Ruff и shell syntax прошли.
  Watchdog проверяет текущие Compose services и fail-closed требует источник
  свежести KZ backup. Production rollout и
  fault-injection на контролируемом staging остаются отдельным release gate.
- Профилактика: health monitor должен проверять identity и exact immutable
  release, а не только DNS/TLS/HTTP status. Dev/demo/rollback endpoints никогда
  не включать в production success path.

## SECURITY-006 — Limiter доверял неподписанному tenant и неполному public-route списку

- Дата: 2026-08-20.
- Симптом: non-public limiter выбирал tenant bucket из JWT payload без проверки
  подписи. Assignment-link, candidate, kiosk view и public lead не считались
  fail-closed public capabilities; invitation route отдельно доверял любому
  `X-Forwarded-For`.
- Причина: middleware пытался получить tenant до auth dependency и смешивал
  transport identity, неподтверждённый claim и route-specific protections.
  Runtime не требовал явный список trusted proxy.
- Исправление: principal bucket строится только после полной JWT
  signature/audience/issuer/expiry/type проверки и хранит opaque hash. Любой
  invalid/forged token остаётся в socket-IP bucket. Все public auth/capability
  routes fail closed при недоступном Valkey; URL tokens хешируются. KZ Compose
  требует exact `FORWARDED_ALLOW_IPS` для WireGuard proxy, а route-код больше не
  разбирает caller-controlled XFF. Redis member получил nonce, исключающий
  коллизии запросов с одинаковым timestamp.
- Проверка: forged JWT, spoofed XFF, verified access JWT, hashed capability,
  outage и exact-compose tests — `33 passed`; полный backend unit-suite
  `305 passed`; scoped Ruff прошёл.
- Профилактика: forwarded headers должны обрабатываться только ASGI server от
  allowlisted socket peer. До auth применяется network bucket, после проверки
  — opaque principal; новый public capability обязан попасть в fail-closed
  inventory и negative outage test.

## SECURITY-007 — Два package manager и уязвимые frontend runtime dependencies

- Дата: 2026-08-20.
- Симптом: LMS web одновременно содержал `package-lock.json` и
  `pnpm-lock.yaml`, CI/Vercel использовали npm, Dockerfile — pnpm и
  несуществующую monorepo-команду. Production SCA показывал high advisories в
  Next/PostCSS/nanoid; после основного обновления отдельно остался vulnerable
  transitive sharp.
- Причина: dependency contract расходился между локальной разработкой, CI,
  Vercel и container build; package manager/version не были закреплены.
- Исправление: web и landing закреплены на `pnpm 10.26.1`; web npm lock удалён;
  CI/Vercel требуют frozen pnpm lock. Web обновлён до Next `15.5.23`,
  PostCSS/nanoid/sharp закреплены на patched versions. Dockerfile использует
  app-local pnpm contract и production `next start`. Next 15 route params и
  ESLint fixture callback приведены к актуальному контракту.
- Проверка: frozen install проходит в обоих репозиториях; production audit —
  `0 high / 0 critical`; web `319 passed`, typecheck/lint/build (57 routes);
  landing `22 passed`, typecheck/lint/build (18 pages).
- Профилактика: один lockfile и exact packageManager на deployable app;
  `--frozen-lockfile` во всех release paths; SCA и production build блокируют
  release. Linux container build и production readback остаются release gate.

## SECURITY-008 — Ruff и mypy не блокировали CI

- Дата: 2026-08-20.
- Симптом: Ruff/format имели `continue-on-error`, mypy job — одновременно
  `continue-on-error` и `|| true`; mypy дополнительно останавливался на
  `config`/`app.core.config` duplicate module.
- Причина: большой накопленный долг пытались запускать как all-or-nothing gate,
  поэтому проверку сделали информационной и зелёный CI не означал отсутствие
  новых нарушений.
- Исправление: mypy получил `explicit_package_bases`; единый blocking script
  запускает Ruff и mypy и сравнивает per-file/per-code counts с committed upper
  bounds. Уменьшение долга разрешено, любое увеличение возвращает exit 1.
  Warn-only jobs и `|| true` удалены.
- Проверка: текущий gate PASS (`ruff=1140`, `mypy=2429`); contract tests
  `4 passed`; seeded дополнительный `F401` делает CLI gate красным.
- Профилактика: baseline не обновлять вверх без отдельного review и объяснения;
  постепенно снижать counts. Первый GitHub Actions run остаётся release gate.

## SECURITY-011 — PII и клиентский контент попадали в runtime logs

- Дата: 2026-08-20.
- Симптом: отдельные AI regeneration paths логировали первые 200 символов raw
  model output; ingestion/JD paths — filenames и document names; ряд внешних
  исключений логировался целиком. Debug API дополнительно копировал logger и
  stdout/stderr без redaction boundary.
- Причина: redaction полагался на дисциплину отдельных call sites; handlers,
  in-memory buffer и Sentry не имели единого контракта.
- Исправление: добавлен общий bounded redactor для свободного текста,
  structured extras, nested telemetry и tracebacks. Он установлен на root
  handlers, stdout/stderr tee, debug buffer и Sentry `before_send`. Опасные
  call sites теперь логируют только event/job/document IDs, counts/status и
  exception class, но не filenames, prompts, outputs или exception messages.
- Проверка: synthetic email/phone/JWT/Bearer/capability token/personnel/PIN/
  password и raw AI fragment tests — `7 passed`; связанный focused suite —
  `53 passed`; полный backend unit-suite — `312 passed`.
- Профилактика: новые content/provider boundaries логируют только opaque IDs,
  metrics и error type. Production aggregator/Sentry canary readback остаётся
  release gate и не должен использовать реальные персональные данные.

## SECURITY-013 — Backup не аутентифицировал ciphertext, а KZ restore не имел fail-closed команды

- Дата: 2026-08-20.
- Симптом: репозиторный backup использовал OpenSSL AES-256-CBC + PBKDF2 без
  authenticated-encryption contract. Offsite upload не скачивался обратно для
  сравнения и не требовал immutable retention. KZ runbook требовал отдельный
  restore, но версия команды отсутствовала; существующий `restore.sh` совмещал
  исторический Supabase portability path с возможностью production override.
- Причина: confidentiality ошибочно считалась достаточной проверкой целостности,
  а operational restore жил только в host-local знаниях. SHA sidecar, пустота
  target, schema/RLS/data gates, RPO/RTO и подписанное evidence не были связаны
  одним версионированным fail-closed workflow.
- Исправление: `scripts/backup.sh` использует authenticated GPG symmetric
  encryption, portable SHA-256 sidecar, обязательный decrypt/TOC validation и
  при MinIO — round-trip byte comparison плюс governance retention. Новый
  `scripts/kz-restore-drill.sh` принимает canonical archive, всегда блокирует
  production DB и непустую target, проверяет RPO/RTO, Alembic head, pgvector,
  FORCE RLS и агрегаты, затем подписывает JSON report отдельным GPG key.
  Исторический `.dump.enc`/Supabase restore оставлен отдельным legacy path.
- Проверка: Bash syntax и `scripts/tests/backup_restore_validation.sh` проходят;
  tampered GPG ciphertext отклоняется; Python source-contract suite — `4 passed`.
  Реальный KZ offsite upload и disposable PostgreSQL 17 + pgvector restore не
  выполнялись и остаются обязательным operational release gate.
- Профилактика: после каждого schema/release изменения выполнять свежий
  disposable drill и хранить подписанный report; quarterly проверять restore и
  immutable offsite retention. Production backup нельзя считать готовым по
  локальному тесту или наличию файла без decrypt/TOC и offsite readback.

## SECURITY-014 — DB security gate отличался от production major и частично работал как owner

- Дата: 2026-08-20.
- Симптом: GitHub Actions и локальный compose использовали pgvector/PostgreSQL
  16 при KZ production PostgreSQL 17. Часть cross-tenant API тестов работала в
  транзакции владельца миграций, а worker generation claim также не
  переключался на `lms_app`; зелёный результат не доказывал runtime FORCE RLS.
- Причина: полный backend suite одновременно выполнял unit, application-filter
  и DB tests, но не имел отдельного version/role/RLS environment contract.
  Production parity и факт `NOBYPASSRLS` подразумевались из migration source.
- Исправление: CI и compose переведены на `pgvector/pgvector:pg17`. Новый
  `scripts/ci/run_rls_release_gate.sh` fail closed разрешает только test-mode
  localhost ephemeral DB с typed confirmation. Gate отдельно проверяет server
  major, pgvector, Alembic head, runtime role attributes, FORCE RLS на критичных
  таблицах, cross-tenant CRUD/export/share/import, worker claim и superadmin
  isolation. Worker test явно выполняет claim после `SET LOCAL ROLE lms_app`.
- Проверка: source-contract unit suite `3 passed`, scoped Ruff, Bash syntax и
  CI YAML parsing прошли. DB-backed suite не запускался локально из-за
  отсутствующего Docker Desktop daemon; первый зелёный GitHub Actions run или
  отдельный ephemeral PostgreSQL 17 запуск остаётся release gate.
- Профилактика: production major version входит в blocking test contract;
  RLS-sensitive test обязан доказать effective runtime role, а не только наличие
  `tenant_id` predicate. Никогда не запускать destructive/fixture suite против
  production или удалённой shared DB.
