# Сравнение LMS-проектов из подборки с Kamilya LMS

**Дата аудита:** 2026-07-12  
**Объект сравнения:** текущий `Kamilya-NEW` и пять проектов из изображения.  
**Метод:** проверка доступности GitHub-репозиториев, README/метаданных доступных проектов и сверка с локальными кодом, ADR и product-документацией Kamilya.

## Итог для руководства

Ни один проект из списка не является готовой заменой Kamilya LMS.

- `AntonioErdeljac/next13-lms-platform` — наиболее близкий по названию и базовой LMS-механике, но это creator/course marketplace LMS: курсы, главы, видео, покупки и teacher mode. Он не решает корпоративную оргструктуру, tenant isolation, обучение по должности, kiosk и казахстанские сценарии.
- `freeCodeCamp/freeCodeCamp` — зрелая образовательная платформа с сильной моделью curriculum, практики, прогресса и certification, но это не multi-tenant корпоративная LMS.
- `safak/youtube/tree/quiz-app` — недоступная ветка; по имеющимся данным нельзя использовать её как подтверждённый источник архитектуры.
- `PacktPublishing/MERN-Stack-Course` и `mkkhedawat/student-management-system` — текущие URL недоступны, поэтому делать выводы о реализации и лицензии нельзя.

**Решение:** не переносить чужой код в Kamilya. Использовать проекты как reference material для отдельных UX-паттернов: авторинг курса, порядок модулей, прогресс, quiz interaction, certification и media delivery.

## Доступность и доказательность

| Проект | Текущий статус проверки | Что можно утверждать | Риск использования |
|---|---|---|---|
| [AntonioErdeljac/next13-lms-platform](https://github.com/AntonioErdeljac/next13-lms-platform) | GitHub URL/API сейчас возвращает 404 | Исторически описан как Next.js LMS с Clerk, Prisma, MySQL/PlanetScale, Stripe, Mux и UploadThing | Нельзя брать код или считать лицензию подтверждённой без архивной копии и LICENSE |
| [PacktPublishing/MERN-Stack-Course](https://github.com/PacktPublishing/MERN-Stack-Course) | GitHub URL/API сейчас возвращает 404 | По названию это учебный MERN-проект/материал Packt | Нельзя использовать код или контент без проверки права использования |
| [mkkhedawat/student-management-system](https://github.com/mkkhedawat/student-management-system) | GitHub URL/API сейчас возвращает 404 | Из изображения следует только название Student Portal System | Нельзя приписывать функции и лицензию без исходников |
| [safak/youtube/tree/quiz-app](https://github.com/safak/youtube/tree/quiz-app) | Репозиторий существует, ветка `quiz-app` недоступна | Можно подтвердить только существование `safak/youtube`; реализацию ветки quiz-app — нет | Нельзя использовать как технический reference без сохранённого checkout |
| [freeCodeCamp/freeCodeCamp](https://github.com/freeCodeCamp/freeCodeCamp) | Доступен, активно развивается | Большая TypeScript-платформа с curriculum, интерактивными заданиями, тестами и сертификатами | Software BSD-3-Clause; curriculum и учебные материалы имеют отдельные copyright-ограничения |

Публичная страница freeCodeCamp подтверждает интерактивные lessons, workshops, labs, reviews, quizzes, обязательные проекты и verified certifications; репозиторий указывает BSD-3-Clause для software и отдельные ограничения для curriculum. [README freeCodeCamp](https://github.com/freeCodeCamp/freeCodeCamp#readme)

## Позиционирование проектов

| Проект | Тип продукта | Основной пользователь | Ближайшая аналогия с Kamilya |
|---|---|---|---|
| Antonio LMS | LMS для продажи/создания видеокурсов | Автор курса, покупатель, teacher | Course builder, chapters, progress, media |
| Packt MERN Course | Учебный full-stack пример | Разработчик/студент курса | Технический шаблон, не продуктовый benchmark |
| Student Management System | Student information/portal CRUD | Администратор учебного заведения, студент | Пользователи, группы, учебные записи |
| Safak quiz-app | Небольшое quiz-приложение/учебный пример | Ученик | Взаимодействие с вопросами и результатом |
| freeCodeCamp | Масштабная community learning platform | Самостоятельный learner, contributor | Curriculum, practice, progress, certification |
| Kamilya LMS | AI-first corporate multi-tenant LMS | HR/admin, методолог, обучающийся | Org-aware learning delivery для компаний Казахстана |

## Сравнение функционала

### 1. Курсы и авторинг

| Функция | Antonio LMS | freeCodeCamp | Kamilya LMS | Вывод |
|---|---|---|---|---|
| Курс → модули/главы | Сильная базовая модель chapters и reorder | Curriculum tree и последовательные этапы | Есть course → modules → lessons | Kamilya нужно улучшить визуальный authoring и порядок модулей, но доменную модель менять не надо |
| Drag-and-drop порядок | Исторически заявлен | Структура curriculum централизована | Есть структура курса, UX требует polish | Заимствовать UX reorder, не чужой код |
| Rich content/media | Video, HLS/Mux, attachments | Интерактивные coding challenges | Markdown/HTML, документы, native lessons, SCORM 1.2 | Kamilya не нужно становиться видеоплатформой; нужны стабильные content blocks и media policy |
| Генерация из документов | Нет в описанной модели | Нет как основной сценарий | Ключевая функция через Qwen/DeepSeek fallback | Это собственное конкурентное преимущество Kamilya |
| Две языковые версии из одного источника | Не является ключевой функцией | Не корпоративный bilingual flow | Требование Kamilya: русский + казахский курс и тесты | Довести как отдельный versioned course-generation flow |

### 2. Learner experience

| Функция | Antonio LMS | freeCodeCamp | Kamilya LMS | Вывод |
|---|---|---|---|---|
| Student dashboard | Есть | Сильный learning/curriculum experience | Есть `/student`, `/my-courses`, `/my-quizzes` | Kamilya нужно улучшать приоритеты, empty states и next action |
| Progress | Completion глав | Progress по curriculum/challenges | Lesson progress, quiz gates, enrollment status | Нужен единый progress model: lesson, quiz, course и path |
| Практика | Глава/видео | Интерактивный code execution и проекты | Уроки, тесты, AI assistant | Для корпоративного обучения добавить кейсы, scenario questions и evidence, не code runner |
| Обязательная последовательность | Course chapters | Curriculum prerequisites | Завершение уроков и обязательных quiz | Заимствовать явный next-step UX и блокировки, а не общий consumer flow |
| Shared-device flow | Нет | Нет | Kiosk с табельным номером и idle timeout | Уникальная Kamilya-функция, её нужно тестировать на staging/mobile |

### 3. Проверка знаний и сертификаты

| Функция | Quiz-app reference | freeCodeCamp | Kamilya LMS | Вывод |
|---|---|---|---|---|
| Quiz | Ветка недоступна, подтверждения нет | Quizzes встроены в curriculum | Quiz constructor, attempts, score, deferral | Kamilya уже выше простого quiz-demo; улучшать discoverability и feedback |
| Практические задания | Не подтверждено | Проекты и code challenges | Нет полноценного evidence submission | P1/P2: добавить кейсы и подтверждение результата для корпоративных программ |
| Сертификат | Не подтверждено | Verified certification link | PDF certificate, number, verify, download | Кamilya сильнее типового quiz-app; нужен public verification UX и шаблоны без hardcoded текста |
| Отзыв сертификата | Не подтверждено | Есть policy-driven revocation concept | Требует отдельной проверки/доработки | Для compliance нужен audit trail статуса сертификата |

### 4. Администрирование и бизнес-модель

| Функция | Antonio LMS | Student system | Kamilya LMS | Вывод |
|---|---|---|---|---|
| Teacher/admin mode | Есть teacher mode | Обычно CRUD admin/student | Разделены superadmin, tenant admin, methodologist/teacher, student | RBAC Kamilya намного глубже, но требует выравнивания `teacher/methodologist` |
| Tenant isolation | Не является заявленной функцией | Обычно одна организация/инсталляция | Tenant model + PostgreSQL RLS | Это нельзя заменять копированием простого CRUD-проекта |
| Оргструктура | Не является ключевой функцией | Возможно группы/студенты | Department, position, staff import, course rules | Это главное отличие Kamilya и основа B2B value proposition |
| Назначение обучения | Покупка/доступ к курсу | Запись студента | Department/position/manual enrollment, quiz assignment | Kamilya подходит для HR-процессов, но надо довести invitation/status и аналитические срезы |
| Billing | Stripe purchase flow исторически заявлен | Не подтверждено | Trial limits есть, billing не завершён | Нельзя брать Stripe flow как готовую модель SaaS billing; нужен собственный tenant plan/usage ledger |

## Архитектурное сравнение

| Область | Reference projects | Kamilya LMS | Практический вывод |
|---|---|---|---|
| Frontend | В основном Next/React или учебные web-примеры | Next.js 14 + TypeScript + Tailwind | Kamilya уже на production-ориентированном стеке |
| Backend/data | Antonio: Clerk/Prisma/MySQL/PlanetScale; остальные недоступны или учебные | FastAPI + SQLAlchemy async + Alembic + PostgreSQL/pgvector | Не менять backend ради сходства; reference полезен только для UX/media ideas |
| Auth | Antonio: Clerk; freeCodeCamp — собственная большая ecosystem | Email OTP, Telegram, Resend, tenant registration, in-memory access + refresh cookie | Kamilya auth сложнее и требует contract tests, но лучше соответствует tenant onboarding |
| Storage/media | Antonio: UploadThing/Mux | Supabase Storage, SCORM package launch, AI documents | Довести lifecycle, quotas и observability; не добавлять Mux без подтверждённой бизнес-потребности |
| Search/learning graph | freeCodeCamp curriculum engine | PostgreSQL + pgvector, course/module/lesson | Нужна отдельная domain-модель learning paths/prerequisites |
| Deployment | Reference projects ориентированы на tutorial/cloud stack | Vercel + Render + Supabase + Redis/Celery/VPS | Kamilya уже имеет нужную infra форму для B2B MVP, но нужно нагрузочное тестирование и backup drills |

## Что стоит заимствовать

### P0/P1: без смены архитектуры

1. **Курс как визуальный конструктор.** Дерево модулей и уроков, reorder, быстрый preview, видимый статус draft/review/published.
2. **Следующее действие для learner.** На dashboard показывать один primary CTA: продолжить конкретный урок/quiz, а не только список курсов.
3. **Единая шкала прогресса.** Не смешивать completion lesson, quiz score и course completion; показывать их отдельными сигналами.
4. **Empty/error states.** При отсутствии назначений, сертификатов, приглашений или документов показывать причину и следующий шаг.
5. **Quiz feedback.** После ответа показывать объяснение, попытки, доступность повторного прохождения и связь с уроком.
6. **Сертификат как проверяемый объект.** Номер, дата, курс, организация, статус и public verification URL должны быть единым UX.

### P2: после первого стабильного tenant-flow

1. Learning paths: программа из курсов с prerequisites и итоговым прогрессом.
2. Evidence-based learning: кейс, файл/ответ обучающегося, проверка методологом.
3. Rich media policy: видео, вложения и лимиты, но без зависимости от Mux до появления подтверждённой потребности.
4. Публичная библиотека шаблонов корпоративных курсов с явными лицензиями.
5. Аналитика для HR: department/position/user/course completion, overdue только при появлении реального deadline поля.

## Что не стоит заимствовать

- Consumer marketplace и Stripe purchase flow из creator LMS: у Kamilya не покупатель курса, а tenant с корпоративной подпиской.
- Clerk/Prisma/PlanetScale как замену текущему auth/RLS: это создаст миграционный риск без решения продуктовой задачи.
- Простую таблицу студентов из student-management проекта: она не покрывает tenant isolation, роли, штатную структуру и learner/runtime enrollment.
- Quiz-app как доказательство production-grade тестового движка: недоступная ветка не позволяет подтвердить качество, а простого score-flow недостаточно для Kamilya.
- Учебные материалы freeCodeCamp: даже при BSD-лицензии software curriculum и тексты имеют отдельные ограничения.

## Приоритетный backlog для Kamilya по результатам сравнения

| Приоритет | Задача | Почему |
|---|---|---|
| P0 | Прогнать staging flow kiosk → course → quiz → completion → certificate → timeout | Это собственная критичная функция shared-device обучения |
| P0 | Закрыть RBAC contract `teacher/methodologist` | Сейчас документация и backend используют разные названия ролей |
| P1 | Довести learner dashboard до модели «продолжить обучение» | Это сильная сторона зрелых learning platforms и слабое место типичного CRUD UX |
| P1 | Learning path поверх существующих courses/enrollments | Даст корпоративным программам структуру без разрушения текущей модели |
| P1 | Единый certificate verification/public view | Подтверждение результата должно быть отдельным продуктовым объектом |
| P1 | Course authoring: blocks, preview, reorder, bilingual generation | Сочетает сильную идею Kamilya с лучшими UX-паттернами creator LMS |
| P2 | Evidence/case assignments | Повысит ценность обучения для HR и руководителя, а не только процент прохождения |
| P2 | Media pipeline hardening | Только после измерения объёма видео и стоимости хранения/транскодинга |

## Финальный вывод

Kamilya уже отличается от проектов из списка не количеством учебных экранов, а доменной глубиной: tenant SaaS, RLS, HR-оргструктура, должностные инструкции, AI-генерация, правила назначения, kiosk и сертификаты.

Главная опасность — начать копировать отдельные consumer-LMS экраны и потерять корпоративную логику. Правильная стратегия: сохранить Kamilya как backend/domain ядро, а из Antonio LMS и freeCodeCamp заимствовать только проверенные UX-идеи для авторинга, learning progression, практики и certification.
