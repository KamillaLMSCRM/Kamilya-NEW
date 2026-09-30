# Kamilya: isolated Google Ads LMS-platform pilot — 2026-09-30

## Owner decision and boundary

The owner approved launching a **separate USD 10** test for the broad category
intent `LMS платформа`, additional to the existing HR package. No top-up or
change to `KZ | HR | Search | RU` or `KZ | B2B LMS | Search | RU` was authorized.
The pilot uses Google Ads' non-shared **campaign total budget**, not a USD 10
average daily budget.

The execution used a one-off fail-closed operator package with SHA-256
`2EAC371B8A63C11BC6A8749A9CAB1F616DE5AC31547885E7B96E841B01BFC16E`.
The package contained no credential values and did not implement activation.
It is intentionally not retained as a reusable repository script; this document
is the durable sanitized readback.

## Exact provider readback — 2026-09-30 12:46 GMT+05

- Account: Kamilya `5305432295`, USD, `Asia/Almaty`; auto-tagging enabled.
- New campaign: `KZ | LMS platform | Search | RU | Oct 2026 pilot`, ID
  `24303981023`, **ENABLED**. Google normalized its start to
  `2026-09-30 12:39:58`; end `2026-10-07 23:59:59`.
- Budget ID `15912198888`: `CUSTOM_PERIOD`, total **USD 10.00**,
  `explicitly_shared=false`, daily amount USD 0.00. Initial cost USD 0.00.
- Search / Google Search only; Search Partners and Display off; AI Max off;
  text asset automation opted out. Kazakhstan (`2398`), Presence only;
  Russian (`1031`); Mon–Fri 09:00–19:00, account GMT+05. Maximize Clicks
  (`target_spend`) with CPC ceiling USD 2. EU political advertising: No.
- One enabled ad group: `AG1 | LMS platform exact`, ID `203366289729`.
- One enabled exact keyword: `[LMS платформа]`, criterion ID `2524250500004`.
- One enabled RSA, ad ID `826456543804`, 10 headlines and 4 descriptions.
  Its final URL is
  `https://www.kml.kz/ru?utm_source=google&utm_medium=cpc&utm_campaign=kz_lms_platform_search_ru&utm_content=ag1_rsa_a&utm_term={keyword}`.
  The live URL with encoded ValueTrack placeholder returned HTTP 200 and
  exposed the LMS, demo, and trial copy.
- At the immediate readback, the RSA's primary status was **PENDING** with
  `AD_GROUP_AD_UNDER_REVIEW`; policy approval status was `UNKNOWN`, with no
  policy topics reported. Zero impressions, clicks, and cost. **Enabled is not
  evidence of serving** until review completes.
- Existing campaigns remained: HR **ENABLED**, USD 5/day, USD 12.41 cost
  since 2026-09-21 as of this readback; B2B LMS **PAUSED**. Neither was edited.

## Execution and measurement

The exact 12-object paused package passed Google Ads `validate_only` and was
created in one atomic request. Campaign, group, keyword, and RSA were read back
as paused, then those four statuses alone passed `validate_only` and were
enabled in one atomic request. Post-apply readback confirmed all four enabled
and all budget/targeting controls unchanged. No test lead was submitted.

The homepage attribution code passes current UTM/GCLID into a successful demo
lead payload and passes UTM/GCLID to trial registration; local attribution,
trial-link, and analytics tests passed. This is **code/test evidence**, not a
new provider-side end-to-end lead test. The Ads account still has only the
enabled conversion action `Kamilya | Finance lead form`; a generic homepage
demo may be reported under that legacy name, and a completed trial is not a
separately confirmed Ads conversion. Evaluate the pilot through search terms,
actual demo/trial evidence, and Ads processing separately.

The existing `kamilya-usd-25-2` heartbeat was updated to monitor HR through
October 4 and this new pilot through October 7, without authority to alter the
pilot's budget, assets, targeting, or status. The provider-side USD 10 total
budget is the spending boundary; do not substitute the HR package's USD 25
operational limit for it.
