# Mobile/Desktop QA execution

Дата: 2026-07-12
Окружение: production `https://app.kml.kz`
Коммит UI: `55db254`

## Проверено

| Сценарий | Desktop | Mobile 390x844 | Результат |
|---|---:|---:|---|
| Demo login -> dashboard | да | да | pass |
| Tenant context in top bar | да | да | pass |
| Sidebar navigation | да | да | pass |
| Mobile menu open/close | — | да | pass |
| Dashboard rendering | да | да | pass |
| Courses route | да | — | pass |

## Найденный и исправленный дефект

До `55db254` sidebar имел постоянную ширину 240px на всех viewport. На
390px основная область сжималась примерно до 178px, поэтому dashboard и
карточки курсов были практически непригодны для работы.

Исправление:

- sidebar закрыт по умолчанию на ширине меньше `md`;
- добавлена кнопка открытия меню в TopBar;
- добавлен затемняющий overlay;
- переход по пункту меню закрывает sidebar;
- основная область на мобильном получает `margin-left: 0`;
- добавлены локализованные labels `open/close` для ru/kk/en.

## Ограничения текущего прохода

- QA выполнен через production demo-сессию, без изменения рабочих tenant-данных.
- Реальные iSpring/Articulate SCORM-пакеты ещё требуют отдельного staging
  прохода.
- Полная матрица 13 flows x 3 viewport требует поднятого dev-stack или
  расширенного production smoke.

## Verification

- `npm run typecheck` — pass.
- Windows production build через `$env:NEXT_TELEMETRY_DISABLED=1; npx next build` — pass.
- Render API latest live commit: `68cda90`.
- Frontend latest pushed commit: `55db254`.
