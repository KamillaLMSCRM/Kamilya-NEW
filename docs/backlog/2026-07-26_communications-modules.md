# Communications modules backlog

Date recorded: 2026-07-26
Product owner: Kamilya LMS
Status: hidden from navigation; implementation retained

## Why the modules are hidden

The existing `/surveys` and `/announcements` routes implement useful technical
building blocks, but neither module is complete enough to be presented as a
finished first-tenant workflow.

They remain protected registered routes. Database tables, API endpoints and
existing test coverage must not be removed while the product flow is being
redesigned.

## Post-course feedback

Current implementation:

- a methodologist creates a published rating question for one course;
- the learner sees it only after completing the course;
- one response per learner and survey is accepted.

Required before returning to navigation:

- response list and aggregate rating visible to the methodologist;
- response count, completion rate and rating distribution;
- optional free-text question and anonymous-response policy;
- filters by course, period, department and position;
- export with reader-facing column names;
- clear empty, insufficient-data and closed-survey states;
- course editor integration so feedback is configured in course settings;
- summary entry point under results/analytics rather than a disconnected
  content-menu item.

## Announcements and delivery

Current implementation:

- a methodologist creates a draft;
- recipients are all active tenant users or learners enrolled in one course;
- email is sent through the configured email service;
- aggregate sent/failed counters are stored.

Required before returning to navigation:

- rename the product surface to `Рассылки` or `Объявления`; reserve
  `Уведомления` for the in-app notification center and top-bar bell;
- recipient preview and explicit audience count before send;
- targeting by course, program, cohort, department, position and selected
  learners;
- scheduled delivery and cancellation before dispatch;
- asynchronous durable delivery with retry and per-recipient status;
- email template preview and sender identity;
- clear distinction between email, Telegram, WhatsApp and in-app channels;
- delivery history, failure reason and safe resend flow;
- tenant-admin channel configuration separated from methodologist messaging.

## Return-to-navigation gate

Both modules may return only after:

1. the complete manager and learner flows are covered by integration tests;
2. role ownership and navigation placement are approved;
3. desktop and mobile browser QA passes;
4. user documentation describes actual behavior without future claims.
