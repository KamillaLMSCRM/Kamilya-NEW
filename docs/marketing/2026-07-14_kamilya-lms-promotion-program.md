# Программа продвижения Kamilya LMS: первые 90 дней

**Рынок:** Казахстан · **период:** 14 июля — 11 октября 2026 · **версия:** 1.0
**Цель:** получить первых платящих B2B-тенантов и подтвердить воспроизводимый канал привлечения, не обещая непроверенные функции.
**Модель запуска:** founder-led, sales-assisted; один пилот одновременно, ручное сопровождение первых тенантов.
**Основание продуктовой правды:** checkout `b71ff3d` от 14.07.2026, код и production evidence в ссылках ниже. Это не прайс-лист и не юридическая консультация.

## 1. Решение и границы запуска

Первый продаваемый сценарий — **контролируемый пилот обучения 3–10 сотрудников**: представитель компании регистрирует trial по рабочему email, методолог берёт один внутренний документ, создаёт/дорабатывает курс и тест, назначает пилотной группе; обучающийся завершает курс, а HR видит запись в журнале и сертификат. Продажа после доказанной ценности ведётся вручную: demo, согласование объёма, счёт/активация владельцем продукта.

Не продаём как готовое коммерческое решение SCORM, kiosk, автоматические cohort/rule-сценарии, выделенного Telegram-бота, CRM-интеграцию, онлайн-оплату, юридическое соответствие или экономический эффект. Крупные тенанты, которым до пилота нужны SSO, HRIS/CRM, юридические гарантии, массовый SCORM или kiosk, попадают в discovery, а не в стандартный trial.

### 1.1. Режим доказательности

| Метка | Значение в этом документе |
|---|---|
| Подтверждённый факт | Зафиксирован в production evidence, коде либо внешнем первоисточнике. |
| Расчётная оценка | Прозрачная оценка для планирования; не является рыночным фактом. |
| Гипотеза | Должна быть проверена событием, сроком и stop/go-критерием. |

## 2. Аудит продуктовой правды

| Утверждение | Реализовано | Доказательство / файл / URL | Ограничение | Можно использовать в рекламе |
|---|---|---|---|---|
| Из документа можно создать AI-курс | Да, production smoke | [AI smoke 14.07](../reports/2026-07-14_ai-production-smoke.md); [AI module](../../apps/api/app/modules/ai/) | Основной Qwen недоступен; рабочий fallback — DeepSeek. Не обещать скорость, качество без проверки документа человеком. | Да: «помогает превратить внутренний документ в черновик курса»; с human-review. |
| Курсы, уроки и тесты | Да, native E2E | [First-tenant E2E](../reports/2026-07-14_first-tenant-e2e.md) | Подтверждён native flow, не все возможные сценарии автора. | Да, для native-курса/теста. |
| Назначение курса обучающемуся | Да, native E2E | [First-tenant E2E](../reports/2026-07-14_first-tenant-e2e.md) | Ролевой UX ещё требует staging E2E: у методолога есть известные navigation gaps. | Да: «назначить пилотной группе», при ручном сопровождении. |
| Cohorts / правила автоподбора | Частично реализовано | [Role UX audit](../reports/2026-07-13_role-based_ux-ui_audit.md); [Valkey smoke](../reports/2026-07-14_valkey-vps-migration.md) | Нужны E2E worker, идемпотентность и защита от дублей; не доказан коммерческий flow. | Нет как самостоятельный claim; только «изучаем в пилотах». |
| Сертификат и публичная проверка | Да, native E2E | [First-tenant E2E](../reports/2026-07-14_first-tenant-e2e.md) | Это продуктовый сертификат, не государственный документ и не доказательство compliance. | Да: «выдаёт сертификат по условиям курса и даёт публичную проверку». |
| Журнал обучения | Да, native E2E | [First-tenant E2E](../reports/2026-07-14_first-tenant-e2e.md); [training-log report](../reports/2026-07-09_p0_followup_report.md) | Для незавершённого SCORM нет granular progress; не является обязательным по закону журналом. | Да: «журнал прохождения обучения»; не «заменяет обязательный журнал». |
| Штатное расписание, отделы, должности | Реализовано, но не проверено как первый sales flow | [Role UX audit](../reports/2026-07-13_role-based_ux-ui_audit.md) | Ролевое разделение и import/assignment требуют staging проверки. | Не выносить в hero; только demo по запросу с оговоркой. |
| SCORM 1.2 import/launch | Частично: backend и fixtures проверены | [SCORM QA 13.07](../reports/2026-07-13_scorm_qa_execution.md) | Реальные iSpring/Articulate-пакеты, browser/storage/production E2E не пройдены; SCORM 2004 не поддерживается. | Нет до ручного staging QA. |
| Kiosk | Код есть | [Role UX audit](../reports/2026-07-13_role-based_ux-ui_audit.md) | Privacy/auto-logout и browser QA остаются P1. | Нет до ручной проверки. |
| Email login / OTP | Да, Resend в production | [tenant/trial flow](../product/tenant-registration-trial-flow.md), [Project context](../PROJECT-CONTEXT.md) | Deliverability нужно мониторить; не обещать 100% доставку. | Да: «вход по коду на email». |
| Telegram | Дополнительный login и tenant integration | [tenant/trial flow](../product/tenant-registration-trial-flow.md); [integrations router](../../apps/api/app/modules/integrations/router.py) | Не обязателен для первого коммерческого сценария; shared-bot onboarding не подтверждён как flow. | Только «Telegram — дополнительный канал»; не в основном CTA. |
| Trial: 14 дней, 1 AI-курс, 1 курс по ДИ, до 10 обучающихся и 3 системных пользователей | Да, предложение и ограничения | [tenant/trial flow](../product/tenant-registration-trial-flow.md); [trial enforcement](../reports/2026-07-14_trial-enforcement.md) | Превышение/окончание должно вести в support/upgrade, UI для этого ещё надо проверить. | Да, только с точными лимитами и датой актуальности. |
| Ограничение trial по дате | Да, unit-tested | [trial enforcement](../reports/2026-07-14_trial-enforcement.md) | Frontend должен показать отдельное состояние upgrade/support. | Не использовать как marketing claim; учитывать в onboarding. |
| Billing / автоматический upgrade | Нет, как self-service flow не подтверждён | [Project context](../PROJECT-CONTEXT.md) | Возможна только ручная продажа/активация до проверки текущего production flow. | Нет «оплатите онлайн»/«мгновенный upgrade». |
| CRM-интеграции | Не подтверждены | [Project context](../PROJECT-CONTEXT.md) | CRM worker указан как future в README лендинга. | Нет. |
| Соответствие законодательству, ЭЦП, гарантированный ROI | Нет доказательной базы | [external audit verification](../reports/2026-07-14_external-audit-verification.md) | Требуют правового и предметного подтверждения. | Нет. |

**Расхождение, которое нельзя скрывать.** Отчёт [external audit verification](../reports/2026-07-14_external-audit-verification.md) описывает более раннее состояние с недолговечным AI-dispatch и отсутствующим time-based trial enforcement. Коммиты и отчёты от 14 июля фиксируют Celery/Valkey smoke, AI smoke и исправленный enforcement. Для рекламы за источник правды приняты более новые production evidence; сам отчёт остаётся основанием не заявлять SCORM/kiosk и полную самостоятельность flow без ручного контроля.

## 3. Рынок и ICP

### 3.1. Внешние источники на 14.07.2026

| Источник | Подтверждённый факт | Зачем нужен решению | Ограничение |
|---|---|---|---|
| [Бюро национальной статистики РК: МСП на 01.10.2025](https://stat.gov.kz/ru/industries/businessstatistics/stat-org/publications/473784/) | 2,176 млн действующих субъектов МСП; 71,7% из них — ИП. | Подтверждает широкий, но неоднородный рынок; стартуем с юридических лиц/команд, а не называем все МСП адресным рынком. | Это не число потенциальных LMS-покупателей и не оценка TAM. |
| [DataReportal Digital 2026 Kazakhstan](https://datareportal.com/reports/digital-2026-kazakhstan) | На конец 2025: 19,5 млн интернет-пользователей, 16,9 млн social-media identities; LinkedIn указывает 1,90 млн members. | Обосновывает тест digital acquisition и LinkedIn как узкий B2B-канал. | Identities не равны уникальным покупателям; LinkedIn — members, не MAU. |
| [ILO: workplace-safety training in Kazakhstan](https://www.ilo.org/resource/news/kazakhstan-strengthens-workplace-safety-through-new-training-programme) | В 2025 ILO и работодатели проводили обучение специалистов по ОТиПБ. | Подтверждает наличие профессионального контекста для discovery с производственными компаниями и партнёрами по обучению. | Не подтверждает, что Kamilya удовлетворяет нормативным требованиям. |
| [Минтруда РК: изменение правил обучения по безопасности и ОТ](https://www.gov.kz/memleket/entities/enbek/press/news/details/1256107?lang=ru) | В 2026 ведомство сообщало о переносе сроков введения новых правил. | Требует осторожности: не строить кампанию на утверждении о legal compliance. | Нужна отдельная юрпроверка каждой формулировки и актуального правила. |

Канал Telegram/WhatsApp принимается как **рабочая гипотеза коммуникации с продажами**, а не как статистически доказанный лучший acquisition-канал. Instagram — тест на спрос/ретаргетинг, LinkedIn — точечный тест на руководителей HR/L&D; широкая закупка охвата запрещена до появившейся воронки.

### 3.2. Приоритетные сегменты

| Приоритет / сегмент | Размер и отрасль | Триггер и боль | ЛПР / возражения | Путь до сделки | Первый use case |
|---|---|---|---|---|---|
| P0: мультифилиальные сервисы и розница | 50–300 сотрудников; retail, сервис, HoReCa, несколько точек | быстрый ввод новичков, разрозненные инструкции, HR не видит завершение | HRD/HR manager; «у нас уже есть папки/чат», «люди не пройдут» | тёплый intro или список 50 компаний → 15-мин discovery → demo на их инструкции → 14-дневный пилот → ручной proposal | onboarding одной роли в 1–3 точках, 3–10 сотрудников |
| P0: логистика, склад, лёгкое производство | 50–500; сменные/операционные команды | регулярное ознакомление с внутренними процедурами и смена персонала | HR/L&D + руководитель операций; «нужен юридически значимый журнал», «нужен kiosk» | партнёр по обучению/ОТ → discovery на внутренний вводный материал → controlled pilot | внутренний вводный курс; не продаётся как ОТ/compliance-решение |
| P1: консалтинг и частные учебные центры | 10–80 системных сотрудников, B2B-клиенты | нужно быстро превратить свой материал в единый курс для клиентского пилота | владелец/академический директор; «нужен SCORM/брендирование/оплата» | founder referral → demo → один курс и одна клиентская группа | native-курс для внутренней команды центра; SCORM не обещать |
| P1: сети клиник/салонов/франшизы | 30–200; стандартизированные роли | единообразный onboarding и проверка знаний между точками | операционный директор/HR; «какая польза за 14 дней?» | LinkedIn/партнёр/прямой контакт → документ клиента → demo | сервисный стандарт для одной роли |
| P2: компании 500+ с HRIS/SSO/обязательным SCORM | 500+; regulated/enterprise | комплексная интеграция и procurement | HRD, IT, legal; «нужны SSO, интеграции, SLA» | discovery-only, без обещания сроков | не включать в основную воронку до product validation |

**Первый ICP:** юридическое лицо с 50–300 сотрудниками, 1–3 точками, русскоязычным HR/методологом, готовое дать одну внутреннюю инструкцию и 3–10 пилотных обучающихся. Это сегмент, где ценность достигается без интеграции, SCORM, kiosk и автоматического billing.

## 4. Позиционирование и сообщения

### 4.1. Основное ценностное предложение

**RU:** Kamilya помогает HR и методологу превратить внутренний документ в учебный курс, назначить его пилотной группе и увидеть подтверждённое завершение — без запуска тяжёлого проекта автоматизации.
**KK:** Kamilya HR мен әдіскерге ішкі құжатты оқу курсына айналдырып, оны пилоттық топқа тағайындап, расталған аяқталуын көруге көмектеседі — күрделі автоматтандыру жобасын бастамай-ақ.

Измеримая польза рабочего процесса — не «AI сам всё сделает», а: **один согласованный документ → черновик курса и теста → назначение 3–10 людям → хотя бы одно завершение и сертификат → запись в журнале**. Проверка содержания остаётся у клиента.

### 4.2. Headline и supporting copy

| Вариант | RU | KK |
|---|---|---|
| 1 | **Превратите рабочую инструкцию в пилотный курс.** Загрузите документ, проверьте курс и тест, назначьте его команде и посмотрите результат за 14 дней. | **Жұмыс нұсқаулығын пилоттық курсқа айналдырыңыз.** Құжатты жүктеңіз, курс пен тесті тексеріңіз, командаға тағайындап, 14 күнде нәтижесін көріңіз. |
| 2 | **От документа — к подтверждённому прохождению.** Kamilya объединяет подготовку курса, назначение и контроль результата для первого пилота. | **Құжаттан — расталған аяқтауға дейін.** Kamilya алғашқы пилот үшін курсты дайындауды, тағайындауды және нәтижені бақылауды біріктіреді. |
| 3 | **Запустите обучение одной роли без долгого внедрения.** Начните с 3–10 сотрудников и одного внутреннего материала. | **Бір рөлді оқытуды ұзақ енгізусіз бастаңыз.** 3–10 қызметкерден және бір ішкі материалдан бастаңыз. |

### 4.3. Pitch 30 секунд

«Kamilya — LMS для первого управляемого пилота обучения. HR или методолог загружает внутреннюю инструкцию, получает черновик курса, проверяет содержание и назначает его небольшой группе. Когда участники проходят уроки и тест, команда видит завершение, сертификат и запись в журнале. За 14 дней мы вместе проверяем, подходит ли этот процесс вашей компании — без обещаний интеграций или автоматической оплаты, которых ещё нет.»

### 4.4. Ролевые сообщения

| Аудитория | RU | KK | CTA |
|---|---|---|---|
| HR / руководитель обучения | «Соберите первый учебный пилот по вашей инструкции и получите видимый результат по небольшой группе.» | «Өз нұсқаулығыңыз бойынша алғашқы оқу пилотын іске қосып, шағын топтың нақты нәтижесін көріңіз.» | «Запросить 20-мин demo» / «20 минуттық demo сұрау» |
| Методолог | «Начните с документа, проверьте AI-черновик, добавьте уроки и тест — содержание остаётся под вашим контролем.» | «Құжаттан бастаңыз, AI-нобайды тексеріңіз, сабақтар мен тест қосыңыз — мазмұн сіздің бақылауыңызда.» | «Показать документ на demo» / «Demo-да құжатты көрсету» |
| Руководитель / операционный директор | «Проверьте на одной роли, можно ли сократить ручную сборку вводного обучения и увидеть прохождение команды.» | «Бір рөлде кіріспе оқытуды қолмен жинауды азайтып, команданың өтуін көруге болатынын тексеріңіз.» | «Выбрать пилотную роль» / «Пилоттық рөлді таңдау» |

### 4.5. Запрещённые и безопасные формулировки

| Нельзя / рискованно | Безопасная замена |
|---|---|
| «Соответствует всем требованиям закона РК» | «Подходит для внутреннего учебного пилота; юридические требования проверяет компания.» |
| «Заменяет обязательный журнал» | «Показывает журнал обучения внутри платформы.» |
| «Гарантирует результат / ROI» | «Помогает проверить гипотезу на пилотной группе; результат измеряется вместе с клиентом.» |
| «AI создаёт готовый курс за X минут» | «AI формирует черновик; содержание проверяет методолог.» |
| «SCORM/kiosk готовы для вашего запуска» | «Эти сценарии проходят отдельную проверку; обсудим после validation.» |
| «Оплатите и мгновенно расширьте тариф» | «Запросите условия; активация пока сопровождается вручную.» |
| «Telegram обязателен» | «Основной путь — email; Telegram может быть дополнительным каналом.» |

## 5. Воронка, активация и 14 дней trial

### 5.1. События воронки

Все проценты ниже — **гипотезы первых 90 дней**, не benchmark и не обещание результата. Считать отдельно по source/segment и с размером выборки.

| Этап | Цель / переходное событие | Гипотеза конверсии | Главная причина отказа | Product/sales действие | Owner / SLA |
|---|---|---:|---|---|---|
| Ad / контент → landing | `landing_view` с UTM | 1–3% cold; 5–12% тёплый CTR | абстрактный AI-claim, нет доверия | сегментный кейс «одна инструкция → пилот» и CTA demo | Growth, еженедельно |
| Landing → регистрация | `registration_started` | 3–8% тёплый трафик | непонятны лимиты и что будет после trial | рядом показать 14 дней, 1+1 курса, 10/3, «без карты» только если проверено | Growth + Product, P0 / 48 ч |
| Регистрация → первый вход | `registration_completed`, затем `first_login` | 45–70% | OTP не пришёл/нет ясного следующего шага | ручной WhatsApp/email follow-up; проверить deliverability | Sales ops, 1 рабочий час |
| Первый вход → документ | `first_document_uploaded` | 55–75% assisted | нет подходящего документа, страх загрузки | checklist «что можно загрузить», предложение white-glove upload; не просить чувствительные документы | Methodologist, 1 рабочий день |
| Документ → первый курс | `first_course_created` | 70–85% | AI output непригоден или job непонятен | совместный review, показать fallback/статус, дать шаблон ручного курса | Methodologist + Product, 4 ч |
| Курс → назначение | `first_assignment_created` | 60–80% | путаются роли и список людей | совместный экран назначения, 3 пилотных человека заранее | CS, 1 рабочий день |
| Назначение → первое прохождение | `first_learning_started` | 50–75% | сотрудники не получили/не поняли приглашение | личное сообщение лидеру группы + 15-мин слот прохождения | HR клиента + CS, 24 ч |
| Прохождение → сертификат | `first_certificate_issued` | 40–65% от назначенных | тест/урок не завершён, мало времени | follow-up с прогрессом, не подменять прохождение | HR клиента + CS, день 7 |
| Активация → платный диалог | `upgrade_requested` или qualified sales note | 15–30% активированных trial | ценность не сформулирована, нет price/process | day-10 value review, proposal с объёмом и ручной активацией | Founder, 24 ч |

### 5.2. Activation milestone

**A1: «первое доказанное обучение»** — в течение 72 часов после первого входа создан или проверен первый курс, он назначен минимум 3 пилотным обучающимся, минимум один из них начал обучение. Полная активация **A2** — до дня 7 выдан минимум один сертификат и HR видит запись в журнале. В аналитике activation rate = `tenants_with_A2 / trial_tenants_started`.

### 5.3. Ручной план trial

| День | Действие | Артефакт / событие | Владелец |
|---|---|---|---|
| До старта | 15-мин qualification: сегмент, роль, документ, 3–10 участников, язык, отсутствие blocker-интеграций | ICP score и дата kickoff | Founder |
| 0 | подтверждение регистрации, проверка первого входа/OTP, назначение владельцев HR и методолога | `first_login` или incident | CS |
| 1 | 30-мин kickoff: выбрать одну роль и успех A2; согласовать допустимый документ | pilot charter на 1 страницу | Founder + клиент |
| 2 | загрузить документ с методологом; объяснить, что нельзя загружать PII/секреты без разрешения | `first_document_uploaded` | Methodologist |
| 3 | просмотреть AI-черновик, отредактировать уроки/тест и опубликовать | `first_course_created` | Методолог клиента + CS |
| 4 | добавить 3–10 обучающихся и сделать первое назначение | `first_assignment_created` | Методолог клиента |
| 5 | отправить обучающимся короткую инструкцию и пройти первый learner check | `first_learning_started` | HR клиента |
| 7 | value review: процент начала, блокеры, первое завершение/сертификат | A1/A2 dashboard snapshot | Founder |
| 8–10 | устранить один главный blocker; не расширять scope на SCORM/kiosk/integrations | issue log и owner | Product + CS |
| 11–12 | commercial review: желаемое число людей, следующий курс, ручной proposal | `upgrade_requested` / loss reason | Founder |
| 13 | отправить summary: достигнутые события, открытые риски, проект условий | 1-page pilot report | Founder |
| 14 | решение: paid/manual activation, один раз продлить с причиной или закрыть и пометить reason | sales stage / stop reason | Founder + owner продукта |

## 6. План на 90 дней

Даты относительны к старту программы. Стоимость — лимит на действие, включая налоги/комиссии где применимо; `0` означает силами команды. Любая paid-активность имеет отдельный UTM и stop/go.

| Приоритет | Действие | Канал | Сегмент | Артефакт | Ответственный | Дата | Стоимость, KZT | KPI | Продолжение / остановка |
|---|---|---|---|---|---|---|---:|---|---|
| P0 | Утвердить truth table, оффер trial и claim gate | internal | все | этот документ + claim checklist | Product owner | нед. 0 | 0 | 0 неподтверждённых claims | stop публикации при спорном claim |
| P0 | Настроить UTM, события и weekly funnel sheet | product/analytics | все | event spec, dashboard | Growth + engineer | нед. 0–1 | 0–80 000 | 100% новых лидов с source | stop paid до события `registration_completed` |
| P0 | Сформировать 50 ICP-аккаунтов и 20 тёплых интро | founder network | P0 | account list с pain hypothesis | Founder | нед. 1 | 0 | 20 интро, 8 ответов | сменить list, если reply <10% после 50 валидных контактов |
| P0 | Подготовить 20-мин demo и pilot charter | demo / Zoom | P0 | demo script, one-pager | Founder + CS | нед. 1 | 0–30 000 | 5 проведённых demo | менять сценарий, если <40% доходят до документа |
| P0 | Провести 10 discovery-интервью без продажи функций roadmap | call / WhatsApp | P0/P1 | interview notes, objections taxonomy | Founder | нед. 1–2 | 0 | 10 интервью, 3 повторяемые боли | остановить сегмент, если <3 признают боль/триггер |
| P0 | Запустить 2 assisted trials | direct + demo | P0 | 2 pilot charters, A1/A2 log | CS + Methodologist | нед. 2 | 0 | 2 регистрации, 1 A2 | pause acquisition при неустранённом P0 blocker |
| P0 | Уточнить landing CTA: Try trial, Request demo, Request terms | landing backlog | P0 | approved copy/spec, не код в рамках этого документа | Growth + Product | нед. 2 | 0 | понятный маршрут у 5 usability checks | stop publication при false billing/SCORM claim |
| P1 | 2 RU case-style posts: «одна роль/одна инструкция» | LinkedIn, HR Telegram communities через согласование | P0 | 2 posts + UTM | Growth | нед. 3–4 | 40 000 | 10 qualified clicks, 2 calls | оставить, если call rate >=10% от qualified clicks |
| P1 | 1 KK version landing message и demo opener | landing / sales | P0 | approved KK copy | Native KK reviewer | нед. 3–4 | 50 000 | review passed | не публиковать без native review |
| P1 | 50 персональных outbound сообщений, 2 варианта | LinkedIn/email | P0 | sequence + reply log | Founder | нед. 3–4 | 0 | >=10% reply, >=4 discovery | остановить variant after 30 sends if reply <5% |
| P1 | Партнёрский shortlist: 15 консультантов/центров обучения/ОТ | referrals | P0/P1 | partner scorecard | Founder | нед. 3–4 | 0 | 5 meetings, 1 co-pilot | stop if no qualified introductions after 8 meetings |
| P1 | Провести 1 закрытый webinar «из инструкции в пилот» | Zoom + partner | P0 | recording, attendee list, CTA | Founder + partner | нед. 4 | 50 000 | 15 registrations, 3 qualified demos | repeat if demo rate >=15% |
| P1 | 2 landing creative variants и интервью после 5 сессий | landing / calls | P0 | message test summary | Growth | нед. 5 | 30 000 | visitor→demo/start registration | keep only variant with >=20% relative lift on >=100 visits |
| P1 | Paid test 1: LinkedIn lead/message, узкий список | LinkedIn | HR/L&D P0 | 2 ads, UTM campaign | Growth | нед. 5–6 | 150 000 media | 3 qualified leads | stop at 150k if CPQL >50 000 или 0 demo |
| P1 | Paid test 2: Instagram/Meta retargeting only | Instagram/Meta | посетители/видео viewers | 2 short creatives | Growth | нед. 5–6 | 100 000 media | 2 qualified leads | stop if no registration/demo after 100k |
| P1 | Завести weekly win/loss и release-risk review | internal | активные trials | 30-min weekly log | Founder + Product | нед. 5–8 | 0 | 100% trials tagged reason | stop scope creep; P0 blocker идёт в backlog |
| P1 | 3–4 новых assisted trial, только прошедших ICP score | demo/direct | P0 | pilot charters | CS + Founder | нед. 5–8 | 0 | >=50% A1, >=30% A2 | pause new trials if A1 <30% for 3 consecutive tenants |
| P1 | 3 segment-specific content pieces + 1 customer interview | owned/partner | P0/P1 | posts, approved quote only | Growth | нед. 5–8 | 90 000 | 6 qualified conversations | stop topic if 0 conversations across 2 posts |
| P1 | Предложить ручную коммерческую активацию A2-тенантам | call/email | активированные | proposal template | Founder | нед. 7–8 | 0 | 2 paid conversations | revise packaging if 0 after 5 A2 tenants |
| P1 | Partner co-demo с одним валидированным партнёром | partner event | P0 logistics/ops | shared agenda, UTM | Founder | нед. 8 | 80 000 | 3 qualified demos | continue only after 1 A1 trial |
| P1 | Синтезировать канал/ICP: cohort table, conversion and manual hours | internal | все | day-60 decision memo | Growth + Founder | нед. 8 | 0 | источник, дающий A1 | stop channels without A1 after agreed test spend |
| P2 | Удвоить только лучший paid channel | paid | winning P0 segment | creative v3, audience log | Growth | нед. 9–10 | до 300 000 | CPQL <= test threshold, A1 evidence | stop weekly if threshold worsens 30% |
| P2 | 2-й webinar / partner roundtable на основе реального objection | partner/webinar | winning segment | recording, follow-up | Founder | нед. 9–10 | 100 000 | 20 reg, 4 qualified demos | repeat only if >=1 A1 trial |
| P2 | Подготовить customer proof только с письменным разрешением | owned sales | A2 клиент | anonymized case/quote | CS + client | нед. 9–11 | 30 000 | 1 approved proof | never fabricate logo/results |
| P2 | Провести 5 pricing/process interviews с A2 и lost leads | calls | qualified leads | willingness-to-pay notes | Founder | нед. 10–11 | 0 | 5 evidence-backed insights | no price change without owner approval |
| P2 | Решение day-90: double-down, revise ICP или pause paid | internal | все | scorecard, next-quarter plan | Product owner | нед. 12 | 0 | 1 paid tenant or evidence-backed no-go | pause expansion unless gates below are met |

**Gates к week 9–12:** (1) минимум 5 qualified trials, (2) не менее 50% дошли A1, (3) не менее 30% дошли A2, (4) один канал дал ≥2 qualified demos и ≥1 A1, (5) есть измеренные manual hours/trial и владелец P0 backlog. Без всех пяти условий не запускать expanded scenario.

## 7. Бюджеты и сценарии

Это рабочие лимиты на 90 дней, **не прогноз CAC/LTV**. НДС, агентские комиссии и зарплата founders не включены, если не указано иначе.

| Категория | Founder-led | Validation | Expanded после gates |
|---|---:|---:|---:|
| Реклама | 0 | 250 000 | 1 200 000 |
| Производство контента / KK review | 80 000 | 250 000 | 550 000 |
| Мероприятия / партнёрские webinars | 40 000 | 180 000 | 450 000 |
| Подрядчики / дизайн / research transcription | 40 000 | 220 000 | 400 000 |
| Инфраструктура аналитики / CRM sheet / calls | 40 000 | 100 000 | 200 000 |
| Резерв на controlled pilot support | 0 | 100 000 | 300 000 |
| **Итого** | **200 000 KZT** | **1 100 000 KZT** | **3 100 000 KZT** |

| Сценарий | Что делаем | Go / stop |
|---|---|---|
| Founder-led | 50 account list, intros, 10 discovery, 2 trials, почти без paid. | Продлить, если 1 tenant достиг A2 и есть 1 коммерческий разговор; иначе пересобрать ICP/message без увеличения spend. |
| Validation | Два контролируемых paid test, webinar, 3–4 дополнительных trials, партнёрский discovery. | Продлить лучшую связку только при CPQL ≤50 000 KZT **и** хотя бы одном A1 от канала; остановить остальные. |
| Expanded | Увеличить один проверенный канал, несколько co-marketing активностей, customer proof. | Разрешён только после пяти gates из раздела 6 и подтверждённой способности команды сопровождать новые trial. |

**Диапазоны-гипотезы для validation:** CPQL 15 000–50 000 KZT, qualified demo → assisted trial 30–60%, A2 trial → paid conversation 20–40%. Расчётный CAC нельзя публиковать или использовать для инвестрешения, пока нет минимум 10 qualified trials, фактических расходов на канал и итогов paid/closed-lost. Для проверки нужны: spend, source, ICP score, demo held, A1/A2, hours команды, price/proposal, paid/closed-lost и причина.

## 8. Контент, креативы и demo

### 8.1. Десять тем

| # | Тема | Аудитория / боль | Proof point | CTA / язык |
|---:|---|---|---|---|
| 1 | «Одна инструкция — один пилот: что подготовить за 30 минут» | HR, не знает с чего начать | 14-day scoped trial | запросить demo; RU/KK |
| 2 | «Где AI помогает методологу, а где нужна проверка» | методолог, недоверие к AI | human review в flow | показать документ; RU |
| 3 | «3 сигнала, что onboarding живёт в папках и чатах» | HR/ops | workflow document→course→assignment | выбрать пилотную роль; RU/KK |
| 4 | «Как выбрать 3–10 человек для первого обучения» | HR | trial limits и A2 | скачать pilot checklist; RU |
| 5 | «Что увидит руководитель после первого прохождения» | CEO/ops | completion, certificate, training log | 20-min demo; RU |
| 6 | «Не обещаем compliance: как честно провести внутренний learning pilot» | safety/ops | claim gate | consultation/discovery; RU |
| 7 | «Разбор анонимной инструкции: какие уроки и тесты проверить» | методолог | native authoring flow | принести свой документ; RU |
| 8 | «Email-first trial: Telegram — не обязательный шаг» | HR/IT | current access policy | начать по email; RU/KK |
| 9 | «Как не превратить trial в бесконечный проект» | founder/HR | 14-day day plan | получить pilot charter; RU |
| 10 | «Вопросы, которые нужно задать LMS до покупки» | buyer | transparent limits: billing/SCORM/kiosk | чек-лист + demo; RU/KK |

### 8.2. Пять коротких видео (30–45 секунд)

| Сценарий | Аудитория / боль | Кадры и proof | CTA / язык |
|---|---|---|---|
| «Папка → пилот» | HR, документы не превращаются в обучение | папка с инструкцией → загрузка → редактор → назначение; экран без персональных данных | «Покажите одну инструкцию на demo»; RU |
| «AI не заменяет методолога» | методолог, риск галлюцинации | AI-черновик → чек правильного ответа → правка → publish | «Проверьте черновик на своём материале»; RU/KK subtitles |
| «Первый сертификат» | ops, нужен видимый результат | learner completes lesson/test → certificate → public verification screen | «Запустите группу из 3–10 человек»; RU |
| «14 дней без большого внедрения» | founder/HR, нет ресурса | days 1/3/4/7/14 on-screen | «Получить pilot charter»; RU/KK |
| «Честный scope» | IT/legal buyer | on-screen: native pilot ✓, SCORM/kiosk/integrations — отдельная проверка | «Обсудить ваш сценарий»; RU |

### 8.3. Три объявления

| Канал | Текст | CTA / guardrail |
|---|---|---|
| LinkedIn message/ad, RU | **Ваша инструкция уже есть. А учебный пилот?** Kamilya помогает превратить внутренний документ в курс и тест, назначить его небольшой группе и увидеть завершение. Начните с 14 дней: 1 AI-курс, 1 курс по должностной инструкции, до 10 обучающихся. | «Запросить 20-мин demo». Не использовать без актуальной проверки лимитов. |
| Instagram retargeting, RU | **Не обещаем “волшебный AI”.** Покажем на одной инструкции: черновик курса → проверка методологом → назначение → подтверждённое прохождение. | «Посмотреть сценарий пилота». Не заявлять ROI/compliance. |
| Partner post, KK | **Ішкі құжаттан оқу пилотына дейін.** Kamilya көмегімен бір нұсқаулықты курсқа айналдырып, шағын топқа тағайындап, аяқталуын тексеріңіз. | «20 минуттық demo сұрау». Native flow only. |

### 8.4. Две trial email-серии

| Серия | Когда / кому | Сообщения | Цель / CTA |
|---|---|---|---|
| A: activation | день 0/1/3/5/7, зарегистрированный HR/методолог | 0: «Подтвердите первый вход»; 1: «Выберите роль и документ»; 3: «Проверьте первый курс»; 5: «Назначьте 3 человек»; 7: «Сверим первый результат» | A1/A2; email + ручной WhatsApp только с согласия контакта. RU, затем KK после review. |
| B: value/decision | день 10/12/14, активный owner | 10: «Что уже прошло в пилоте»; 12: «Следующий курс и нужный объём»; 14: «Решение: условия, продление или feedback» | paid conversation или честный loss reason; не обещать checkout/auto-upgrade. RU/KK per preferred language. |

### 8.5. Demo на 20 минут

| Минута | Содержание | Подтверждение / результат |
|---:|---|---|
| 0–2 | спросить роль, документ, пилотную группу, язык, integration blockers | qualification; остановить demo при enterprise blocker |
| 2–4 | показать честный scope trial и неготовые направления | trust; limits understood |
| 4–8 | показать native путь: документ → AI-черновик → human review | не обещать «готовый курс без проверки» |
| 8–12 | уроки, тест, публикация, назначение | выбрать 3–10 learners |
| 12–15 | learner completion, certificate и training log | показать native E2E proof |
| 15–17 | показать 14-day plan и A1/A2 | согласовать owner/дату kickoff |
| 17–20 | objections: billing ручной, SCORM/kiosk отдельный QA, legal claims отсутствуют | next step: pilot charter или disqualify |

## 9. Аналитика

### 9.1. События и UTM

| Событие | Когда срабатывает | Обязательные свойства |
|---|---|---|
| `landing_view` | загрузка landing | `anonymous_id`, `locale`, `utm_*`, `landing_variant`, `referrer` |
| `demo_requested` | валидная отправка формы demo | `lead_id`, `segment`, `employee_band`, `intent`, `utm_*` |
| `registration_started` / `registration_completed` | начало / успешная регистрация tenant | `lead_id`, `tenant_id` после создания, `locale`, `intent`, `utm_*` |
| `first_login` | первый успешный вход владельца | `tenant_id`, `role`, `days_since_registration` |
| `first_document_uploaded` | первый документ | `tenant_id`, `document_type`, `source` — без имени/содержимого файла |
| `first_course_created` | первый native course persisted | `tenant_id`, `creation_path` (`ai`/manual), `days_since_registration` |
| `first_assignment_created` | первое назначение | `tenant_id`, `recipient_count`, `assignment_type` |
| `first_learning_started` | первый learner progress | `tenant_id`, `course_id`, `days_since_registration` |
| `first_certificate_issued` | первый сертификат | `tenant_id`, `course_id`, `days_since_registration` |
| `upgrade_requested` / `manual_sale_stage_changed` | запрос условий / изменение sales stage | `tenant_id`, `stage`, `loss_reason` при закрытии |

UTM: `utm_source`, `utm_medium`, `utm_campaign`, `utm_content`, `utm_term`; дополнительно `campaign_id`, `creative_id`, `partner_id`, `landing_variant`. Нельзя отправлять в UTM email, телефон, название компании, документ или иной PII. Единый ключ склейки: `lead_id`, затем `tenant_id`; доступ к маппингу — только sales ops.

### 9.2. Метрики

| Метрика | Формула | Источник | Частота / владелец |
|---|---|---|---|
| North Star: активированные пилотные тенанты | число уникальных tenant с A2 за 28 дней | product events + sales sheet | weekly / Founder |
| Activation rate | `tenants with A2 ÷ trial_tenants_started` | events | weekly cohort / Growth |
| Trial-to-paid | `paid tenants ÷ trials с истекшим окном решения` | manual sales stage + tenant status | monthly cohort / Founder |
| Time-to-value | median от `registration_completed` до `first_certificate_issued` | events | weekly / Product |
| CPQL | attributable media spend ÷ qualified leads | ad platforms + CRM sheet | weekly / Growth |
| Funnel conversion | event B ÷ event A для каждой пары из раздела 5 | events | weekly / Growth |
| Trial retention | `tenants with ≥1 meaningful activity day 7/14 ÷ started trials` | events | weekly / CS |
| Paid retention | `paid tenants with active learning event in month N ÷ paid cohort` | events + billing status | monthly / Founder |
| Guardrail: OTP deliverability | delivered/accepted OTP proxy; failures and support tickets | Resend logs + support sheet | daily / CS |
| Guardrail: AI job reliability | completed AI jobs ÷ started jobs; pending/running age | product/worker monitoring | daily / Product |
| Guardrail: misleading claim incidents | published assets with claim-gate exception | content review log | before every publish / Product owner |
| Guardrail: manual load | CS+Founder hours per active trial | timesheet | weekly / Founder |

Первый dashboard — простая cohort-таблица: `source → segment → lead → demo → registration → A1 → A2 → paid conversation → paid`, с расходами, manual hours и loss reason. Не выводить причинность по десяткам наблюдений.

## 10. Backlog маркетинговых и продуктовых улучшений

| Приоритет | Проблема | Решение | Evidence | Impact / effort | Критерий готовности |
|---|---|---|---|---|---|
| P0 | Trial usage и оставшиеся лимиты не объяснены в onboarding | показать 14 дней, 1+1 курса, 10 learners, 3 users, expiry и контакт support; не raw error | [tenant/trial flow](../product/tenant-registration-trial-flow.md) | высокий / M | 5 usability checks понимают лимит и следующий шаг; product event usage visible |
| P0 | Нет подтверждённого CTA «demo» и ручного sale route | добавить/проверить CTA, форму intent и ownership нового лида; не утверждать online checkout | [Project context](../PROJECT-CONTEXT.md) | высокий / S–M | каждый CTA создаёт lead с source; SLA owner <1 h |
| P0 | Название tenant и контекст роли могут быть неочевидны | persistent tenant name + role banner, особенно при support/impersonation | [Role UX audit](../reports/2026-07-13_role-based_ux-ui_audit.md) | высокий / M | 5/5 pilot users correctly identify tenant/role |
| P0 | Надёжность загрузки/AI влияет на первый value | progress, retry/failure state, supported-file checklist и support handoff; мониторить queue | [AI smoke](../reports/2026-07-14_ai-production-smoke.md) | высокий / M | job has terminal state; failed upload gets actionable message |
| P0 | Первый методолог не видит цельный authoring flow | guided checklist: document → review → test → publish → assign | [Role UX audit](../reports/2026-07-13_role-based_ux-ui_audit.md) | высокий / M | методолог завершает A1 без `/admin/*` legacy navigation |
| P0 | Ролевой путь назначения неочевиден | единый assignment CTA после publish, owner matrix и clear 403 state | [Role UX audit](../reports/2026-07-13_role-based_ux-ui_audit.md) | высокий / M | 3 pilot methodologists create assignment without CS |
| P0 | Trial expiry UI не даёт коммерческий next step | dedicated `trial_expired` support/upgrade state | [trial enforcement](../reports/2026-07-14_trial-enforcement.md) | высокий / S | expired tenant sees contact path, not generic error |
| P0 | Pricing/manual upgrade не оформлены как честный процесс | approved pricing/proposal policy, manual activation SLA, no checkout claim | [Project context](../PROJECT-CONTEXT.md) | высокий / M | qualified lead receives correct proposal ≤1 business day |
| P1 | Нет явного proof после достижения результата | shareable, permissioned pilot summary: completion/certificate/log, without PII | [First-tenant E2E](../reports/2026-07-14_first-tenant-e2e.md) | средний / S | owner can export/review one safe summary; consent recorded |
| P1 | Landing не разделяет HR, methodologist и руководителя | 3 message paths and demo form segmentation | positioning section | средний / M | each path has CTA and source-to-A1 tracking |
| P1 | Email deliverability может ломать registration | Resend dashboard alert, neutral support flow, deliverability measurement | [Project context](../PROJECT-CONTEXT.md) | средний / S | daily failure rate and ticket reason visible |
| P1 | Данные и безопасность не объяснены buyer | approved data-handling FAQ; no invented certification/legal claim | product/security owner evidence required | средний / M | legal/security review completed before publication |
| P1 | Штатка/отделы позиционируются шире доказанного | demo-only feature flags and role-specific explanations | [Role UX audit](../reports/2026-07-13_role-based_ux-ui_audit.md) | средний / S | no marketing asset presents them as validated core flow |
| P2 | SCORM может расширить ICP, но не доказан | manual staging QA with real packages; publish result before claim | [SCORM QA](../reports/2026-07-13_scorm_qa_execution.md) | средний / L | iSpring/Articulate import→launch→commit→log E2E passed |
| P2 | Kiosk востребован в сменных командах, но privacy risk | browser/privacy/auto-logout staging QA and incident criteria | [Role UX audit](../reports/2026-07-13_role-based_ux-ui_audit.md) | высокий риск / L | next learner cannot access prior session/data |
| P2 | Cohort/rule automation может снижать manual work | end-to-end worker/idempotency/duplicate tests and UX | [Valkey migration](../reports/2026-07-14_valkey-vps-migration.md) | средний / L | repeat run creates no duplicates; audit evidence |
| P2 | Масштабирование requires sales/CRM process | select CRM only after required fields, consent and handoff policy are approved | README landing identifies CRM worker as future | средний / M | no lead is lost; source-to-stage sync verified |

## 11. Риски и контроль публикаций

| Риск | Ранний сигнал | Контроль / owner |
|---|---|---|
| Слабая доказательная база | claim нельзя связать с truth table | Product owner approval before asset; remove claim, not hedge it |
| Ручная операционная нагрузка | >4 CS+Founder часов на trial или 3 parallel trials | cap concurrent trials; improve top blocker before more acquisition |
| Email deliverability | no `first_login` after registration; support tickets | daily monitor, fallback support contact, no self-hosted-mail promise |
| Юридические claims | prospect asks about mandatory training/compliance | discovery only; legal review; no statement of compliance |
| Безопасность данных | client asks to upload confidential/PII file | do not request it; approved data FAQ and owner review before upload |
| Незавершённый billing | prospect expects card checkout | explicit manual proposal/activation; set response SLA |
| AI/provider reliability | stale job, failed generation, low-quality output | observe queue; human review; use manual course path if needed |
| SCORM/kiosk creep | buyer demands these in trial | disqualify or discovery-only until manual QA gates pass |

**Перед каждой публикацией:** (1) сверить asset с разделом 2, (2) проверить RU/KK носителем языка, (3) проверить CTA и UTM, (4) проверить privacy/consent для screenshot и client proof, (5) утвердить owner продукта. Никаких внешних писем, рекламных кабинетов и расходов этим документом не запускается.

## 12. Первые 10 действий и решения владельца продукта

### Первые 10 действий

1. Утвердить таблицу продуктовой правды и claim gate.
2. Назначить Founder, Growth, CS и Product owner по именам.
3. Согласовать pilot charter и критерии A1/A2.
4. Настроить event/UTM specification до paid traffic.
5. Проверить live CTA/форму demo и ручной lead SLA.
6. Составить 50 ICP-аккаунтов и получить 20 тёплых интро.
7. Провести 10 discovery-интервью с P0 сегментами.
8. Провести две 20-мин demo по скрипту, не продавая roadmap.
9. Запустить не более двух assisted trials и довести их до A1/A2.
10. Провести weekly win/loss review и остановить любой канал/claim, не дающий доказательства.

### Решения, которые требуются от владельца продукта

1. Кто принимает и активирует ручные paid-заявки, с каким SLA и какими утверждёнными условиями?
2. Какая цена/пакет и допустимое однократное продление trial могут быть предложены после A2? Это решение нельзя выводить из данного документа.
3. Разрешено ли вести первые пилоты на документах, содержащих персональные/чувствительные данные, и каков утверждённый процесс?
4. Какие сегменты/партнёры допустимы для публичной коммуникации и кто утверждает кейсы/логотипы?
5. Когда и кем будет вручную проверен live billing/upgrade flow?
6. Какой владелец и дата у P0 role-navigation/onboarding gaps?
7. Нужна ли отдельная legal review для wording про ОТ, сертификаты, хранение данных и журнал?

### Что вручную проверить до публикации/масштабирования

- actual production CTA landing → lead/demo → `register-tenant`, включая UTM и consent;
- email OTP delivery и первый вход для RU/KK test accounts;
- 14-day limit copy и `trial_expired` user experience;
- путь методолога document → course → quiz → assignment на staging/production-controlled tenant;
- native learner completion → certificate → public verification → training log;
- SCORM с реальными iSpring/Articulate пакетами и kiosk privacy/auto-logout — до любого claim;
- billing/manual activation flow и утверждённые цены — до CTA «купить»;
- казахские тексты носителем языка, accessibility и mobile landing;
- privacy/security wording владельцем продукта/юристом.

## 13. Итоговая логика решения на день 90

Успех первых 90 дней — не «много лидов», а один из двух честных результатов:

1. **Go:** есть хотя бы один платящий tenant либо подтверждённый paid pipeline, один воспроизводимый source→A1 путь, cohort-конверсии и измеренная ручная нагрузка; тогда инвестировать только в этот сегмент/канал.
2. **Learning no-go / revise:** нет A1/A2, CPQL выше порога или команда вручную не тянет flow; остановить paid, зафиксировать loss reasons и исправить один P0 blocker до следующего теста.

Такой подход удерживает Kamilya в продаваемом сегодня native pilot: документ компании → курс → назначение → прохождение → подтверждённый результат. Всё, что шире, остаётся предметом отдельного evidence и согласования.
