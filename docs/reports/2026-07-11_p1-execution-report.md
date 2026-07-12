# P1 execution report — kiosk, assignment discovery and operator UX

**Дата:** 2026-07-11
**Ветка:** `p1-implementation-2026-07-11`
**Область:** первая безопасная итерация P1 поверх актуального `master`.

## Выполнено

### 1. Kiosk privacy timeout

- Добавлен общий React-хук `apps/web/src/lib/useIdleTimeout.ts`.
- После идентификации киоск показывает предупреждение за 60 секунд до завершения.
- Через 5 минут бездействия очищаются ФИО, табельный номер и kiosk-сессия.
- События активности подключаются с очисткой listeners/timers при размонтировании.
- Предыдущая обычная in-memory-сессия браузера восстанавливается при ручной смене сотрудника.

### 2. Kiosk → course player

- Frontend теперь принимает `access_token`, который уже выдаёт backend `POST /v1/kiosks/{token}/identify`.
- Токен устанавливается через существующий in-memory auth API, без localStorage и без refresh-cookie.
- Навигация использует Next `Link`, поэтому переход в курс не превращается в обычный login redirect.
- В учебном проигрывателе действует тот же 5-минутный idle timeout; после истечения пользователь возвращается на kiosk URL.
- Backend JWT остаётся короткоживущим (20 минут, `auth_method=kiosk`), поэтому frontend timeout не является единственной границей безопасности.

### 3. Discoverability назначения тестов

- В sidebar добавлен маршрут `/admin/quizzes/assign` для `admin`, `org_admin`, `methodologist` и `teacher`.
- Название вынесено в `ru/en/kk`.

### 4. Training log UX

- Пустой журнал теперь различает отсутствие данных и пустой результат по фильтрам.
- Для активных фильтров показывается actionable-подсказка и кнопка сброса.
- Состояние фильтров и pagination сбрасывается единообразно.

### 5. Kiosk print sheet

- Печатные инструкции используют текущую локаль (`ru/en/kk`).
- Значения kiosk name/location/URL экранируются перед вставкой в HTML окна печати.

### 6. Invitation status and resend surface

- Добавлена страница `/admin/invitations`.
- Администратор тенанта может создать learner invite link, скопировать ссылку,
  увидеть статусы `pending/accepted/expired/revoked/superseded` и создать новую
  ссылку для pending-приглашения.
- Текст прямо сообщает, что текущий backend создаёт ссылку, но не отправляет
  письмо автоматически.
- Страница подключена в sidebar для `admin` и `org_admin`.

### 7. Certificate learner UX

- Пустое состояние `/certificates` теперь ведёт обучающегося к его курсам.
- Проверка сертификата не отправляет пустой запрос, поддерживает Enter и
  кодирует номер перед запросом.
- Форма проверки адаптирована для узких экранов.

## Проверки

- `apps/web`: `npm run typecheck` — passed.
- `apps/web`: production `next build` — passed (через PowerShell с
  `NEXT_TELEMETRY_DISABLED=1`, потому что npm-script использует Unix-синтаксис
  переменной окружения).
- `apps/web/tests/useIdleTimeout.test.tsx` — 2/2 passed.
- `apps/api/tests/test_kiosk_jwt.py apps/api/tests/test_admin_p0.py` — 9/9 passed.
- Все три locale-файла — валидный JSON.
- `git diff --check` — passed.
- Backend kiosk JWT tests уже присутствуют в `apps/api/tests/test_kiosk_jwt.py`; backend contract не менялся.

## Что не заявляется как выполненное

- Отдельного серверного session-revocation для kiosk inactivity нет: серверный JWT ограничивает верхний срок, а 5-минутный inactivity enforcement выполняется в браузере.
- Реальный Playwright smoke на production/staging и ручной SCORM QA требуют поднятого окружения и не подменяются typecheck.
- Полная локализация `/admin/page.tsx` и мобильная матрица P1 остаются следующими задачами.
- RBAC-выравнивание выполнено после этого отчёта: `teacher` и `methodologist`
  теперь взаимные alias-ы learning-content домена, а миграция `0055` разрешает
  `methodologist` в database role constraints. Admin/org_admin границы не менялись.

## Следующий шаг

1. Поднять staging/dev-stack и пройти Playwright flow: kiosk identify → native course → lesson progress → quiz → completion → timeout.
2. Проверить 401 после истечения backend kiosk JWT.
3. Отдельной итерацией завершить invitations status/resend и admin dashboard i18n.
