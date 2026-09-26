# Этап 2: матрица обязательного обучения и объяснимые назначения

Статус: 2.1 local implementation complete; DEV/runtime acceptance pending

## Цель

Дать методисту и руководителю одну серверную картину обязательного обучения:
кто, какой курс, по какому правилу, к какому сроку и в каком состоянии должен
пройти. Каждая строка должна отвечать на вопрос «почему назначено» и одинаково
трактоваться в дашборде, журнале и экспорте.

## Жёсткие границы

- Не создавать второй независимый механизм назначения.
- Не менять поведение `recompute_enrollments()` и приоритет
  `position > department > organization` без отдельной миграции продукта.
- Не вводить новые глобальные роли; использовать tenant/RLS и существующие
  capability-проверки журнала обучения.
- Не считать наличие `Enrollment` доказательством корректности правила:
  projection должен различать ожидаемое требование и фактическое назначение.
- Не терять ручные, программные, групповые и циклические назначения.
- Dashboard, журнал и CSV используют один read model, а не три набора SQL.

## Глубокий модуль

Новый read-only модуль `app.modules.mandatory_training` владеет двумя контрактами:

1. `resolve_effective_requirements(user)` — ожидаемые обязательные курсы из
   правил должности, всех предков подразделения и организации с тем же
   приоритетом, что у materializer.
2. `get_mandatory_training_matrix(...)` — сопоставляет ожидаемые требования с
   реальными enrollment-строками и возвращает один explainable read model.

`positions.assignment_service` вызывает тот же resolver для materialization.
Так правило определяется один раз, а write-path и read-path не расходятся.

## Контракт строки

- сотрудник, табельный номер, активность;
- путь подразделения и должность;
- курс и формат;
- `requirement_state`: `materialized`, `missing_enrollment`,
  `protected_assignment`, `stale_managed_enrollment`;
- `assignment_reason`:
  - `kind`: `position`, `department`, `organization`, `manual`, `cohort`,
    `learning_path`, `recurring`;
  - точный id источника, если он существует;
  - человекочитаемое название источника;
  - путь/контекст правила;
  - короткий локализуемый reason code, без готового UI-текста в БД;
- enrollment-поля, достаточные для сверки требования и назначения;
- `action_required`: `none`, `materialize`, `review_stale`.

Прогресс, deadline, certificate и evidence остаются каноническими полями
training log. Их включение в саму матрицу относится к срезу 2.2: нельзя
копировать расчёт или создавать второй тяжёлый SQL-контур только ради нового UI.

## Вертикальный срез 2.1

1. Красные unit/service tests на приоритет правил, ancestor department rule,
   отсутствующий enrollment, protected manual enrollment и tenant isolation.
2. Вынести структурированный resolver без изменения результатов существующего
   `recompute_enrollments()`; прогнать его текущую regression-suite.
3. Добавить API schemas, repository/service и
   `GET /v1/admin/mandatory-training` плюс summary.
4. Обогатить `TrainingLogRow` тем же `assignment_reason`, не меняя старое поле
   `enrollment_source`.
5. Добавить CSV-поля причины и состояния требования.
6. Добавить frontend-страницу/режим матрицы и раскрываемое «Почему назначено»;
   desktop/mobile, RU/KK/EN, loading/empty/error.
7. Перевести dashboard action counters на summary этого read model; журнал и
   экспорт должны ссылаться на те же reason/state.

## Приёмка

- Один и тот же сотрудник/курс имеет одинаковые source, reason и requirement
  state в API matrix, training log и CSV; dashboard считает действия из того
  же summary.
- Правило на родительском подразделении объясняется точным путём предка.
- Если materializer не создал enrollment, строка всё равно видна как
  `missing_enrollment`; это не маскируется нулём в дашборде.
- Ручное назначение не удаляется и отображается как protected assignment.
- Чужой tenant не появляется ни в строках, ни в summary, ни в CSV.
- Существующие assignment, learning-actions, training-log и evidence tests
  остаются зелёными.
- DEV: API contract, tenant isolation, CSV, desktop/mobile browser journey.
- Production: только после отдельного exact-SHA релиза и синтетической приёмки;
  реальные tenant-данные не используются.

## Выполнено в вертикальном срезе 2.1

- Введены структурированные контракты `EffectiveRequirement`,
  `EnrollmentAssignment` и `MandatoryTrainingProjection`.
- Приоритет `position > department > organization` вынесен в общий
  `merge_effective_requirements()` и уже используется действующим
  materializer без изменения его write-поведения.
- Добавлены tenant-safe одиночный и пакетный resolvers для матрицы:
  он учитывает опубликованные курсы, authoritative placement сотрудника,
  legacy fallback должности и root-to-leaf ancestor path.
- Проекция различает отсутствующее назначение, защищённое ручное/программное
  назначение и устаревшее управляемое назначение; неоднозначные дубли не
  маскируются.
- Добавлены tenant-scoped page/summary API, ограничение области в 1000
  сотрудников и безопасное пустое состояние для superadmin без tenant context.
- Добавлена страница матрицы: поиск, фильтры состояния и действия, честная
  серверная пагинация, desktop/mobile, RU/KK/EN, loading/empty/error и
  раскрываемое точное основание назначения.
- Training log JSON и CSV используют тот же enrichment и reason contract;
  ручное назначение, совпавшее с правилом, не получает чужой источник правила.
- Dashboard получает `missing_enrollment` и `stale_managed_enrollment` из
  summary и ведёт на соответствующий фильтр матрицы. Ошибка summary не
  подменяется нулевыми значениями.
- Полная локальная API regression-suite: `2880 passed, 500 skipped`.
- Полная локальная web regression-suite: `704 passed`; typecheck, ESLint и Ruff
  прошли без ошибок.

## Следующий целостный срез 2.2

1. Добавить к матрице progress/deadline/evidence только через переиспользование
   канонического training-log projection, без дублирования вычислений.
2. Ввести scoped responsibility для руководителя по org subtree/group и
   доказать отрицательные tenant/scope сценарии.
3. Пройти Supabase DEV/RLS API-контракт и человеческий browser journey, затем
   сверить matrix → dashboard → training log → CSV на одной синтетической паре
   сотрудник/курс.
4. Production допускается только отдельным exact-SHA релизом после DEV PASS.

## Наблюдение за расходом контекста

В срезе использованы три Graphify-навигационных запроса, одна проверка
целостности и одно AST-обновление индекса. Точный кросс-языковой HTTP-переход
Graphify не доказал: generic `api.get` расширяет граф, поэтому эта граница
подтверждена контрактными тестами и source-readback. Context Mode в доступном
контуре не вызывался. Точная экономия токенов не измеряется текущими
инструментами и не подменяется оценкой; основная работа шла по центральным seams
(`recompute_enrollments`, training-log read model, dashboard consumer), без
полного чтения репозитория.
