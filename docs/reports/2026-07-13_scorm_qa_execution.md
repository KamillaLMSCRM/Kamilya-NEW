# SCORM 1.2 QA execution

Дата: 2026-07-13

## Итог

Локальный контур SCORM 1.2 проверен. Запуск и импорт реальных iSpring/Articulate-пакетов на staging пока не подтвержден: таких пакетов нет в рабочем checkout.

## Что проверено

Команда:

```text
python -m pytest apps/api/tests/unit/test_scorm_parse.py apps/api/tests/unit/test_scorm_security.py -q
```

Результат: **17 passed**.

Покрыты:

- SCORM 1.2 с явной и отсутствующей `schemaversion`;
- обнаружение SCORM 2004 по версии и по namespace `adlcp_v1p3`;
- entrypoint с query string и hash fragment;
- вложенные пути и отсутствие entrypoint в ZIP;
- path traversal, абсолютные пути и небезопасные имена;
- XSS в названии курса;
- лимит файлов и работа с архивом.

В `docs/test-assets/scorm/` есть шесть воспроизводимых фикстур: `minimal.zip`, `with_assets.zip`, `query_entrypoint.zip`, `hash_entrypoint.zip`, `scorm_2004_namespace_only.zip`, `malicious_title.zip`.

## Результат по сценариям

| Сценарий | Статус | Примечание |
|---|---:|---|
| Минимальный SCORM 1.2 | PASS | Manifest и launch resource распознаются |
| Ресурсы CSS/JS/изображения/подкаталог | PASS | Покрыто parser/security-тестами |
| iSpring-style `?loadcss=1` | PASS | Query сохраняется, проверка файла нормализуется |
| Hash в entrypoint | PASS | Hash учитывается при проверке архива |
| SCORM 2004 | PASS | Корректно отклоняется как неподдерживаемый |
| Небезопасный путь | PASS | Отклоняется до выдачи asset |
| XSS в title | PASS | Заголовок экранируется |
| Импорт -> launch -> LMSCommit -> сертификат | НЕ подтвержден | Нужен staging E2E с архивом и учеником |
| iSpring / Articulate / Captivate / Chamilo export | НЕ подтвержден | Нужны реальные экспортированные ZIP |

## Что осталось сделать на staging

1. Импортировать `minimal.zip` и `with_assets.zip` через UI.
2. Открыть курс от имени обучающегося и убедиться, что iframe загружает entrypoint и ассеты.
3. Нажать completion в SCORM-плеере и проверить `completed_at`, progress 100%, сертификат и журнал обучения.
4. Повторить тест с реальными экспортами iSpring Suite и Articulate Storyline SCORM 1.2.
5. Проверить повторное открытие завершенного курса, повторный `LMSCommit` и отсутствие дубликата сертификата.
6. Проверить отказ SCORM 2004 через UI: ошибка должна объяснять, что поддерживается только SCORM 1.2.

## Ограничение

Положительный результат unit-тестов доказывает корректность parser/security-контуров, но не заменяет проверку браузерного iframe, SCORM API bridge, storage и production database. До загрузки реального авторского пакета SCORM 1.2 считается готовым к контролируемому staging-пилоту, но не полностью закрытым для production claim.
