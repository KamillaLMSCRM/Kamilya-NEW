# Kamilya Yandex Direct: Kazakhstan launch plan

Date: 2026-08-12
Market: Kazakhstan
First language: Russian (KK is a separate evidence-based decision)
Status: **PREPARED / NO-GO. No Yandex spend authorized. Account access and
Wordstat/Forecast evidence are BLOCKED.**

## 1. Executive status

The Yandex-native plan is fully drafted. Two hard blockers remain before any
launch-gate request:

1. **No signed-in Yandex account access** in this environment (no OAuth token,
   no Direct/Metrica credentials, no browser session, no Yandex env-var names).
   The read-only payer/currency/account audit (Phase 1) cannot be executed.
2. **Wordstat and Budget Forecast are authenticated tools.** Base/refined
   frequencies and forecast budgets (Phase 2) are therefore PENDING, not
   collected. No volume is fabricated in this package.

Approval boundary is unchanged: no payer change, payment, Metrica install,
lead submission, publication, budget top-up, or activation may occur without
an explicit owner instruction.

## 2. Verified platform rules (rechecked 2026-08-12)

These replace the Google-budget wording entirely:

- Budgets for manual-bid campaigns and the shared account are now **weekly**.
  Minimum weekly budget in tenge: **1,300 KZT**.
- With a 3+ day schedule, max daily spend = **35% of weekly budget**.
- Up to **30% of an unused weekly budget rolls over** to the next week
  (pay-per-click; no rollover on the first week; cumulative spend ≤ plan).
- Changing the weekly budget restarts spend: per-click 35% old + 35% new that
  day. Change budgets at the start of a calendar week.
- The unified performance campaign ("Единая перфоманс-кампания") is the current
  type; text-and-graphic ads are editable-only since 2026-06-30 and
  combinatorial ads are the recommended creation path. Verify in the live UI.
- Manual-bid strategy ("Максимум кликов с ручными ставками") is **search
  only**. Bid step in tenge = 1 KZT.
- Expanded geographic targeting is **ON by default** and must be disabled.
- `utm_source=yandex*` can be rewritten to `ya*`; use `utm_source=ya_direct`.
- Kazakhstan legal entities pay in tenge by bank transfer or VISA/MasterCard;
  funds received by ТОО «Y. Izdeu men Jarnama».
- A JS-event goal via `reachGoal` is the Metrica optimization mechanism.

## 3. Proposed structure (draft, not yet built)

One Search-only unified performance campaign:

`KZ | Finance | Search | RU`

| Group | Cluster | Planned status |
|---|---|---|
| AG1 | Knowledge control / employee testing | active (after validation) |
| AG2 | Mandatory / corporate training (proxy) | active with validation cap |
| AG3 | Employee training platform / LMS | active |
| AG4 | Training automation | active |
| AG5 | LMS category (tight negatives) | active |
| AG6 | Finance-vertical validation | **paused** |

Rules:

- Kazakhstan geography only; expanded geo targeting **off**.
- Russian first; KK only with separate Wordstat evidence.
- Search placement only. No Yandex Advertising Network, no auto-targeting in
  the first test.
- Mon–Fri 09:00–19:00 in the confirmed Kazakhstan account timezone. Note:
  Direct statistics/dates are shown in Moscow time even when the campaign
  timezone differs; confirm the schedule renders as intended.
- Initial dates cover ten active business days but are not set until budget and
  launch date are approved.
- Tight `"..."` quoted phrases (fixed word count) plus campaign/group negatives.
  Validate every negative against actual Yandex queries before broad exclusions.
- At least two controlled ad variants per live cluster (see ads CSV).
- No auto-targeting or networks to manufacture volume.

## 4. Two budget / strategy options in KZT

Both options assume: weekly budget is the cap; shared-account budget is the
hard total stop; daily cap 35% of weekly (5-day schedule); no VAT number is
assumed — the account displays VAT treatment and the owner must confirm an
amount in KZT and whether it includes VAT. No Yandex spend is authorized.

### Option A — Conservative: «Максимум кликов с ручными ставками» (search-only)

- Why: zero conversion history; full bid control on low-frequency B2B queries;
  strategy is documented as search-only, matching the first-test scope.
- Weekly budget: **15,000 KZT** (excl. displayed VAT) — about 10× the 1,300 KZT
  minimum, small enough for a controlled first test.
- Daily cap ≈ **5,250 KZT**; possible concentration risk within a day up to the
  35% rule; no carry from week 1 to week 2 except the 30% rollover rule.
- Bid guard: per-phrase manual bid with a cap to be set from authenticated
  Budget Forecast (step 1 KZT). Do not exceed the forecast-recommended bid.
- Conservative maximum exposure before the next manual review: **two calendar
  weeks ≈ 30,000 KZT**, controlled by the shared-account budget; confirm the
  account-level shared budget value and stop at that total.
- Stop/pause rule: pause at 30,000 KZT total or on any mandatory-stop condition
  in Phase 7; never let rollover push cumulative spend above plan.
- Switch to conversion optimization only after: backend-confirmed lead goal
  proven, attributed to Direct via `yclid`/UTM, and meeting the current official
  Yandex recommendation for minimum conversions for «Максимум конверсий»
  (recheck the live strategy page; do not invent a fixed threshold).

### Option B — Moderate: «Максимум кликов» with average-CPC limit

- Why: automatic bid management at campaign level while still pay-per-click and
  needing no conversion history; an average-CPC limit caps cost per click.
- Weekly budget: **30,000 KZT** (excl. displayed VAT).
- Daily cap ≈ **10,500 KZT**; spend can concentrate on high-CTR hours within the
  35% rule; rollover as in Option A.
- Average CPC limit: to be set from authenticated Budget Forecast (step 1 KZT).
- Conservative maximum exposure before the next manual review: **two calendar
  weeks ≈ 60,000 KZT** via shared-account budget.
- Stop/pause rule: same as Option A; tighten or pause if spend concentration
  degrades query quality.
- Switch to conversion optimization only under the same proof rule as Option A.

Recommendation: start with **Option A** (manual, search-only) for the first
high-intent B2B test; Option B is the follow-up if forecast supports volume and
the owner approves a higher cap. Neither is authorized until the owner confirms
amount and VAT.

## 5. Measurement / privacy gate (Phase 4) — gap analysis

Audit of `kml.kz` landing source (`kamilya-landing` repo) performed. Current
state and gaps:

1. **Attribution capture.** Landing `lib/attribution.mjs` captures utm_source,
   utm_medium, utm_campaign, utm_content, utm_term, gclid, referrer,
   landing_page, attribution_captured_at. **Gap: `yclid` is not captured.** Must
   add `yclid` (limit ~200) to sanitization, LeadPayload, lead API schema, and
   the lead proxy route, then persist to lead storage. Test persistence.
2. **Primary conversion.** Existing client event `lead_form_success` fires only
   after backend success (`components/LeadForm.tsx`), which matches the required
   primary conversion contract. **Gap: no Yandex Metrica counter and no
   `reachGoal` call exist.** Metrica counter ownership, counter access, a JS
   event goal `lead_form_success` (reachGoal), and the Direct-Metrica goal link
   must be created. Form open / submit / error remain diagnostic events and are
   never bidding goals.
3. **Deduplication.** Lead storage dedups on (email, company) in a 24h window
   (BRIEF §6). The Metrica goal should fire once per successful backend
   confirmation; the landing currently calls `trackGoogleAdsLeadConversion` once
   per success. Define the same single-fire behavior for Metrica.
4. **Consent.** Google tag loads only after explicit consent and successful
   submit (lib/google-ads.mjs, consent version `privacy-terms-2026-08-10`).
   **Gap: no Yandex Metrica loader exists.** Metrica is a new third party;
   installing it, Webvisor, or form analytics is not authorized by the existing
   Google measurement consent. Privacy copy (RU/KK) must be updated to name
   Yandex Metrica/identifiers if installed, and any production code change must
   be reviewed, tested, released by exact SHA, and smoke-tested.
5. **No PII in analytics.** Current analytics events carry only interest,
   source_section, locale, error_code, plan — no PII. **Requirement:** prove the
   same for Metrica/debug payloads: no name, email, phone, company, document
   text, or free text.
6. **Attribution model.** Landing persists first campaign attribution in the
   browser session and lets a fresh campaign attribution replace it
   (first-touch-in-session; last-fresh-touch wins). Record this explicitly and
   test UTM/`yclid` persistence, failed-submit, and duplicate-submit cases.
7. **Data retention / Webvisor / form analytics.** Decide and document before
   install. Webvisor and form analytics are not implicitly authorized.
8. **Privacy page** (RU/KK) currently mentions GCLID and Google Ads; update for
   yclid/Metrica only if installed, keeping legal boundaries in the landing/
   contract context.

Until 5 and 7 are satisfied and code is deployed by exact SHA, the campaign
cannot start.

## 6. Paused-build and pre-launch QA checklist (Phase 5)

Verified in the live web account, not just an import file:

- [ ] payer / currency / legal entity (ТОО «Document. KZ», BIN 080340022947,
      KZT);
- [ ] Search-only placement; no Yandex Advertising Network;
- [ ] Kazakhstan and expanded-geo **off**;
- [ ] language Russian;
- [ ] timezone and Mon–Fri 09:00–19:00 schedule (Moscow-time display caveat);
- [ ] approved KZT financial limit and shared-account budget;
- [ ] bidding strategy and bid/CPC guard;
- [ ] networks and auto-targeting state off;
- [ ] `"..."` phrase operators and negative phrases;
- [ ] ad/group/keyword status hierarchy (parent paused, AG1–AG5 planned,
      AG6 paused);
- [ ] landing URLs, UTM macros, `yclid` capture;
- [ ] moderation status and policy warnings;
- [ ] Metrica linkage and primary-goal selection (after install approval);
- [ ] exactly one authorized test lead and exactly one recorded goal;
- [ ] no PII in analytics/debug payloads;
- [ ] mobile/desktop landing and form success/error behavior;
- [ ] legal footer, privacy, terms, operator identity, contacts.

Keep the parent paused until all gates pass.

## 7. Correction plan for the blocked account audit (Phase 1)

The owner must provide one of the following so the read-only audit can run:

1. A signed-in Yandex Direct session (owner runs a browser) that the agent can
   inspect read-only; or
2. An approved read-only access/API token scoped to the Direct and Metrica
   accounts; or
3. A manually exported account snapshot (currency, payer, balance, billing,
   timezone, campaigns, counters) from the owner.

The audit then reports, without changing data: registration country; currency
and changeability; payer type; whether ТОО «Document. KZ» / BIN is the payer;
billing method, VAT display, balance, credit/autopay settings; existing
campaigns/counters/goals/grants/agency links/auto-apply/moderation tasks; and
timezone. Any mismatch is only corrected after approval.

## 8. Phase 2 correction plan (Wordstat/Forecast)

When an authenticated session is available:

- Run Wordstat for KZ (By words) for every seed in
  `kz-yandex-wordstat-2026-08-12.csv`, recording base and operator-refined
  frequency, related queries, and dates. Fill the PENDING cells only from real
  output.
- Run Budget Forecast for KZ with the validated phrases, capture impressions,
  clicks, CPC, and spend, and fill `kz-yandex-budget-forecast-2026-08-12.csv`.
- Update decisions (launch / isolated validation / SEO / outbound / reject) per
  cluster; adjust negatives only from actual queries.
- Only then finalize the KZT budget options and request Phase 6 authorization.

## 9. Phase 6 — launch authorization (not requested)

When ready, a single approval request will state: exact campaign name and
account; live paused-state evidence; approved dates/schedule/geography; balance
and max KZT exposure; budget incl./excl. VAT as displayed; active groups and
intentionally paused hypotheses; moderation/advertiser status; conversion test
result; unresolved risks; and the exact activation action. Only an explicit
owner instruction such as `enable the Yandex campaign` authorizes activation.

## 10. Phase 7 — daily operation rules (summary)

- Daily review at 19:10 Asia/Almaty on active business days; read-only until a
  read-only automation task is owner-approved.
- Report campaign state, spend/VAT, impressions/clicks/CTR/CPC/conversions/
  CPL, qualified leads (no personal data), search-query review, cluster/ad/
  device/region/hour performance when sample size suffices, Direct↔Metrica↔
  stored-lead discrepancies, moderation/budget/billing anomalies.
- Mandatory stop/escalation conditions: conversion tracking stops or leads do
  not match Metrica; unapproved charge or pacing breach; serving outside KZ /
  schedule / network; policy/moderation warning; landing/form/API failure;
  predominantly irrelevant queries; automated recommendation changes scope/
  budget/bidding/targeting; personal data in analytics or reports.
- Keep a dated change log (`kz-yandex-change-log.md`).

## 11. Files

- `kz-yandex-demand-2026-08-12.md`
- `kz-yandex-wordstat-2026-08-12.csv` (volumes PENDING)
- `kz-yandex-budget-forecast-2026-08-12.csv` (PENDING)
- `kz-yandex-launch-plan-2026-08-12.md` (this file)
- `kz-yandex-keywords-2026-08-12.csv`
- `kz-yandex-negatives-2026-08-12.csv`
- `kz-yandex-ads-2026-08-12.csv`
- `kz-yandex-utm-matrix-2026-08-12.csv`
- `kz-yandex-change-log.md`

## 12. Sources rechecked 2026-08-12

- Geotargeting: yandex.ru/support/direct/ru/efficiency/geotargeting
- Time targeting: yandex.ru/support/direct/ru/efficiency/timetargeting
- Budget Forecast: yandex.ru/support/direct/ru/impressions/budget-estimation
- Strategies: yandex.ru/support/direct/ru/strategies/select-strategy
- Weekly/daily budget: yandex.ru/support/direct/ru/strategies/day-budget and
  /week-budget
- Manual strategy: yandex.ru/support/direct/ru/strategies/manual-strategy
- Keyword operators: yandex.ru/support/direct/ru/keywords/symbols-and-operators
- URL parameters/macros: yandex.ru/support/direct/ru/statistics/url-tags
- Metrica goals: yandex.ru/support/metrica/ru/general/goals
- KZ payment methods: yandex.ru/support/direct/ru/payments/payment-methods
