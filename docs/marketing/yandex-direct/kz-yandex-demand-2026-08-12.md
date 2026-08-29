# Kamilya Yandex Direct: Kazakhstan demand research foundation

Date: 2026-08-12
Market: Kazakhstan only
First language: Russian. Kazakh is a separate evidence-based decision.
Status: **PREPARED, NOT AUTHORIZED TO SPEND. Wordstat volumes are NOT yet collected.**

## Executive summary

This document is the Yandex-native replacement of the Google Keyword Planner
hypothesis. It does not copy Google volumes. Wordstat and Budget Forecast are
authenticated tools; the agent currently has **no signed-in Yandex account
access** in this environment, so **no Wordstat base frequency, refined
frequency, or Budget Forecast numbers appear in this file**. Every numeric cell
is marked PENDING and must be filled from a live Wordstat/Budget Forecast
session before the launch plan can be finalized.

The seed set, operator strategy, campaign structure, negatives, ads, UTM
contract, and the two budget options are fully drafted and ready to validate.

## Hard blocker for Phases 1–2

- No Yandex OAuth token, Yandex Direct or Metrica credentials, or signed-in
  browser session are present in this environment.
- No `YANDEX*`/`METRICA*`/`DIRECT*`/`OAUTH*` environment-variable names exist
  in `C:\Kamilya New\Kamilya-NEW\.env`, `kamilya-landing\.env.local`, or the
  process environment (names checked only, values never read).
- Wordstat (wordstat.yandex.ru) and Budget Forecast both require an authorized
  user session; Budget Forecast is documented as "only available to
  authorized users".

Until the owner provides an authenticated Yandex session (or an approved
read-only API token), the account/payer audit and Wordstat/Forecast collection
cannot be executed. The correction plan for this blocker is in
`kz-yandex-launch-plan-2026-08-12.md`.

## Verified official Yandex platform facts (rechecked 2026-08-12)

Source pages were reopened at execution time; the following reflect current
documentation, not memory:

1. **Weekly budgets are now the unit.** Since 2026-06-22, campaigns with manual
   bids and the account-level shared account use weekly (not daily) budgets.
   A set daily value was automatically converted to weekly respecting the
   display schedule. (support/direct/ru/strategies/day-budget.md,
   select-strategy.md, week-budget.md)
2. **Budget rollover.** Since 2026-07-06, in pay-per-click campaigns up to 30%
   of an unused weekly budget can roll to the next week; cumulative spend still
   does not exceed planned budget. No rollover is calculated for the first week.
   (week-budget.md#transfer)
3. **Daily spend cap.** With a schedule of 3+ days, max daily spend is 35% of
   the weekly budget; 2 days → 50%; 1 day → 100%. Minimum weekly budget in
   tenge is **1,300 KZT**. (week-budget.md)
4. **Budget restart spikes.** Changing the weekly budget, payment model, or
   moving the start date restarts spend: for pay-per-click, up to 35% old + 35%
   new that day; for pay-per-conversion up to 100% + 100%. Change budget at the
   start of the calendar week. (week-budget.md#restart-budget)
5. **Current campaign type.** The default performance campaign type is now the
   "Unified Performance Campaign" ("Единая перфоманс-кампания"). Text-and-
   graphic ads in it are editable-only since 2026-06-30; combinatorial ads
   ("комбинаторные") are the recommended creation path, and existing text-and-
   graphic ads are being migrated from 2026-07-14. The agent must verify the
   exact campaign type and ad format in the live interface before building.
   (manual-strategy.md)
6. **Strategies available for the unified performance campaign:**
   - «Максимум конверсий» (pay-per-conversion, CPA),
   - «Максимум кликов» (pay-per-click, with optional average-CPC limit),
   - «Максимум кликов с ручными ставками» (manual bids, **search only**),
   - «Максимум прибыли».
   Manual-bid strategy is search-only and no longer supported for networks.
   (select-strategy.md)
7. **Bid step in tenge: 1 KZT.** (manual-strategy.md)
8. **Strategy restart rules.** Changing strategy, spend limit, payment model,
   or pausing >7 days restarts learning. If a strategy was stopped >28 calendar
   days its statistics are reset. (select-strategy.md#restart)
9. **URL parameters / UTM.** `{keyword}`, `{campaign_id}`, `{ad_id}`, `{gbid}`,
   `{phrase_id}`, `{device_type}`, `{position_type}`, `{position}`,
   `{region_id}`, `{source_type}`, `{source}`, `{yclid}` are the dynamic
   Direct parameters. Cyrillic values in URLs are UTF-8 encoded; if the final
   URL exceeds 4096 bytes, only `yclid` and `openstat` are passed.
   (statistics/url-tags.md)
10. **utm_source rewriting.** Yandex may rewrite a `utm_source` value beginning
    with `yandex` to `ya` (e.g. `yandex_direct` → `ya_direct`). This is a real
    risk to the required contract value `utm_source=yandex_direct`. Mitigation
    options are listed in the UTM matrix; the safe default is
    `utm_source=ya_direct`.
11. **Expanded geographic targeting is ON by default** in campaign advanced
    settings and must be explicitly turned off for the first high-intent B2B
    test. (efficiency/geotargeting.md)
12. **Time targeting.** Schedule is set per campaign, with country+timezone
    selection; Kazakhstan public-holiday handling is supported. Minimum total
    scheduled time is 8 hours/week. Statistics and campaign dates are always
    shown in Moscow time even when a different campaign timezone is selected.
    (efficiency/timetargeting.md)
13. **Kazakhstan payment methods.** Kazakhstan legal entities can pay in tenge
    by bank transfer or VISA/MasterCard; funds are received by
    ТОО «Y. Izdeu men Jarnama». (payments/payment-methods.md)
14. **Metrica goals for optimization.** A JS-event goal via `reachGoal` is the
    mechanism; counter owners can enable "Разрешить в рекламных кампаниях
    оптимизацию по целям без доступа к счетчику". (metrica goals.md)

These facts make the original Google-style "average daily budget $5 / campaign
total $70" wording invalid for Yandex: the correct control is a **weekly budget
in tenge**, a schedule-dependent daily cap, a 30% rollover, and an account-level
shared budget as the hard total stop.

## Seed set for Wordstat collection (RU, then KK)

Cluster seed phrases to enter into Wordstat (By words tab), Kazakhstan region,
with the `+`/`!`/`"` operators applied per phrase. Volumes are PENDING:

1. Knowledge control and employee testing
2. Mandatory/corporate employee training
3. Employee-training platform / LMS
4. Training automation
5. Finance-vertical validation (expected low volume, kept paused)

Full candidate list with operators: `kz-yandex-keywords-2026-08-12.csv`.

Kazakh natural variants to research with a fluent-language pass (not
word-for-word translations), and only launch if Wordstat evidence supports a
separate KK campaign:

- қызметкерлерді оқыту (обучение сотрудников)
- қызметкерлерді тестілеу (тестирование сотрудников)
- қызметкерлерді оқыту жүйесі (система обучения сотрудников)
- қызметкерлердің білімін тексеру (проверка знаний сотрудников)
- корпоративтік оқыту (корпоративное обучение)
- жеке құрамды оқыту (обучение личного состава — domain check required)

Expectation from Google evidence: most KK formulations were 0–10/month; do not
create a paid KK campaign merely because `/kk/finance` exists.

## Collection protocol (to run when access is available)

For every candidate phrase save:

- exact phrase (with operator variant);
- language;
- country/region (Kazakhstan; optionally KZ regions — Almaty, Astana, etc.);
- date and research period (e.g. month, last 12 months);
- Wordstat base frequency and operator-refined frequency where available;
- related-query evidence (left/right columns);
- Budget Forecast impressions/clicks/CPC/spend where available;
- intended audience/problem;
- intent class: commercial / informational / hiring / education-consumer /
  ambiguous;
- decision: launch, isolated validation, SEO/content, outbound/ABM, reject;
- source URL or exported artifact.

Never fabricate, interpolate, or sum overlapping query volumes. Label every
proxy, missing cell, grouped variant, and zero/low-volume hypothesis clearly.

## Competitor/ads scan

Inspect current Yandex search results and live Direct examples for message
patterns only. Do not copy competitor wording and do not make claims from
competitor ads.

## Files in this package

- `kz-yandex-wordstat-2026-08-12.csv` — collection template, volumes PENDING.
- `kz-yandex-budget-forecast-2026-08-12.csv` — forecast template, PENDING.
- `kz-yandex-launch-plan-2026-08-12.md` — structure, budget options, gates.
- `kz-yandex-keywords-2026-08-12.csv` — keywords with Yandex operators.
- `kz-yandex-negatives-2026-08-12.csv` — candidate negative phrases.
- `kz-yandex-ads-2026-08-12.csv` — RU ad variants (two per cluster).
- `kz-yandex-utm-matrix-2026-08-12.csv` — attribution contract.
- `kz-yandex-change-log.md` — dated change log.

## Decision

No launch approval is requested. Deliverables 1 (payer/currency facts) and 2
(sourced Wordstat/Forecast evidence) cannot be produced without an authorized
Yandex session. See the launch plan for the exact correction plan.
