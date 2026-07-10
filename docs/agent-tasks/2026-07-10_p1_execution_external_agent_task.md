# Задание внешнему агенту: реализация P1 Kamilya LMS

Дата: 2026-07-10  
Репозиторий: KamillaLMSCRM/Kamilya-NEW  
Тип работы: реализация P1-функционала с тестами и отчётом  
Владелец финального ревью: основной Codex/Askar

## 1. Рабочая папка и ветка

Ты работаешь на отдельном компьютере. Не используй пути из чужого checkout. Сначала найди свою локальную папку репозитория и проверь remote:

~~~powershell
git remote -v
git fetch origin
git checkout master
git pull --ff-only origin master
git checkout -b p1-execution-kiosk-ux
~~~

Не работай напрямую в master. В конце:

~~~powershell
git push -u origin p1-execution-kiosk-ux
~~~

Merge в master не выполнять. Не делать force-push.

Текущий baseline: актуальный origin/master на момент начала работы. После fetch обязательно зафиксируй commit hash в отчёте. Если рабочая ветка уже существует, обнови её от актуального origin/master только через rebase/новую ветку и сообщи об этом.

## 2. Контекст продукта

Kamilya LMS — HR-first multi-tenant LMS для компаний Казахстана.

Основной продуктовый поток:

~~~text
tenant registration
  -> первый администратор
  -> штатка / сотрудники / должности
  -> документы и должностные инструкции
  -> AI-курс
  -> тест
  -> назначение
  -> прохождение обучающимся
  -> сертификат
  -> training log / отчёт
~~~

P0 уже закрывает базовую авторизацию, tenant isolation, SCORM 1.2 foundation, сертификаты, kiosk foundation, training log foundation и superadmin foundation. Твоя задача — улучшить рабочие P1-флоу, а не переписывать архитектуру.

Перед кодом прочитай:

1. AGENTS.md;
2. docs/reports/2026-07-09_p1_product_qa_gap_inventory.md;
3. docs/plans/2026-07-09_p1_backlog_execution_plan.md;
4. docs/plans/2026-07-09_p0_p1_product_hardening_plan.md;
5. docs/plans/2026-07-09_scorm-kiosk-ai-chamilo-roadmap.md;
6. docs/LESSONS.md;
7. актуальный P0 report в docs/plans/2026-07-10_p0-fix-all.md.

Не считай старые отчёты источником истины без проверки текущего кода. Если документ противоречит коду, зафиксируй расхождение.

## 3. Главная цель

Реализовать P1 последовательно, начиная с наиболее рискованного пользовательского потока:

1. kiosk privacy и kiosk course player;
2. discoverability назначения тестов;
3. training log UX;
4. invitations UX;
5. certificate UX;
6. mobile/desktop QA и i18n cleanup.

Работа выполняется блоками. После каждого блока:

- код;
- тесты;
- короткий отчёт;
- отдельный commit;
- обновление общего P1 execution report.

Не объединяй все изменения в один большой коммит.

## 4. Жёсткие ограничения

Запрещено без отдельного согласования:

- менять JWT, refresh-cookie, email OTP, Telegram login или superadmin auth;
- менять tenant isolation, RLS policies или способ определения tenant_id;
- менять billing, trial limits и тарифную логику;
- делать миграции БД, если решение можно выполнить без миграции;
- удалять старые документы, lessons или пользовательские untracked files;
- менять production DB напрямую;
- читать, печатать или коммитить значения из .env;
- записывать в отчёт пароли, токены, API keys, DATABASE_URL, Redis URL или персональные production данные;
- утверждать, что live QA пройден, если ты реально его не выполнял.

Если для задачи действительно нужна миграция/auth/RLS/billing — остановись на design note и укажи точный blocker. Не имитируй готовность.

Разрешены:

- React/Next.js UI;
- безопасные API-изменения, необходимые для kiosk session;
- тесты;
- i18n;
- empty/loading/error states;
- небольшие backend query fixes без schema migration;
- документация и QA harness.

## 5. Milestone P1.1: kiosk auto-logout

### Проблема

Kiosk — общий компьютер. После идентификации одного сотрудника следующий сотрудник не должен увидеть его имя, курсы, прогресс или результаты.

### Реализовать

Проверь текущий контракт apps/web/src/app/kiosk/[token]/page.tsx и apps/api/app/modules/users/kiosk_router.py.

Нужно:

- idle timeout по умолчанию 5 минут;
- отслеживание mouse, touch, keydown, pointer и visibility/focus событий;
- countdown за 60 секунд до завершения;
- явный экран "Сеанс истёк";
- кнопка "Начать заново";
- очистка personnel number, результата identify, выбранного курса и локальных transient данных;
- после нового identify старые данные не должны оставаться в UI;
- при logout не удалять данные самого kiosk token;
- audit event, если существующий audit contract позволяет добавить его без миграции.

Не добавляй localStorage для access token или персональных данных.

### Acceptance criteria

- после 5 минут inactivity персональные данные исчезают;
- активность пользователя продлевает сессию;
- countdown виден и не перекрывает основной UI;
- refresh страницы не возвращает старого worker;
- новый worker видит только свой результат;
- desktop и mobile layout не ломаются.

### Tests

Добавить unit/component tests для:

- timer;
- activity reset;
- cleanup state;
- timeout rendering.

Добавить integration test backend, если меняется session contract.

## 6. Milestone P1.2: kiosk course player

### Проблема

После kiosk identify пользователь может попасть на обычный course route и быть перенаправлен на /login. На общем терминале это dead end.

### Предпочтительное решение

Сначала изучи существующие kiosk JWT/session helpers. Предпочтительно использовать короткоживущий kiosk session token, связанный с:

- kiosk token;
- tenant_id;
- user/personnel;
- course_id при необходимости;
- issued_at/expiry.

Не создавай полноценную долгую пользовательскую сессию. TTL — короткий, целевой диапазон 5–20 минут согласно текущему контракту kiosk.

Варианты реализации оцени в design note:

- kiosk-specific player route;
- query token на course player;
- short-lived kiosk JWT.

Выбери вариант, который не ломает обычный learner course flow.

### Acceptance criteria

~~~text
kiosk open
  -> personnel number
  -> employee identified
  -> course selected
  -> course player opens
  -> lessons/progress/quizzes save
  -> completion works
  -> no ordinary /login redirect
~~~

После истечения kiosk session:

- backend отклоняет запрос;
- frontend показывает понятное сообщение;
- данные прошлого worker очищаются.

### Tests

- token valid before expiry;
- token rejected after expiry;
- token cannot be used for another tenant;
- kiosk player does not change ordinary student login;
- Playwright/E2E smoke, если dev stack доступен.

## 7. Milestone P1.3: discoverability назначений тестов

Проверь routes:

- /quizzes;
- /admin/quizzes;
- /admin/quizzes/assign;
- /assignments.

Нужно определить canonical purpose каждого route. Не удаляй route, пока не доказано, что он дубликат.

Добавь в Sidebar явный пункт для методолога:

- понятный label на русском, английском и казахском;
- ссылка на /admin/quizzes/assign;
- правильные роли: methodologist, admin, org_admin при наличии права;
- не показывать пункт обучающемуся;
- иконка из существующей системы.

Добавь тест на видимость ссылки по ролям.

Acceptance criteria: методолог открывает назначение теста максимум за один переход из sidebar.

## 8. Milestone P1.4: training log UX

Проверь apps/web/src/app/admin/training-log/page.tsx и backend contract.

Добавь:

- понятный empty state для пустого результата;
- различие "нет данных вообще" и "нет данных по фильтру";
- кнопку "Сбросить фильтры";
- видимые активные filters;
- состояние loading;
- состояние API error с retry;
- сортировку "сначала проблемные" или эквивалентный понятный toggle;
- сохранение UI preference только если это не сохраняет персональные данные.

Не меняй вычисление progress/status без отдельного теста на backend semantics.

Acceptance criteria:

- HR понимает, почему таблица пустая;
- сброс фильтров реально возвращает список;
- completed/in_progress/assigned не смешиваются визуально;
- mobile table не выходит за viewport.

## 9. Milestone P1.5: invitations UX

Изучи существующий invitations API и accept-invite flow перед изменением frontend.

Нужно:

- явный CTA "Пригласить сотрудника" в методологическом/tenant-admin контексте;
- форма email, имя/фамилия при поддержке backend contract, роль;
- понятные состояния pending, accepted, expired, revoked, superseded;
- copy invite link;
- resend только через существующий backend API;
- защита от двойного submit;
- понятный success/error state;
- не показывать tenant admin функции обучающемуся;
- не отправлять email автоматически, если backend/Resend contract этого не поддерживает.

Если создаёшь /admin/invitations, он должен быть связан с существующим /admin/team и не дублировать данные без причины.

Acceptance criteria:

- администратор/методолог понимает, кого приглашает;
- ссылка копируется одним действием;
- повторное приглашение не создаёт визуальных дублей;
- accepted/expired status виден без ручного просмотра БД.

## 10. Milestone P1.6: certificates UX

Проверь текущую реализацию сертификатов прежде чем менять контракт.

Приоритет:

- preview шаблона сертификата в настройках;
- отображение expiration date;
- понятный verification state;
- QR verification только если backend endpoint уже поддерживает это;
- download button с loading/error state;
- mobile layout.

Не заявляй об электронной подписи или юридической значимости, если это не реализовано в backend.

## 11. i18n и дизайн

Поддерживаемые языки: ru, kk, en.

Нельзя оставлять новые hardcoded labels в JSX, если строка пользовательская. Добавляй ключи во все три locale-файла.

Проверяй:

- длинные казахские labels;
- отсутствие overflow в sidebar;
- кнопки с иконками из существующей библиотеки;
- loading/error/empty states;
- desktop 1440px;
- tablet 768px;
- mobile 390px.

Не делай крупный redesign. Сохраняй текущую визуальную систему Kamilya LMS.

## 12. Testing requirements

Минимально перед каждым commit:

~~~powershell
cd apps/api
python -m compileall -q app tests
python -m pytest -q tests/unit
cd ../web
npm run typecheck
npm run test
~~~

Если часть команд недоступна, запиши точную причину, не называй её passed.

Для UI изменений добавь Playwright test или component test. Для backend изменений добавь unit/integration test.

Проверяй:

- role visibility;
- tenant boundary;
- expired tokens;
- duplicate submit;
- empty/error/loading;
- language switch;
- mobile viewport.

## 13. Git commits

Рекомендуемая структура:

~~~text
feat(p1-kiosk): add inactivity timeout and cleanup
feat(p1-kiosk): allow short-lived kiosk course player session
feat(p1-navigation): expose quiz assignment route
feat(p1-training-log): improve filter empty states
feat(p1-invitations): add invitation status UX
feat(p1-certificates): add template preview and expiration state
test(p1): add regression coverage
docs(p1): update execution report
~~~

Каждый commit должен быть небольшим и проверяемым. Не смешивай unrelated cleanup.

## 14. Финальный отчёт

Создай в своей ветке:

docs/reports/2026-07-10_p1-execution-report.md

В отчёте укажи:

- baseline commit;
- список выполненных milestones;
- список изменённых файлов;
- API contract changes;
- migrations: yes/no;
- auth/RLS changes: yes/no;
- tests and exact commands;
- manual QA matrix;
- screenshots или ссылки на Playwright artifacts, если есть;
- known limitations;
- что осталось следующему агенту;
- список commits;
- branch name и push status.

Формат каждой задачи:

~~~text
Task
Current problem
Implemented behavior
Files changed
Tests
Acceptance result
Known limitation
~~~

Финальная сводка не должна содержать credentials, production tokens, email/password или connection strings.

## 15. Условие готовности

Ветка готова к ревью, если:

- нет незакоммиченных изменений, кроме явно перечисленных;
- все commits pushed в отдельную ветку;
- backend/frontend проверки честно отражены;
- P1 flow можно пройти из UI;
- tenant boundary не ослаблен;
- learner не видит admin/methodologist actions;
- mobile layout проверен минимум на 390px;
- report создан и соответствует фактическому коду;
- merge в master не выполнялся.

