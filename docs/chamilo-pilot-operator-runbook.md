# Chamilo Pilot Operator Runbook

Date: 2026-07-06

This runbook describes the v0 manual Chamilo pilot flow. It intentionally avoids deep automation until 2-3 pilot tenants prove the process.

## Source Of Truth

For v0:

- Lead/commercial status: Kamilya/internal ops notes.
- LMS delivery: Chamilo.
- Generated content source: Kamilya course package.
- Progress/certificates for pilot: Chamilo.

Do not try to synchronize all data automatically in v0.

## Lead Intake

Required lead fields:

- Company name.
- Contact name.
- Email.
- Phone or Telegram.
- Employee count.
- Preferred language: `ru`, `kk`, `en`.
- Intent: `trial`, `demo`, `buy`.
- Training topic.
- Source materials status.

Lead statuses:

```text
new
contacted
qualified
waiting_for_materials
materials_received
portal_setup
course_generation
course_upload
handoff_ready
active_pilot
rejected
lost
```

## Tenant Setup Checklist

For each qualified tenant:

```text
[ ] Lead qualified
[ ] Materials received
[ ] Chamilo portal/access URL created
[ ] Tenant admin created
[ ] Teacher/methodologist created
[ ] Learner test user created
[ ] Real learner users imported or created
[ ] Course generated in Kamilya
[ ] Course reviewed by methodologist/operator
[ ] Course created in Chamilo
[ ] Learning path/modules created
[ ] Lessons uploaded/copied
[ ] Quiz created
[ ] Certificate/report settings checked
[ ] Learner smoke passed
[ ] Access email sent
[ ] Pilot support owner assigned
```

## Chamilo Portal Creation

Use Chamilo admin UI after installation.

Suggested portal URL format:

```text
https://<tenant-slug>.lms.kml.kz/
```

For v0, if wildcard DNS is not ready, use the main portal and keep tenant separation through Chamilo admin structures until multi-URL is confirmed.

Record:

- Chamilo portal URL.
- Tenant admin email.
- Chamilo course URL.
- Date created.
- Operator.
- Notes/blockers.

Never store passwords in this document.

## User Creation

Minimum users:

- 1 tenant admin.
- 1 teacher/methodologist.
- 1 learner test user.

For pilot learners, prefer CSV import if the tenant provides a list.

Required learner fields:

- First name.
- Last name.
- Email or login.
- Group/class/session if used.

## Course Package From Kamilya

The generator output should be operator-friendly:

```text
course-title.md
course-description.md
modules/
  01_module-title/
    lesson-01.md
    lesson-02.md
    quiz.json
  02_module-title/
    lesson-01.md
    quiz.json
assets/
operator-checklist.md
```

Manual upload target:

- Chamilo course.
- Learning path or course sections.
- Lessons/pages.
- Quiz.
- Certificate/report configuration.

Measure the time spent:

```text
course_generation_minutes:
course_review_minutes:
chamilo_upload_minutes:
smoke_test_minutes:
```

If `chamilo_upload_minutes > 30`, prioritize semi-automatic export/import before adding more pilot tenants.

## Learner Smoke

Before handoff, run:

```text
1. Login as learner.
2. Open assigned course.
3. Open each lesson.
4. Complete lesson path.
5. Pass quiz.
6. Confirm progress/report visible.
7. Confirm certificate/badge behavior if enabled.
```

Record:

- learner account used;
- course URL;
- result;
- issues found;
- time spent.

## Handoff Email Template

Subject:

```text
Ваш учебный портал Kamilya / Chamilo готов
```

Body:

```text
Здравствуйте, <name>.

Мы подготовили учебный портал для <company>.

Портал:
<portal_url>

Администратор:
<admin_email>

Что уже настроено:
- пользователи: <summary>
- курс: <course_title>
- тест/сертификат: <summary>

Первый шаг:
1. Войдите в портал.
2. Смените пароль.
3. Проверьте курс как администратор/преподаватель.
4. Отправьте доступ пилотной группе.

Если нужно добавить пользователей или поправить курс, напишите нам в этот чат/на эту почту.
```

Do not send passwords in plain text if avoidable. Prefer password reset or one-time setup flow.

## Pilot Metrics

For every pilot tenant, track:

- lead qualification time;
- tenant setup time;
- user setup/import time;
- course generation time;
- manual Chamilo upload time;
- number of upload errors;
- number of client support requests in first week;
- whether client used Chamilo features beyond course playback;
- whether client asked for Kamilya-specific AI/HR automation.

## Decision After 2-3 Tenants

Choose one:

1. Continue Chamilo route and automate import.
2. Use Chamilo only for enterprise/full-LMS clients.
3. Return LMS delivery to Kamilya core.
4. Hybrid: Kamilya for AI/onboarding, Chamilo for full LMS delivery.
