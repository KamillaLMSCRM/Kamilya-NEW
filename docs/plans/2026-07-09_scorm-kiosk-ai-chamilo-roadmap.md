# SCORM, киоск, AI-ассистент и ориентир по Chamilo

Дата: 2026-07-09

## Решение по SCORM

SCORM нельзя корректно обещать как "все версии" одним пунктом. Для продукта нужно разделить стандарты:

- SCORM 1.2 - основной стандарт для загрузки готовых курсов. Поддерживаем в Kamilya.
- SCORM 2004 - вне текущего scope. Не импортируем, чтобы не создавать непроходимые курсы.
- AICC - старый стандарт, не берем в первый релиз.
- xAPI / Tin Can и cmi5 - не SCORM, а отдельная линия интеграции. Их нужно проектировать через LRS/событийное хранилище, а не как ZIP-импорт SCORM.

Ориентир: даже Chamilo в стабильной ветке 1.11 явно фокусируется на SCORM 1.2, а SCORM 2004 описывает как частичную/рискованную поддержку. Поэтому для Kamilya фиксируем SCORM 1.2 как продуктовый стандарт.

Источники:

- https://docs.chamilo.org/teacher-guide/teacher-guide/adding-content/learning-paths
- https://docs.chamilo.org/1.11.x-es/manual-del-profesor/estructura_rutas_de_aprendizaje/importar_aicc_y_scorm
- https://github.com/chamilo/chamilo-lms/blob/master/README.md

## Этап 1. SCORM 1.2: рабочий импорт и запуск

Цель: методист/админ загружает `.zip`, система создает курс, обучающийся открывает его как обычное назначение, прогресс и завершение попадают в Kamilya.

Статус на 2026-07-09:

- Сделано: backend-модель `scorm_packages` / `scorm_attempts`, миграция `0050`, API импорта ZIP, валидация `imsmanifest.xml`, безопасная проверка путей, сохранение ZIP в storage, создание курса `delivery_type=scorm`.
- Сделано: UI-вход "Импорт SCORM" на странице курсов, бейдж SCORM в карточке курса.
- Сделано: SCORM 1.2 launch-shell на backend-домене, чтобы SCO видел `window.API`.
- Сделано: asset proxy из ZIP через launch-token в path, чтобы относительные CSS/JS/картинки SCORM-пакета открывались без потери токена.
- Сделано: runtime bridge `window.API` (`LMSInitialize`, `LMSGetValue`, `LMSSetValue`, `LMSCommit`, `LMSFinish`, error helpers).
- Сделано: commit `cmi.core.*`, `cmi.suspend_data`, score/location/time/status.
- Сделано: при `cmi.core.lesson_status = completed|passed` закрывается enrollment и вызывается существующая выдача сертификата.
- Сделано: student dashboard для SCORM считает прогресс через enrollment: `enrolled=0%`, `completed=100%`.

Backend:

- `scorm_packages`: tenant, course, version, manifest title, entrypoint, storage prefix, manifest JSON, upload metadata.
- `scorm_attempts`: tenant, user, course, package, status, score, lesson_location, suspend_data, total_time, raw `cmi` JSON, timestamps.
- `POST /api/v1/scorm/packages/import`: загрузка ZIP, проверка размера, поиск `imsmanifest.xml`, защита от zip-slip, парсинг organizations/resources, создание курса `delivery_type=scorm`.
- `GET /api/v1/scorm/courses/{course_id}/launch`: выдача launch URL.
- `GET /api/v1/scorm/packages/{id}/launch`: HTML launcher с runtime bridge.
- `GET /api/v1/scorm/packages/{id}/assets-token/{token}/{path}`: безопасная отдача файлов пакета через storage/proxy.
- `POST /api/v1/scorm/attempts/{id}/commit`: сохранение `cmi.core.*`, score, status, suspend_data, total_time.

Frontend:

- В разделе "Курсы" добавить действие "Импорт SCORM".
- Отдельный экран импорта: ZIP, название, язык, статус публикации, привязка к должностям после импорта.
- Для обучающегося SCORM-курс открывается в iframe/fullscreen shell с индикатором сохранения.
- В списках курсов показать бейдж "SCORM 1.2".

Ограничения этапа:

- Только SCORM 1.2. SCORM 2004 отклоняется на импорте.
- Один organization по умолчанию; multi-SCO можно импортировать, но launch сначала ведет на default item.
- Сертификат выдавать по `completed/passed`, а если пакет не отдает статус - разрешить администратору вручную выбрать правило завершения: по посещению, по score, по кнопке "завершить".

## SCORM 2004

Не делаем в текущей версии. Если позже появится платный клиент с готовыми SCORM 2004 пакетами, проектировать отдельным эпиком: `window.API_1484_11`, completion/success statuses, sequencing и отдельная QA-матрица.

## Киоск

Функциональность уже есть:

- backend: `/api/v1/admin/kiosks`, `/api/v1/kiosks/{token}`;
- frontend: `/admin/kiosks`, `/kiosk/[token]`.

Проблема была в discoverability: раздел не был выведен в боковое меню и командную палитру. В текущем этапе добавлен пункт "Киоски" для `admin` и `org_admin`.

Статус на 2026-07-09:

- Сделано: пункт "Киоски" в sidebar и Cmd-K.
- Сделано: QR-код генерируется локально на странице `/admin/kiosks`.
- Сделано: печатная форма для размещения QR в цехе/на объекте.
- Сделано: backend-журнал `kiosk_access_logs`, миграция `0051`.
- Сделано: запись успешных и неуспешных идентификаций по табельному номеру.
- Сделано: админский endpoint `/api/v1/admin/kiosks/access-logs`.
- Сделано: таблица "Журнал киоска" на странице `/admin/kiosks`.

Следующие улучшения:

- Фильтр по локации и должности.
- Режим "без персональных данных на экране": после завершения сессии автоматически очищать состояние.
- Автоочистка kiosk-сессии на frontend после периода бездействия.
- Более подробный журнал: курс начал/завершил именно из kiosk-сессии.

## AI-ассистент при прохождении курса

Да, фича логичная, но ее нужно ограничить, чтобы ассистент не превращался в источник списывания тестов.

Статус на 2026-07-09:

- Сделано: отдельный learner endpoint `/api/v1/learner/assistant/chat`, не связанный с методологическим `/ai/chat`.
- Сделано: проверка доступа к курсу через enrollment или роль администратора/методиста.
- Сделано: контекст ограничен текущим курсом и текущим уроком.
- Сделано: system prompt запрещает выбирать ответы теста за обучающегося.
- Сделано: история user/assistant сообщений сохраняется в `learner_assistant_messages`, миграция `0052`.
- Сделано: frontend-панель "AI-ассистент по уроку" на странице прохождения native-курса.
- Не сделано: ассистент внутри SCORM iframe; это отдельный UX, потому что SCORM-пакет является внешним контентом внутри runtime shell.

MVP:

- Панель "AI-ассистент по уроку" внутри урока.
- Ответы только по материалам текущего курса/урока и документам тенанта, которые участвовали в генерации.
- Источники в ответе: название урока/документа, фрагмент.
- В режиме теста ассистент отключен или отвечает только подсказками без прямого ответа.
- Логи вопросов для методиста: где обучающиеся чаще всего не понимают материал.

Backend:

- `learner_assistant_sessions`, `learner_assistant_messages`.
- endpoint `POST /api/v1/learner/assistant/chat`.
- RAG по chunks курса/документов с tenant scope.
- Provider fallback: Qwen primary, DeepSeek fallback для chat; embeddings fallback нужно отдельное решение, потому что chat-модель не заменяет embedding-модель.

## Chamilo как ориентир для развития Kamilya

Chamilo - зрелая LMS общего назначения. Из него стоит взять не "все подряд", а только то, что усиливает Kamilya как HR/LMS для компаний:

Сильные функции Chamilo:

- learning paths с SCORM;
- quizzes с большим набором типов вопросов;
- assignments/homework;
- forums, announcements, surveys;
- gradebook, certificates, badges;
- attendance, rooms/branches, sessions/classes/groups;
- skills/competencies;
- analytics по прогрессу, времени, среднему баллу;
- plugins/integrations, LTI/xAPI/cmi5/QTI;
- multi-language и кастомизация бренда.

Что добавить в Kamilya в ближайшие этапы:

1. SCORM 1.2 import/launch/tracking.
2. Киоск: QR, журнал, print-mode, auto-cleanup.
3. AI-ассистент обучающегося по уроку.
4. Улучшенный журнал обучения: попытки, время, источник входа, сертификат, прогресс по должности.
5. Skill matrix: должность -> обязательные компетенции -> курсы -> тесты -> сертификаты.
6. Announcements/уведомления по назначенным курсам.
7. Surveys/обратная связь после курса.
8. Cohorts/группы обучения для крупных тенантов.
9. Импорт/экспорт курсов: SCORM export позже, сначала только import.

## Приоритет запуска

Для первого платного тенанта:

1. Протестировать SCORM 1.2 на 2-3 реальных пакетах: iSpring, Articulate, Captivate или Chamilo/Moodle export.
2. Довести киоск до понятного рабочего сценария с QR и журналом.
3. Добавить AI-ассистента в уроки без доступа к прямым ответам теста.
4. После этого расширять Chamilo-like функции: surveys, announcements, skill matrix, cohorts.
