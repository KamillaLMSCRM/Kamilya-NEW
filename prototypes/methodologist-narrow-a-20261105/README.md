# Узкий A / подготовка C — локальный прототип

Открыть `index.html` отдельно в браузере. Все CSS/JS встроены; сервер, сеть,
установка пакетов и соседние файлы для просмотра не нужны. Все данные вымышлены.
Показаны только выбранные сценарии, а не полная карта LMS. «Задачи» обозначает
предлагаемое содержание существующего dashboard, не новый canonical route.

## Что попробовать

1. Генерация → открыть задание → причина остановки → курс.
2. Проверка → курс → согласование (только пояснение существующего входа).
3. Подготовка материалов → источник/урок/вопрос → current/missing/stale.
4. Просроченное назначение → срок/происхождение → контекст журнала.
5. Selector состояний: populated, filtered empty, empty, loading, unavailable,
   partial unavailable, error. Список не подменяет отсутствие данных нулями.

Никаких API, повторного запуска AI, публикации, apply, formal approval или
экспорта бизнес-данных нет. Маршрут к job иллюстративен и требует проверки A0.
Разделы, не входящие в прототип, явно обозначены как не реализованные.

## Проверка, 2026-11-05

- `node prototypes/methodologist-narrow-a-20261105/verify.mjs` — PASS:
  standalone resource ограничения, fixture markers, inline JavaScript syntax.
- `node prototypes/methodologist-narrow-a-20261105/browser-qa.cjs` — PASS
  (требуется браузер Playwright той revision, которую ожидает `apps/web`;
  при отсутствии — `npx playwright install chromium`):
  Chromium, локальный file URL, HTTP(S) blocked, 390/768/1270/1440 ×900;
  фильтрация, task destinations, contextual approval, source-state переключение,
  три варианта ответа, distinct states, readonly C, no stale action на partial,
  stacked detail/nav/empty-return focus, no page overflow, text-resize smoke.
- На каждом viewport: 0 попыток сетевых запросов, 0 page errors.
- Скриншоты: `evidence/tasks-{390,768,1270,1440}.png` и
  `evidence/sources-{390,768,1270,1440}.png`; root визуально просмотрел desktop
  queue и mobile C. Это evidence прототипа, не реального приложения.
- Независимые коллеги: critic и designer; устранены overclaim приоритетов и
  эффектов, общие destinations, неполные options, неполная source quote,
  зелёное оформление неподтверждённого ответа, focus/state ambiguities.

Пределы: только RU/light, desktop Chromium с эмуляцией viewport; настоящий
телефон, screen reader, полная keyboard-only приёмка, axe, RU/KK/EN и dark
для рабочего приложения ещё не проверены. Text-resize smoke не равен полному
browser-zoom/WCAG audit. Backend/auth/RLS, live flags и качество AI не проверялись.

Приложение, production и feature flags не менялись. Commit/push/deploy не выполнялись.
Принятый scope и следующие gates: `docs/product/contract-modules/learning-workspace-visual/STAGE_1_NARROW_A.md`.
