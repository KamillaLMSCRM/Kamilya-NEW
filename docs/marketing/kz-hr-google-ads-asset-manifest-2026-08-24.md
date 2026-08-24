# KZ HR Google Ads asset manifest — 2026-08-24

Status: `PARTIALLY READY`. This document is a local evidence manifest only. No
sitelink, logo or image in this document has been uploaded, previewed or applied.

## Sitelink evidence boundary

Both allowed production pages returned HTTP 200 with every query contract below.
The existing landing component exposes the same `features`, `how` and `pricing`
section IDs for both pages:

- source: `C:\Kamilya New\kamilya-landing\components\SolutionLanding.tsx`;
- SHA-256: `1B133AD644074F2A3198D5E9109EE89D66E9F66F553A04CA6B8FE98CD9EFF910`;
- size: 11,134 bytes;
- section definitions: `features`, `how`, `pricing`;
- browser verification: each URL reached the intended existing section rather
  than merely loading the base page.

| # | Link text | Description line 1 | Description line 2 | Final URL |
|---|---|---|---|---|
| 1 | Возможности онбординга | Курс, тест и маршрут новичка | По документам вашей компании | `https://www.kml.kz/ru/onboarding?utm_source=google&utm_medium=cpc&utm_campaign=kz_hr_search_ru&utm_content=sl_onboarding_features&utm_term={keyword}#features` |
| 2 | Как проходит онбординг | Сценарий запуска по шагам | Назначения, прогресс, результат | `https://www.kml.kz/ru/onboarding?utm_source=google&utm_medium=cpc&utm_campaign=kz_hr_search_ru&utm_content=sl_onboarding_how&utm_term={keyword}#how` |
| 3 | Демо онбординга | Покажем на ваших материалах | Обсудим пилот для команды | `https://www.kml.kz/ru/onboarding?utm_source=google&utm_medium=cpc&utm_campaign=kz_hr_search_ru&utm_content=sl_onboarding_demo&utm_term={keyword}#pricing` |
| 4 | Возможности оценки | Оценка знаний до найма | Без автоматического решения | `https://www.kml.kz/ru/candidate-assessment?utm_source=google&utm_medium=cpc&utm_campaign=kz_hr_search_ru&utm_content=sl_candidate_features&utm_term={keyword}#features` |
| 5 | Как проходит оценка | Курс, ссылка, PIN и результат | Контроль сроков и попыток | `https://www.kml.kz/ru/candidate-assessment?utm_source=google&utm_medium=cpc&utm_campaign=kz_hr_search_ru&utm_content=sl_candidate_how&utm_term={keyword}#how` |
| 6 | Демо оценки кандидатов | Покажем сценарий оценки | Обсудим пилот для роли | `https://www.kml.kz/ru/candidate-assessment?utm_source=google&utm_medium=cpc&utm_campaign=kz_hr_search_ru&utm_content=sl_candidate_demo&utm_term={keyword}#pricing` |

All link texts are at most 25 characters. Every description line is at most 35
characters. `utm_content` is stable and unique; the other UTM values preserve the
canonical HR contract.

Blocker: the current signed-in Google Ads bulk-template dialog exposes Campaign,
Ad group, Responsive Search Ad, Responsive Display Ad, Keyword and Negative
Keyword templates, but no sitelink template. Therefore a Google bulk Preview
schema for this six-row sitelink batch is not currently available. No manual UI
creation is authorized until root confirms an alternative deterministic Preview
and field-readback method. Status: `SITELINK_BULK_PREVIEW_SCHEMA_UNAVAILABLE`.

## Existing Kamilya visual candidates

Only the exact Kamilya logo derivative remains an approved candidate after root
visual review. Product screenshot derivatives were excluded before Google
Preview or upload because visible demo-company names, internal document names
and clipped interface content are unsuitable for external advertising. The
original screenshots and every derived product crop must not be uploaded.

| Asset | Canonical source and source SHA-256 | Proposed file | Dimensions | Proposed association / destination |
|---|---|---|---|---|
| Kamilya logo mark | `C:\Kamilya New\kamilya-landing\app\[locale]\layout.tsx` — `6F4D36556F8FD63C71C6CEEB4D1CC77F58ABA179E96CBC9B2E56308B2BF70E79`; corroborating `components\ui\Logo.tsx` — `6D67B9C536B2887483B861A75072E4A066D8D3998B2424BFB3A0134E78A8824A` | `docs\marketing\google-ads-assets-2026-08-24\kamilya-logo-mark-1200.png` — `4EEAC7A634B7C5A2EB316BC150B78D75CB12E4100CBEEBB7FF518537326CA1B1` | 1200x1200 | Company logo; no independent destination field. Do not enable automated assets. |

Excluded local derivatives, not tracked as canonical assets:

- `onboarding-courses-square-1200.png` — `6C1751D6FB0AABCFF1CC0CE7D991E16EBAB539D620103DA3D29FC9FA8B2383C4`;
- `onboarding-documents-landscape-1200x628.png` — `B6F99A3591DB2ACE023D2A2039A246553DA3CB5A81E86E5BD67C242D7706A65D`;
- `onboarding-documents-square-1200.png` — `54BAA6835EA4806A941A9D2B55BD166EC4F1FCEF889580F3C1EACBD9FDC672AD`;
- `onboarding-training-log-landscape-1200x628.png` — `F8A114830B8CC1C7E937FC145609144D77AFBACD18B870068650712EC9D22A8F`.

No product image is proposed for any ad group in the completed execution.

Blocker: the signed-in bulk-template dialog provides no image-asset or company-
logo template and therefore no deterministic Preview schema for these assets.
No image/logo Google action is permitted until root confirms this manifest and a
field-level Preview/readback route. Status: `IMAGE_BULK_PREVIEW_SCHEMA_UNAVAILABLE`.

## Explicit exclusions

- All ImageGen outputs are local drafts only and are excluded from this manifest.
- No generated, reinterpreted or dynamically selected logo is proposed.
- No dynamic images, landing-page image scanning or automated asset expansion.
- No Finance, privacy, terms or invented landing destination.
- No fabricated clients, product outcomes, UI state or performance claims.
