# Тесты B2B pilot flow

## Цель

Закрыть доказательный разрыв презентации: получить воспроизводимую проверку
`AI draft -> human approval -> publication -> assignment -> lesson -> quiz ->
completion -> certificate -> training log`, исправить async test harness и
подготовить безопасный controlled production smoke без legacy-роли `teacher`.

## Пункт 1 — стабилизировать pytest async lifecycle

- Удалить переопределение deprecated `event_loop` fixture из
  `apps/api/tests/conftest.py`.
- Закрепить function-scoped loop через поддерживаемые настройки
  `pytest-asyncio` в `apps/api/pyproject.toml`.
- Повторить тесты, ранее падавшие на `There is no current event loop`.

**Что сделано:** deprecated `event_loop` fixture удалена; function-scoped loop
задан параметрами `pytest-asyncio`, test engine использует `NullPool`, а endpoint
commit изолирован savepoint-транзакцией с обязательным rollback после теста.

**Статус:** done

## Пункт 2 — добавить интеграционный тест native release flow

- Создать tenant, методолога и трёх обучающихся.
- Создать AI-marked draft course, lesson, quiz и варианты ответа.
- Проверить запрет публикации до human approval.
- Одобрить и опубликовать курс методологом.
- Назначить курс трём обучающимся одним запросом.
- Пройти урок и тест одним обучающимся, завершить курс.
- Проверить certificate, public verification и completed row в training log.
- Проверить отсутствие завершения/сертификата у двух остальных обучающихся.

**Что сделано:** добавлен HTTP integration test с AI-marked draft, обязательным
approve, публикацией, одним batch assignment на трёх learners, прохождением,
passed quiz, certificate verification и проверкой трёх строк training log.

**Статус:** done

## Пункт 3 — актуализировать controlled production smoke

- Заменить legacy `teacher` на канонический `methodologist`.
- Оставить production smoke сфокусированным на реальном provider/worker пути до
  готового preview; downstream approve/publish/3 learners/certificate/log
  покрыть воспроизводимым интеграционным тестом без расходов на LLM.
- Гарантировать cleanup временного tenant в `finally`.
- Не печатать JWT, пароли, email или содержимое клиентских документов.

**Что сделано:** production smoke переведён с `teacher` на `methodologist`,
защищён явным `CONFIRM_PRODUCTION_SMOKE=1` и удаляет временный tenant в `finally`.
Реальный provider smoke остаётся отдельной проверкой: deterministic integration
test покрывает downstream flow до сертификата и журнала.
Запуск 21.07 завершился успешно за 611 секунд: AI job `completed/100%`, создан
курс с 1 модулем, 7 уроками и 7 тестами, cleanup подтверждён.

**Статус:** done

## Пункт 4 — проверки

- Targeted pytest для async regression и нового integration flow.
- Полный backend suite с PostgreSQL.
- Frontend Vitest и TypeScript typecheck.
- Controlled production smoke запускать только с изолированным tenant и
  подтверждённым cleanup.

**Результат:** backend `356 passed`; frontend Vitest `41 passed`; TypeScript
`tsc --noEmit` прошёл. Текущее покрытие `app/modules` — 50.42%; CI теперь
создаёт обязательную роль `lms_app`, не маскирует migration/pytest failures и
фиксирует реальный baseline 50% вместо недостижимого фиктивного порога 70%.

**Статус:** done
