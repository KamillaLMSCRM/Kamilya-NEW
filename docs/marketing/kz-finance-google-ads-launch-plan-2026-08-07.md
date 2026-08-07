# Kamilya Finance: Google Ads launch package

Дата исследования: 2026-08-07
Рынок: Казахстан
Язык первой кампании: русский
Статус: **подготовлено, запуск запрещён до прохождения gate**

## Вывод

Прямой поисковый спрос по формулировкам «обучение сотрудников финансовых
организаций / МФО / страховых / брокеров» составляет только `0–10` запросов в
месяц. Поэтому первая поисковая кампания должна ловить измеримый спрос на
проверку знаний, обязательное и корпоративное обучение, а принадлежность к
финансовому сектору квалифицировать в объявлении и на `/ru/finance`.

Отдельная KK search campaign пока не создаётся: все ранее проверенные
казахские формулировки также дали `0–10`. Страница `/kk/finance` сохраняется для
доверия, прямых продаж и последующего A/B-теста, но не получает отдельный
бюджет без новых данных.

## Структура

Одна Search-only кампания `KZ | Finance | Search | RU`:

1. `AG1 | Knowledge control` — проверка знаний и тестирование; основной
   intent-кластер.
2. `AG1b | Mandatory training` — отдельный proxy-кластер обязательного
   обучения. Он не доказывает финансовый intent и отключается, если достигнут
   отдельно согласованный validation cap без квалифицированного finance-лида.
3. `AG2 | Employee training` — корпоративное обучение и платформы для
   сотрудников.
4. `AG3 | Automation` — только exact match и отдельный контроль расходов.
5. `AG4 | LMS category` — ограниченный категорийный трафик; `LMS платформа`
   имеет объём `100–1000`, но падение `-90%` квартал к кварталу и год к году.
6. `AG5 | Vertical validation` — прямые финансовые формулировки; ad group и
   keywords остаются paused, потому что спрос `0–10`.

Используются только exact и phrase match. Broad match не применяется: Google
описывает broad как самый широкий тип соответствия, а phrase уже включает
exact и более близкие варианты. Для низкого B2B-объёма broad создаёт
неприемлемый риск нерелевантного трафика.

## Настройки аккаунта перед запуском

- Тип: Search only; Display expansion выключена.
- Search partners: выключить на первом тесте.
- География: Казахстан; выбирать присутствие пользователя в целевой
  географии, а не только интерес к ней.
- Язык: русский. Казахстанский текст тестировать через landing/outbound, а не
  отдельный search-бюджет.
- Auto-apply recommendations: выключить для broad match, автоматического
  добавления keywords и изменения ставок.
- Auto-tagging: включить, чтобы получать `gclid`.
- Кампания, все RSA и keywords импортируются paused.
- Дневной бюджет и стратегия ставок не задаются до согласования владельцем.
- Основная конверсия: `lead_form_success` после HTTP success от backend.
- `lead_form_open` и `lead_form_submit` — только secondary/diagnostic, в bidding
  не включаются.

## Объявления и message match

Для каждого активного ad group подготовлено по два RSA. Google допускает до 15
заголовков и 4 описаний; в пакете используется по 8 заголовков и 4 описания,
чтобы сохранить управляемую отраслевую семантику. Все объявления ведут на
`https://www.kml.kz/ru/finance` с разными `utm_content`.

Текст позиционирует Kamilya как B2B-платформу обучения сотрудников, а не как
финансовый продукт. Не используются обещания гарантированного соответствия,
юридически значимого ознакомления или автоматического утверждения курса.

## Конверсии и приватность

Landing сохраняет первую UTM/GCLID-атрибуцию только на время текущей браузерной
сессии. Форма требует явного согласия и отправляет время и версию текста
согласия в lead payload. Аналитические события не содержат имя, email, телефон,
компанию или комментарий.

Google tag загружается только после явного согласия и успешного сохранения
заявки. Публичные ID action `Kamilya | Finance lead form` зафиксированы в
client adapter; env `NEXT_PUBLIC_GOOGLE_ADS_ID` и
`NEXT_PUBLIC_GOOGLE_ADS_CONVERSION_LABEL` остаются опциональными overrides.

Перед загрузкой consent mode выставляет `ad_storage`, `ad_user_data`,
`ad_personalization` и `analytics_storage` в denied. Затем для уже согласованной
и успешно сохранённой заявки разрешаются только measurement и `ad_user_data`;
`ad_storage` и персонализация остаются denied. Consent mode не заменяет текст
согласия — выбор пользователя собирает сама форма.

## Launch gate

Запуск разрешён только когда выполнены все пункты:

- [ ] backend с расширенным lead contract развёрнут и smoke подтверждён;
- [ ] landing с session attribution и явным согласием развёрнут;
- [x] Google Ads conversion action `Kamilya | Finance lead form` создана,
  value `0`, count `One`, enhanced conversions выключены;
- [ ] production bundle содержит ID и label созданной conversion action;
- [ ] тестовая заявка с UTM и тестовым GCLID дошла в production lead storage;
- [ ] Tag Assistant показывает ровно одну conversion после успешной заявки;
- [ ] PII отсутствует в локальных analytics events, dataLayer и Google event;
- [ ] advertiser verification не запрошена либо успешно завершена;
- [ ] в аккаунте подтверждены Search only, выключенные Display expansion и
  Search partners, а география использует Presence, не interest;
- [ ] после импорта нет broad match: только exact/phrase; parent campaign
  paused, AG1–AG4 и AG1b enabled только под ней, AG5 и его keywords paused;
- [ ] дневной лимит и максимальный тестовый расход отдельно подтверждены
  владельцем;
- [ ] кампания вручную переведена из paused только после всех проверок.

## Первые 14 дней

- Просматривать search terms ежедневно в первые семь дней.
- Добавлять минус-слова только по фактическим нерелевантным запросам; не
  исключать потребительские финансовые термины вслепую, если они ещё не
  появились в отчёте.
- Оценивать не клики, а квалифицированные лиды: сектор, размер команды,
  обязательность обучения, наличие внутренних документов и готовность к
  пилоту.
- Не расширять match types и не включать vertical-validation ad group до
  появления качественных лидов из основных кластеров.
- На 7-й и 14-й день фиксировать: расходы, search terms, заявки, валидные
  заявки, согласованные демонстрации и причины отказа.

## Файлы

- `kz-finance-keyword-planner-results-2026-08-07.csv` — дополнительный Planner
  pass по ИБ и финансовым вертикалям.
- `kz-finance-google-ads-keywords-2026-08-07.csv` — keywords и статусы.
- `kz-finance-google-ads-negatives-2026-08-07.csv` — стартовые минус-слова.
- `kz-finance-google-ads-rsa-2026-08-07.csv` — два RSA на активный ad group.
- `kz-finance-google-ads-utm-matrix-2026-08-07.csv` — контракт атрибуции.

## Источники Google

- [Responsive search ads: лимиты и рекомендации](https://support.google.com/google-ads/answer/7684791?hl=en-t)
- [Рекомендации по RSA и количеству объявлений](https://support.google.com/google-ads/answer/12159014?hl=en)
- [Keyword matching options](https://support.google.com/google-ads/answer/7478529?hl=en-t)
- [Consent mode](https://support.google.com/google-ads/answer/10000067?hl=en)
- [Политика финансовых продуктов и услуг](https://support.google.com/adspolicy/answer/2464998?hl=en)
- [Advertiser verification для организаций Казахстана](https://support.google.com/adspolicy/answer/9872280?co=GENIE.CountryCode%3DKZ&hl=en)
