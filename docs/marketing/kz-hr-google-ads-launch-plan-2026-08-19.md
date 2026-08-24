# Kamilya Kazakhstan HR Search — paused import plan

Date: 2026-08-19  
Owner scope: employee onboarding and candidate assessment  
External mutation boundary: import/create all new objects paused; no activation or budget increase

## Purpose

Prepare one isolated Russian-language Search campaign for two distinct B2B intents:

1. employee onboarding and adaptation after hire;
2. candidate knowledge assessment before hire.

The existing `KZ | B2B LMS | Search | RU` campaign remains unchanged. The new
campaign does not inherit or extend its spend authority.

## Hierarchy and statuses

- Campaign: `KZ | HR | Search | RU` — **PAUSED**.
- `AG1 | Employee onboarding` — **PAUSED**.
- `AG2 | Onboarding platform` — **PAUSED**.
- `AG3 | Candidate assessment` — **PAUSED**.
- `AG4 | Candidate testing platform` — **PAUSED**.
- 24 keywords — **PAUSED**, exact/phrase only.
- 8 responsive search ads — **PAUSED**.
- 28 campaign negatives and 12 ad-group cross-negatives.

No object in this package is authorized to serve or spend.

## Campaign settings for paused creation

- Type: Search only.
- Search Partners: off.
- Display expansion/network: off.
- Location: Kazakhstan.
- Location option: Presence — people in or regularly in Kazakhstan.
- Language: Russian.
- Schedule: Monday–Friday, 09:00–19:00, account timezone GMT+05 Kazakhstan.
- Bid strategy candidate: Maximize Clicks.
- Maximum CPC candidate: USD 2.
- Auto-tagging: preserve account-level enabled state.
- Auto-apply recommendations: off.
- AI Max: off.
- Performance Max: not used.
- Broad match: not used.
- Start/end dates: leave unapproved for activation; choose a fresh future window
  only after the activation decision.

If Google Ads requires a budget object for paused creation, configure a proposed
USD 5 average daily budget but keep the parent campaign paused. This creates no
current spend authority. Activation would require a fresh reallocation decision
inside the owner's USD 50 hard cap.

## Budget impact and activation gate

Fresh live readback on 2026-08-19: the existing campaign had spent USD 12.85
of its USD 50 total budget, leaving USD 37.15. This value is time-sensitive and
must be refreshed immediately before any activation proposal.

While the new campaign is paused:

- spend impact: USD 0;
- current USD 50 hard cap: unchanged;
- prepaid top-up: not authorized;
- existing campaign budget/status: unchanged.

The new campaign must not be enabled while the existing campaign can still spend
against its USD 50 total unless the owner approves an exact reallocation and the
combined maximum is technically controlled. A nominal daily budget is not an
account-level hard cap.

## Landing and message match

- Onboarding ads: `https://www.kml.kz/ru/onboarding`.
- Candidate ads: `https://www.kml.kz/ru/candidate-assessment`.
- Production release SHA: `add197f14264d64f65a5ec1760ef7862cfdc2f04`.

Both pages have localized canonical/hreflang metadata, sitemap entries and demo
lead CTAs. Onboarding leads carry `plan=employee_onboarding`; candidate leads
carry `plan=candidate_assessment`.

Candidate messaging is limited to knowledge/skills assessment. It does not claim
background checks, psychometrics, legal validity, objective hiring, automated
hiring decisions or guaranteed hiring outcomes.

## Conversion and product gates

- Tag Assistant dispatch for the existing finance lead-form event was previously
  verified by an authorized test.
- Google Ads attributed conversions remain a separate measurement question.
- The current conversion action name is finance-specific; do not optimize the HR
  campaign against it until reporting separation is explicitly approved.
- Candidate-assessment is implemented in production and its public campaign
  landing is live. The controlled KZ production E2E passed: campaign
  create/activate, protected link/PIN, consent exchange, deterministic
  score/pass, manager result/CSV, staff isolation and cleanup with no residual
  data were verified. The retention timer is enabled and active, and its last
  recovery completed successfully.
- Candidate groups remain paused because advertising activation, budget
  allocation and HR conversion strategy still require separate owner/root
  approval; the hold is no longer a product-readiness or E2E gate.

## Paused-import verification checklist

- [ ] Campaign name is exact and campaign status is paused.
- [ ] Four ad groups exist and all four are paused.
- [ ] 24 keywords exist: 12 exact and 12 phrase; all paused; no broad.
- [ ] Eight RSAs exist and all are paused.
- [ ] Onboarding ads use only `/ru/onboarding` URLs.
- [ ] Candidate ads use only `/ru/candidate-assessment` URLs.
- [ ] Every RSA URL contains `utm_source`, `utm_medium`, `utm_campaign`,
  `utm_content` and `utm_term={keyword}`.
- [ ] Search Partners and Display are off.
- [ ] Kazakhstan Presence targeting and Russian language are set.
- [ ] Monday–Friday 09:00–19:00 GMT+05 schedule is set.
- [ ] No existing campaign, ad group, keyword, negative, ad, budget or conversion
  setting changed.
- [ ] New campaign reports zero spend after creation.

## Activation boundary

ROOT REVIEW REQUIRED before enabling the campaign, any ad group, keyword or ad;
before choosing dates; before accepting a budget impact; before changing the
conversion goal; or before submitting another lead.

## Owner-approved controlled optimization, 2026-08-24

The owner authorized a bounded optimization pass for the live
`KZ | HR | Search | RU` campaign. This authorization is limited to six verified
HR sitelinks, existing traceable Kamilya brand/product image assets, and targeted
headline improvements for the Google-identified AG1 and AG4 responsive search
ads. AG3 remains unchanged.

The following controls remain fixed: USD 5 average daily budget, USD 2 CPC cap,
current campaign dates and statuses, Maximize Clicks, Kazakhstan Presence only,
Russian, Monday-Friday 09:00-19:00 GMT+05, Google Search only, Search Partners
off, Display off, dynamic images off, Customer Match unused, and the existing six
exact keywords retained. No top-up is authorized.

Every Ads batch must use the current signed-in Google Ads schema and follow:
canonical artifact and SHA-256 -> Google Preview -> field-level readback -> one
Apply -> immediate live readback. Stop on any error, warning, URL mismatch,
unexpected Add/Remove/Replace classification, policy ambiguity or control drift.

The 2026-08-24 read-only conversion checkpoint still showed
`Kamilya | Finance lead form` as inactive/unverified with no observed web pages
and 0 Ads-attributed conversions. This is a Google Ads processing/status result,
not a negation of the previously verified Tag Assistant event dispatch and not
evidence of real-click attribution. No additional test lead was submitted and no
tracking setting was changed.

Generated image drafts are explicitly outside this authorization and must never
be uploaded, previewed or applied. Sitelinks and image/logo assets require an
exact traceable manifest and root scope confirmation before any Google action.

## Execution outcome, 2026-08-24

The approved RSA batch was applied exactly once. Terminal execution ID
`422195574876737289` reported exactly two successful Edit operations and zero
errors, limited to AG1 and AG4:

- Ad `821419453636` in AG1 added only H9 `Онбординг новых сотрудников`, H10
  `Адаптация новых сотрудников` and H11 `Маршрут новичка по роли`;
- Ad `821419453654` in AG4 added only H9 `Тестирование при найме`, H10
  `Проверка знаний кандидатов` and H11 `Оценка по требованиям роли`.

Immediate live readback confirmed both exact Ad IDs remained Enabled/Eligible;
H1-H8, D1-D4, paths and Final URLs/UTMs were preserved; no duplicate ad was
created; campaign controls did not drift. AG3 was not included and remained
unchanged.

Exactly six manifest sitelinks were then created sequentially, one Save per
object, at Campaign level for `KZ | HR | Search | RU` only:

- `Возможности онбординга`;
- `Как проходит онбординг`;
- `Демо онбординга`;
- `Возможности оценки`;
- `Как проходит оценка`;
- `Демо оценки кандидатов`.

Each pre-save readback matched the approved text, descriptions, live HR-page
destination, anchor and UTM mapping. Each post-save row was Enabled and Under
review. No warning, duplicate, URL rewrite, automated recommendation,
account-level association or association with `KZ | B2B LMS | Search | RU` was
observed.

Product screenshot derivatives and generated image drafts remained excluded and
were not uploaded. The approved logo candidate remains:
`docs/marketing/google-ads-assets-2026-08-24/kamilya-logo-mark-1200.png`, size
54,432 bytes, SHA-256
`4EEAC7A634B7C5A2EB316BC150B78D75CB12E4100CBEEBB7FF518537326CA1B1`.
Google showed a deterministic HR Campaign-level association, but the available
Chrome control surface did not expose a supported deterministic local-file
selection operation. Classification: `LOGO_FILE_INPUT_ROUTE_BLOCKED`. No logo
file was selected, uploaded or saved.

The conversion action `Kamilya | Finance lead form` remained Inactive/Unverified
with 0 Ads-attributed conversions. No additional test lead was submitted and no
GTM, consent, conversion-action, attribution or other tracking setting was
changed.

Controls remained unchanged: HR campaign Enabled; B2B campaign Paused; USD 5/day
HR budget; Maximize Clicks; USD 2 CPC cap; 19-25 August 2026 dates; Kazakhstan
Presence only; Russian; Monday-Friday 09:00-19:00 GMT+05; Google Search only;
Search Partners, Display, AI Max, dynamic/automated assets, text optimization and
Final URL expansion off; 24 HR keywords retained.

Time-sensitive snapshot observed on 2026-08-24 at approximately 09:59 GMT+05:
HR had 76 impressions, 3 clicks, USD 4.68 spend and 0 conversions; paused B2B
history had 226 impressions, 9 clicks, USD 16.53 spend and 0 conversions; the
combined campaign spend shown was USD 21.21. These figures must be refreshed
before any later pacing or budget decision.

Readiness is `PARTIALLY READY`: the RSA edits are live and the six sitelinks are
awaiting Google policy review; the logo remains blocked only by the deterministic
file-input route. The next safe action is a read-only policy/status check for the
two edited RSAs and six sitelinks, followed by normal read-only spend, search-term
and conversion monitoring.

## Company logo execution outcome, 2026-08-24

The previous `LOGO_FILE_INPUT_ROUTE_BLOCKED` state was resolved after the
supported Chrome file-chooser API became available. With fresh owner
confirmation at the final publication gate, exactly one existing Kamilya
site-derived logo was uploaded and saved:

- source file:
  `docs/marketing/google-ads-assets-2026-08-24/kamilya-logo-mark-1200.png`;
- dimensions: 1200 x 1200 pixels;
- size: 54,432 bytes;
- SHA-256:
  `4EEAC7A634B7C5A2EB316BC150B78D75CB12E4100CBEEBB7FF518537326CA1B1`;
- provenance: deterministic export of the existing Kamilya website mark, not
  generated imagery.

The pre-save Google Ads form readback showed association level `Campaign` and
the exact campaign `KZ | HR | Search | RU`. The alternative `Account` level was
visible but not selected. Visual preview confirmed that the K mark was complete
and not materially cropped or distorted. The object picker contained one
selected logo and the two required Save operations were each performed once.

Immediate live association readback showed exactly one company-logo row:

- asset type: Company logo;
- destination: `KZ | HR | Search | RU`;
- level: Campaign;
- resource state: Enabled;
- policy state: Under review;
- added by: Advertiser;
- Google Ads last-update timestamp: 24 August 2026, 12:48 GMT+05;
- table count: 1 of 1.

No account-level or `KZ | B2B LMS | Search | RU` logo association was created.
No product screenshot or generated image was uploaded. No RSA, sitelink,
keyword, GTM, conversion, budget, bid, date, status, network, geo, language or
schedule setting was changed during this logo operation.

Readiness remains `PARTIALLY READY` until Google completes policy review of the
new logo and the six sitelinks, and until the separately documented conversion
processing issue is resolved. The next action is read-only policy/status and
conversion monitoring; no additional creative or tracking mutation is implied.
