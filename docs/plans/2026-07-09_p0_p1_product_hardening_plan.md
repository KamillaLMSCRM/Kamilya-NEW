# План P0/P1 по итогам сравнения Chamilo 2.0 и Kamilya LMS

Дата: 2026-07-09

Основа: `docs/analysis/2026-07-09_chamilo2_vs_kamilya_lms_feature_comparison.html`.

Цель плана: довести Kamilya LMS до состояния, в котором первый платный tenant может начать работу без ручного DB-сопровождения и без “кривых” ключевых flow.

## Принцип приоритизации

P0 - то, что прямо блокирует запуск первого платного tenant или ломает доверие к продукту.

P1 - то, что не обязано быть в первом дне запуска, но быстро повышает ценность продукта, удержание и управляемость обучения.

Не включаем в P0/P1: форумы, wiki, CMS, e-commerce, plugin system, live classes, SCORM 2004, xAPI/cmi5/LTI. Это функционал зрелой универсальной LMS, но не блокер HR-first запуска Kamilya.

---

# P0. Запуск первого платного tenant

## P0.1. SCORM 1.2 end-to-end QA

**Зачем:** SCORM уже добавлен как фича, но до обещания клиенту нужно проверить реальные пакеты. Самописный runtime может ломаться на пакетах iSpring/Articulate/Captivate из-за относительных путей, popup/navigation, нестандартных `LMSSetValue`.

**Scope:**

- Собрать 2-3 реальных SCORM 1.2 пакета: iSpring, Articulate, Captivate или Moodle/Chamilo export.
- Проверить импорт ZIP.
- Проверить открытие iframe shell.
- Проверить загрузку CSS/JS/assets.
- Проверить `LMSInitialize`, `LMSSetValue`, `LMSCommit`, `LMSFinish`.
- Проверить completion при `cmi.core.lesson_status = completed|passed`.
- Проверить certificate issue после completion.
- Проверить learner dashboard: 0% до завершения, 100% после завершения.

**DoD:**

- Есть тестовый tenant с минимум двумя импортированными SCORM 1.2 курсами.
- Обучающийся проходит курс, enrollment становится `completed`, сертификат появляется.
- Ошибки runtime логируются понятно.
- SCORM 2004 пакет отклоняется понятной ошибкой.

**Риск:** высокий. SCORM-пакеты часто ведут себя нестандартно.

---

## P0.2. Единый журнал обучения

**Зачем:** для первого клиента админ/HR должен видеть, кто обучен, кто не обучен, кто получил сертификат. Сейчас данные есть в разных местах: enrollments, quiz attempts, certificates, progress, kiosk logs.

**Scope:**

- Backend endpoint `/api/v1/admin/training-log`.
- Фильтры: курс, должность, отдел, статус, дата, источник назначения.
- Поля: сотрудник, табельный номер, должность, отдел, курс, тип курса (`native/scorm`), статус, прогресс, лучший балл, попытки, дата завершения, сертификат, источник входа/kiosk.
- Export CSV/XLSX.
- Frontend page в admin/staff или отдельный `/admin/training-log`.

**DoD:**

- HR за 30 секунд отвечает: кто не прошел обязательное обучение.
- Можно выгрузить отчет.
- SCORM и native courses отображаются в одном журнале.

**Риск:** средний. Нужно аккуратно объединить несколько таблиц без тяжелых N+1 запросов.

---

## P0.3. Staff import wizard 2.0

**Зачем:** штатка - основа Kamilya. Сейчас импорт уже лучше, но реальные Excel часто много-листовые, с разными заголовками и “грязными” строками.

**Scope:**

- Выбор листа Excel перед preview.
- Автоопределение подходящего листа.
- Экран сопоставления колонок: табельный, ФИО/имя/фамилия, отдел, должность, email, телефон, дата приема.
- Поддержка ФИО одной колонкой.
- Предпросмотр первых 20 строк.
- Сохранение mapping per tenant.
- Понятные ошибки: “не найдена колонка должности”, “пустые табельные”, “дубли”.

**DoD:**

- Пользователь может загрузить файл с несколькими листами без ручного переименования колонок.
- Ошибка импорта всегда говорит, что исправить.
- После commit сотрудники, departments, positions и enrollments создаются ожидаемо.

**Риск:** высокий по UX, средний по backend.

---

## P0.4. Superadmin / tenant lifecycle hardening

**Зачем:** если первый tenant нельзя создать/удалить/исправить без DB, запуск будет зависеть от разработчика.

**Scope:**

- Tenant create wizard: компания, slug, тариф/trial, лимиты, первый админ.
- Проверка duplicate slug/email до отправки.
- Rollback при частично успешном создании.
- Delete tenant: soft delete или guarded hard delete для тестовых tenant.
- Tenant detail: лимиты, админы, статус, trial end, usage.
- Invite first admin по email.

**DoD:**

- Суперадмин создает tenant через UI без 500/409 “после факта”.
- Ошибки показываются в форме, а не только в консоли.
- Тестовый tenant можно удалить из UI.
- Первый админ tenant может войти по email OTP/invite.

**Риск:** высокий. Здесь много связей: tenants, users, limits, invites, auth.

---

## P0.5. Mobile/desktop QA ключевых flow

**Зачем:** learner и kiosk должны работать на телефоне/планшете. Admin-heavy экраны могут быть desktop-first, но learner-flow обязан быть чистым.

**Scope:**

- Login/email OTP.
- Accept invite.
- My courses.
- Native course player.
- SCORM player.
- Quiz.
- Certificate view/download.
- Kiosk identify and course open.

**DoD:**

- Playwright smoke на desktop и mobile viewport.
- Нет горизонтального скролла в learner/kiosk.
- Кнопки не перекрываются.
- Logout с shared device не зависает.

**Риск:** средний. Основной риск - layout regressions.

---

## P0.6. Onboarding checklist для tenant admin

**Зачем:** после регистрации tenant не должен теряться. Ему нужно показать путь “как получить первый результат”.

**Scope:**

- Виджет в админке: “Подготовить компанию к обучению”.
- Шаги: заполнить профиль компании, импортировать штат, загрузить документы, сгенерировать курс, назначить курс, пригласить/открыть kiosk, проверить журнал.
- Статусы шагов из реальных данных.

**DoD:**

- Новый tenant понимает, что делать дальше.
- Trial limits видны рядом с действиями.

**Риск:** низкий/средний.

---

# P1. Усиление продукта после запуска

## P1.1. Surveys / feedback после курса

**Зачем:** методологу нужны данные, где курс непонятен. Это проще и полезнее форумов.

**Scope:**

- Мини-опрос после завершения курса: полезность, понятность, сложность, свободный комментарий.
- Отчет по курсу: средняя оценка, частые жалобы, список комментариев.
- Связка с learner AI questions: где часто спрашивали.

**DoD:**

- После completion learner видит короткий feedback.
- Методолог видит feedback summary по курсу.

**Риск:** низкий.

---

## P1.2. Announcements / reminders

**Зачем:** назначить курс мало; нужно напомнить сотруднику пройти обучение до срока.

**Scope:**

- Deadline на enrollment/rule.
- Reminder schedule: за 3 дня, в день дедлайна, после просрочки.
- Каналы: email сначала, WhatsApp/Telegram позже.
- Admin UI: список просрочек и ручная отправка напоминания.

**DoD:**

- HR видит просроченные обучения.
- Сотрудник получает email reminder.
- Лог отправки сохраняется.

**Риск:** средний из-за фоновых задач и каналов уведомлений.

---

## P1.3. Skill matrix вокруг должностей

**Зачем:** это правильный аналог Chamilo skills для Kamilya, но в HR-терминах.

**Scope:**

- Skill/competency entity.
- Связь: position -> skills -> courses/tests/certificates.
- Уровни: required / optional, basic / advanced.
- UI на странице должности.
- Отчет: покрытие компетенций по сотруднику/отделу.

**DoD:**

- HR видит, какие навыки требуются должности.
- Система показывает, какие курсы закрывают навык.
- После сертификата навык считается подтвержденным.

**Риск:** средний/высокий. Нужно не усложнить модель.

---

## P1.4. Certificate verification QR

**Зачем:** сертификат должен быть проверяемым без входа в систему.

**Scope:**

- Public verification page.
- QR/link на PDF.
- Проверка: номер, ФИО, курс, tenant, дата выдачи, срок действия, статус.
- Настройка в certificate template.

**DoD:**

- На PDF есть QR.
- По QR открывается публичная страница проверки.
- Истекший/отозванный сертификат отображается корректно.

**Риск:** средний. Важно не раскрывать лишние персональные данные.

---

## P1.5. 2FA для superadmin и tenant admin

**Зачем:** админские аккаунты управляют персональными данными и tenant lifecycle.

**Scope:**

- TOTP для superadmin/admin/org_admin.
- Recovery codes.
- UI настройки 2FA.
- Enforce policy для superadmin.

**DoD:**

- Superadmin не может работать без 2FA.
- Tenant admin может включить 2FA.
- Recovery flow документирован.

**Риск:** средний. Ошибка в auth может заблокировать админов.

---

## P1.6. CRM/HR integration API

**Зачем:** если CRM пользователя будет источником клиентов/тенантов/сотрудников, нужен стабильный контракт.

**Scope:**

- API/webhook для создания tenant lead.
- API для staff sync.
- API для статуса обучения/сертификатов обратно в CRM.
- HMAC подпись webhook.
- Документация контракта.

**DoD:**

- CRM может создать заявку tenant и получить статус onboarding.
- CRM может получить training status по сотруднику/курсу.

**Риск:** средний.

---

# Рекомендуемая последовательность работ

1. P0.1 SCORM 1.2 QA.
2. P0.4 Superadmin / tenant lifecycle.
3. P0.2 Единый журнал обучения.
4. P0.3 Staff import wizard 2.0.
5. P0.5 Mobile/desktop QA.
6. P0.6 Onboarding checklist.
7. P1.4 Certificate verification QR.
8. P1.1 Surveys / feedback.
9. P1.2 Announcements / reminders.
10. P1.3 Skill matrix.
11. P1.5 2FA.
12. P1.6 CRM/HR integration API.

## Почему такой порядок

Сначала закрываем то, что ломает запуск и доверие: SCORM, tenant lifecycle, журнал обучения, импорт штатки. Затем улучшаем управляемость и доказуемость обучения: QA, checklist, verification QR. После этого добавляем продуктовые усилители: feedback, reminders, skills, 2FA, интеграции.

