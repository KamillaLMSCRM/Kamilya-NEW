# Kamilya LMS: оптимизация OCR и перенос инфраструктуры в Казахстан

**Статус:** исследование и целевая схема, не разрешение на production-cutover.  
**Актуальность источников и замеров:** 06.08.2026.  
**Область:** обработка документов, OCR, PostgreSQL/pgvector, object storage и
сервисы текущего worker VPS.

## 1. Решение в одном абзаце

Текущую маршрутизацию Docling/MarkItDown/LibreOffice/Tesseract следует оставить
production baseline. AnyDoc или PaddleOCR рассматриваются только при появлении
измеримого bottleneck и внедряются лишь если benchmark показывает значительный
выигрыш без ухудшения казахского текста, структуры и эксплуатационной
надёжности. Firecrawl Cloud не использовать по умолчанию для клиентских
документов. Для коммерческого контура целевая схема — два узла у одного
казахстанского провайдера, отдельное S3-compatible хранилище и резервная копия:
узел данных с PostgreSQL/pgvector и узел приложения/worker/OCR. Полный Supabase
не нужен: приложение использует собственный JWT/RBAC, обычный PostgreSQL и уже
имеет интерфейс storage, в который необходимо добавить S3 backend.

## 2. Фактическая отправная точка

Read-only inventory production-контура на 06.08.2026:

| Объект | Фактическое состояние |
|---|---:|
| PostgreSQL | 17.6, около 39,1 MiB |
| tenants / users | 142 / 346 |
| documents / courses / lessons | 16 / 26 / 171 |
| embeddings | 775, `vector(4096)` |
| крупнейшая таблица | `document_embeddings`, около 16,5 MiB |
| Supabase Storage | 22 объекта, около 24,2 MiB |
| текущий VPS | 4 vCPU, 7,8 GiB RAM, без swap |
| свободная RAM во время замера | около 4,6 GiB |
| диск VPS | около 71,6 GiB, занято 60% |
| worker | три отдельных Celery worker; documents concurrency 1 |

Текущий объём данных очень мал: перенос ограничивается не размером, а
совместимостью RLS, pgvector, storage URLs, очередей, backup/PITR и контролем
данных. Реальный 21-страничный скан Sandyq распознавался около 4 минут 51 секунды,
поэтому latency сейчас определяется OCR, а не PostgreSQL.

Текущая маршрутизация:

- Office и PDF с текстом — MarkItDown;
- старый `.doc` — предварительная конвертация LibreOffice;
- скан или text-poor PDF — Docling + Tesseract `kaz,rus,eng`;
- ingestion — parse, chunk, embedding, запись в PostgreSQL/pgvector;
- исходники и артефакты — Supabase Storage.

## 3. Целевой pipeline документов

| Тип входа | Основной маршрут | Fallback | Причина |
|---|---|---|---|
| DOC/DOCX/XLS/XLSX/PPT/RTF/ODF | текущий MarkItDown/LibreOffice | Docling | baseline уже работает; AnyDoc только после доказанного выигрыша |
| digital PDF | текущий быстрый extractor | Docling без принудительного OCR | не тратить CPU на уже существующий text layer |
| скан PDF/изображение | Docling Standard + Tesseract `kaz+rus+eng` | очередь ручной проверки | Tesseract имеет официальный `kaz.traineddata` |
| таблицы и сложный layout | Docling; PaddleOCR PP-StructureV3 в shadow benchmark | ручная проверка | качество структуры важнее сырого текста |
| рукописный текст | не обещать автоматический результат | ручная обработка | текущий контур ориентирован на печатные документы |

### Почему AnyDoc — дополнение, а не OCR-замена

AnyDoc — MIT-проект на Rust, локально извлекающий текст из Office и PDF без
внешних сервисов. Он поддерживает в том числе старый `.doc`, поэтому теоретически
может убрать LibreOffice из частого пути. Однако сам проект прямо отделяет
локальный parser от OCR: сканированные страницы распознаются hosted-слоем
Firecrawl. Это кандидат на оптимизацию, а не обязательный компонент.

### Обязательный performance gate

Новый parser/OCR не добавляется в production, если на репрезентативном KZ/RU
корпусе не выполнено хотя бы одно условие:

- не менее чем двукратный рост throughput при не худшем качестве;
- не менее чем 35% снижение p95 времени при не худшем качестве;
- не менее чем 20% снижение CER/ошибок таблиц при времени не хуже baseline.

Дополнительно не допускаются регрессия казахских букв, рост доли ручной проверки,
новый внешний канал передачи документов или заметное усложнение эксплуатации.
Если gate не пройден, сохраняется текущая настройка.

### Что сравнить до изменения production routing

Собрать репрезентативный корпус 100–200 страниц:

- казахский, русский и смешанный текст;
- цифровые PDF, сканы 150/300 dpi, фото с наклоном;
- таблицы, печати, колонтитулы и нумерованные разделы;
- DOC/DOCX/XLSX и несколько старых `.doc`.

Для каждого движка фиксировать:

- CER/WER отдельно для казахского и русского;
- сохранность казахских букв и числовых значений;
- полноту таблиц, порядок чтения и заголовки;
- долю страниц, потребовавших ручной проверки;
- p50/p95 времени на страницу, peak RAM/CPU;
- итоговое качество chunking и grounded-ссылок курса.

Кандидаты:

| Кандидат | Решение |
|---|---|
| AnyDoc | не внедрять заранее; shadow benchmark только при наблюдаемом bottleneck |
| Docling | оставить оркестратором OCR/layout |
| Tesseract | оставить baseline для `kaz+rus+eng` |
| PaddleOCR PP-StructureV3 | не внедрять заранее; benchmark challenger только при проблемах таблиц/layout; поддержку казахского не считать подтверждённой без теста |
| Surya | исследовательский challenger; проверить лицензию и реальный KZ corpus |
| Firecrawl Cloud | только opt-in для несекретных материалов после проверки договора, резидентности и стоимости |

## 4. Казахстанские варианты размещения

Публичные цены — ориентир, окончательная смета требует коммерческого предложения,
фиксированной локации ЦОД, SLA, резервного копирования и налоговых условий.

| Провайдер | Что подтверждено публично | Вывод |
|---|---|---|
| PS Cloud / PS.kz | KZ дата-центры; VPS и помесячная цена CPU/RAM/NVMe; S3 тарификация | лучший вариант для прозрачной первичной сметы и запроса двух VM в одной private network |
| Hoster.kz | VPS 4 vCPU/8 GiB/200 GB — 23 040 ₸/мес.; 8 vCPU/16 GiB/400 GB — 65 280 ₸/мес.; тестовый период | бюджетный пилот, но отдельно проверить backup, private network, DDoS и SLA |
| Kazteleport | IaaS, Cloudian S3, BaaS/DRaaS, Managed Kubernetes и GPU Cloud в KZ | сильный enterprise-кандидат; стоимость и managed PostgreSQL/pgvector запрашивать письменно |
| QazCloud | IaaS, Cloud Storage, BaaS/DRaaS; площадки в Косшы, Павлодаре и Акколе | enterprise/RFP-кандидат; публичной достаточной цены и pgvector SLA нет |

Официальный тариф PS Cloud с 01.10.2025 указывает 5 440 ₸/месяц за vCPU,
1 450 ₸/месяц за GiB RAM и 142 ₸/GB-месяц NVMe. Поэтому ориентир для узла
PostgreSQL 4 vCPU / 8 GiB / 100 GB NVMe:

`4 × 5 440 + 8 × 1 450 + 100 × 142 = 47 560 ₸/месяц`

Это не итоговая цена: дополнительно потребуются public IP, трафик, backup,
мониторинг и, возможно, администрирование.

## 5. Варианты целевого контура

### Вариант A — недорогой pilot

- одна VM 8 vCPU / 16 GiB / 400 GB;
- API, worker, Valkey, converter и PostgreSQL/pgvector на одной машине;
- документы и backup — во внешнем KZ S3;
- публичный ориентир Hoster.kz: 65 280 ₸/месяц плюс storage/backup.

Подходит только для демонстрации или ограниченного pilot: OCR может конкурировать
с БД за RAM/CPU, а отказ VM останавливает весь продукт.

### Вариант B — рекомендуемый production minimum

Один провайдер и одна приватная сеть:

1. **Data node:** 4 vCPU, 8 GiB RAM, 100–200 GB NVMe — PostgreSQL 17,
   pgvector, PgBouncer, monitoring agent.
2. **App/compute node:** минимум 4 vCPU, 8 GiB RAM; при параллельном OCR лучше
   8 vCPU, 16 GiB — API, Celery workers, Valkey и текущий converter/OCR.
3. **KZ S3:** исходники согласно retention-классу, сертификаты, экспорт и
   зашифрованные backup.
4. **Backup:** pgBackRest/WAL archive с PITR, ежедневный full/incremental,
   неизменяемая off-site копия и регулярный restore drill.

По открытым тарифам нижний ориентир двухузлового варианта начинается примерно
от 70 600 ₸/месяц: расчётный PS data node 47 560 ₸ плюс Hoster 4/8/200
23 040 ₸. Смешивать провайдеров в production не рекомендуется: число приведено
только как ценовой floor. Нужен единый quote на две VM, private network, S3 и
backup у PS Cloud, Kazteleport, QazCloud и Hoster.kz.

### Вариант C — enterprise/HA

- два app/worker узла;
- primary + standby PostgreSQL в разных fault domains;
- managed load balancer, S3 с versioning, BaaS/DRaaS;
- отдельный GPU node только если benchmark докажет экономический эффект VLM/OCR.

Запрашивать у Kazteleport и QazCloud. Не принимать решение без демонстрации
PITR/restore, цифр RPO/RTO и подтверждения, где физически лежат primary,
реплики и backup.

## 6. Политика хранения исходников

Результаты обработки — извлечённый текст, chunks, embeddings, курс, тесты и
course release snapshot — действительно являются основной рабочей ценностью.
Однако удаление исходника сразу после OCR создаёт три практических риска:

- текущий reindex повторно читает source blob; без него нельзя сменить embedding
  model, исправить parser или восстановить повреждённый индекс;
- course release хранит SHA-256 и ссылки на документы, но hash без доступного
  оригинала не позволяет независимо проверить спорный фрагмент;
- OCR-ошибку или изменение версии документа нельзя доказательно сопоставить с
  тем, что пользователь фактически загрузил.

Поэтому исходники не должны храниться бессрочно по единому правилу, но и не
должны удаляться сразу. Рекомендуемая tiered retention:

| Класс | Что хранить | Срок |
|---|---|---|
| временный материал без provenance | оригинал до успешного OCR, QA и публикации; затем canonical text + chunks + hash | 7–30 дней, настраивается tenant |
| источник опубликованного курса/должностной инструкции | оригинал либо гарантированно доступная копия в DMS клиента + immutable hash | пока активна связанная версия курса, затем договорный grace period |
| документ с персональными данными/регулируемое доказательство | только в KZ storage, с legal hold и lifecycle | срок определяется целью, договором и применимым законодательством |

Извлечённый текст, chunks и embeddings тоже считаются персональными данными,
если по ним можно определить человека. Их локализация не менее важна, чем
локализация оригинала. Для текущего объёма стоимость originals почти нулевая;
основной аргумент за lifecycle — минимизация данных, а не экономия диска.

## 7. Render и Vercel: что можно обосновать

Сейчас frontend находится на Vercel, API — на Render, а БД/storage — в
Supabase. Правила защиты персональных данных РК указывают, что сбор и обработка
персональных данных ограниченного доступа осуществляются посредством объектов
информатизации, размещённых в Казахстане, а их электронная база должна
находиться в серверном помещении или ЦОД в Казахстане. Поэтому перенос одной
БД не создаёт достаточного обоснования для Render: API принимает и обрабатывает
email, кадровые данные, результаты обучения, токены и загружаемые файлы.

Фактическая архитектура frontend сейчас лучше:

- Next.js не содержит API route handlers и не проксирует FastAPI;
- рабочие страницы получают данные client-side напрямую по
  `NEXT_PUBLIC_API_URL`;
- Vercel analytics/Sentry/PostHog в frontend не подключены;
- Vercel middleware не выполняет auth и в основном пропускает запросы.

Следовательно, контент API и документов можно не передавать Vercel. Но Vercel
всё равно видит IP, URL и edge-метаданные, а URL проекта сейчас могут содержать
invitation/kiosk tokens и номера сертификатов. Поэтому есть два варианта:

1. **Предпочтительный:** перенести Next.js на тот же KZ app node. Это недорого и
   даёт самое простое доказательство единого KZ-контура.
2. **Условно допустимый:** оставить Vercel только как статический delivery,
   удалить middleware/SSR/server actions/telemetry, направить браузер напрямую
   в KZ API и перенести чувствительные идентификаторы из query/path в URL
   fragment или иной канал, который не отправляется Vercel. Затем закрепить
   это data-flow diagram, настройками логов, договором/DPA и юридическим
   заключением.

Для коммерческого tenant с персональными данными необходимо:

- перенести FastAPI/API на KZ app node; Render оставить только для dev/demo без
  реальных персональных данных;
- отдельно принять и документировать решение по Vercel;
- проверить внешние AI, email и observability providers: какие данные им
  передаются, где обрабатываются и как редактируются PII;
- провести юридическую проверку трансграничной передачи по применимому праву
  Казахстана. Локальное размещение само по себе не является полной гарантией
  compliance.

Та же проверка требуется для внешних LLM, email, Telegram и observability:
перенос Render не делает внешний AI-вызов локальным. В prompt нельзя отправлять
персональные данные без отдельного правового основания, минимизации и
согласованной трансграничной передачи.

Это инженерная оценка требований, а не юридическое заключение. До договора с
клиентом data-flow и классификацию данных должен подтвердить профильный юрист в
Казахстане.

## 8. Что потребуется изменить в Kamilya

1. Добавить `S3StorageBackend` в `app.core.storage` с тем же интерфейсом
   `put/get/exists/delete/get_url`; текущая реализация содержит только local и
   Supabase backends.
2. Обновить ADR-0009 после выбора KZ S3 и добавить интеграционные тесты signed
   URL, missing object, versioning и retry.
3. Сохранить `vector(4096)` либо выполнить отдельную контролируемую миграцию
   embedding model и полную переиндексацию.
4. Развернуть обычный PostgreSQL 17 + pgvector; приложение не зависит от
   Supabase Auth — JWT, refresh и active-role реализованы внутри Kamilya.
5. Использовать существующий portable restore, который исключает
   `supabase_vault` и создаёт роль `lms_app`; после restore отдельно задать
   runtime LOGIN/password и проверить FORCE RLS.
6. Перенести Celery queues, watchdog, converter и backup units с текущего VPS
   через декларативный deployment, не копированием секретов в образ.
7. Завести метрики OCR latency/error/manual-review, DB pool, queue depth,
   storage errors, backup age и restore success.

## 9. План миграции без необратимого cutover

### Этап 0 — договор и приёмка инфраструктуры

- получить 4 одинаковых коммерческих предложения;
- подтвердить KZ location primary/replica/backup, SLA, RPO/RTO, DDoS, private
  network, egress, поддержку и порядок возврата данных;
- запустить 7-дневный trial и измерить сеть KZ API ↔ DB ↔ storage.

### Этап 1 — landing zone

- развернуть VM, firewall, WireGuard/bastion, TLS, monitoring и secret store;
- PostgreSQL 17 + pgvector + `lms_app`, PgBouncer;
- S3 bucket с versioning/lifecycle и отдельный backup bucket.

### Этап 2 — shadow restore и storage copy

- восстановить актуальный зашифрованный dump через `--portable-supabase`;
- скопировать объекты с manifest: key, bytes, SHA-256, content type;
- сравнить counts, hashes, Alembic head, extensions, functions, triggers, RLS
  и `vector(4096)`;
- провести tenant-isolation, course generation, certificate и download smoke.

### Этап 3 — приложение и worker

- внедрить S3 backend и поднять KZ API/worker на shadow endpoints;
- прогнать оба Sandyq-документа и записать benchmark рядом с текущим;
- провести нагрузку: digital docs отдельно, OCR отдельно, DB во время OCR.

### Этап 4 — cutover

- объявить короткое окно read-only либо настроить проверенную логическую
  репликацию;
- выполнить final delta, повторить hash/count/RLS checks;
- переключить DNS/secret references, затем business smoke;
- Supabase и старый VPS оставить read-only как rollback на 30–90 дней.

### Этап 5 — завершение

- только после приёмки отключить старые writes;
- провести первый PITR restore drill и зафиксировать RPO/RTO;
- удалить старые данные по утверждённому акту, не по окончанию billing периода.

Rollback-триггеры: нарушение RLS, расхождение объектов/хэшей, ошибки выдачи
сертификата, очередь без прогресса, недоступный backup/restore или p95 выше
согласованного порога.

## 10. Вопросы провайдерам в одном RFP

1. В каких городах физически находятся VM, S3, replica и backup?
2. Есть ли private network без тарифицируемого public egress?
3. Поддерживаются ли PostgreSQL 17, custom extensions и pgvector?
4. Каковы гарантированные IOPS, CPU overcommit и лимиты burst?
5. Каковы SLA, RPO/RTO и компенсации; можно ли показать restore drill?
6. Есть ли immutable/versioned S3, lifecycle, KMS и audit log?
7. Какая защита DDoS/WAF и кто отвечает за OS/PostgreSQL patching?
8. Как выгружаются все данные и backup при расторжении договора?
9. Полная цена двух VM, 200 GB NVMe, 100 GB S3, backup, IP, трафика и 24×7
   поддержки с НДС?

## 11. Рекомендуемый ближайший порядок действий

1. Оставить текущий OCR/document routing; вернуться к AnyDoc/Paddle только при
   зафиксированном bottleneck и применить performance gate.
2. Утвердить три retention-класса originals и вариант DMS клиента.
3. Разослать единый RFP четырём KZ-провайдерам и запросить trial.
4. Включить KZ API в обязательный migration scope; для Vercel выбрать перенос
   либо документированный static-only профиль.
5. Выбирать не самый дешёвый VPS, а контур, успешно прошедший portable restore,
   tenant-isolation, storage hash и PITR drill.

## 12. Источники

- [Docling: выбор pipeline](https://docling-project.github.io/docling/examples/agent_skill/docling-document-intelligence/pipelines/)
- [Docling: GPU и batch-настройки](https://docling-project.github.io/docling/usage/gpu/)
- [AnyDoc: локальный parser и ограничения OCR](https://github.com/firecrawl/anydoc)
- [Firecrawl: document parsing и OCR modes](https://docs.firecrawl.dev/features/document-parsing)
- [PaddleOCR PP-StructureV3](https://paddlepaddle.github.io/PaddleOCR/v3.0.1/en/version3.x/algorithm/PP-StructureV3/PP-StructureV3.html)
- [PaddleOCR: официальный список языков PP-OCRv5](https://swhl.github.io/PaddleOCR/main/en/version3.x/algorithm/PP-OCRv5/PP-OCRv5_multi_languages.html)
- [Tesseract: `kaz.traineddata`](https://github.com/tesseract-ocr/tessdata/blob/main/kaz.traineddata)
- [Surya OCR/layout](https://github.com/VikParuchuri/surya)
- [pgvector](https://github.com/pgvector/pgvector)
- [PS Cloud: тарифы с 01.10.2025](https://www.ps.kz/news/new-tariff-2025)
- [PS.kz: дата-центры](https://www.ps.kz/en/about/data-center)
- [Hoster.kz: VPS](https://hoster.kz/cloud/vps/)
- [Kazteleport: облачные сервисы](https://kazteleport.kz/services/)
- [Kazteleport: S3](https://kazteleport.kz/services/oblachnye-servisy/s3-object-storage/)
- [Kazteleport: GPU Cloud](https://kazteleport.kz/services/oblachnye-servisy/gpu-cloud/)
- [QazCloud: облачные сервисы](https://www.qazcloud.kz/services/cloud)
- [QazCloud: география инфраструктуры](https://www.qazcloud.kz/about/mission)
- [Закон РК «О персональных данных и их защите»](https://adilet.zan.kz/eng/docs/Z1300000094)
- [Правила мер по защите персональных данных](https://adilet.zan.kz/rus/docs/V2300032810)
- [Закон РК «Об информатизации»](https://adilet.zan.kz/rus/docs/Z1500000418)

## 13. Использование Graphify

Graphify использован как индекс для выбора фактических компонентов:
`DocumentIngestion`, `VectorStore`, upload/operations документов и storage
boundary. Перед выводами были прочитаны реальные implementation, ADR по storage,
backup/restore runbook и production readiness. Граф не использовался как
единственный источник истины.
