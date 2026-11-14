# Editor chat history V1.5 — marker-only response acknowledgement

Accepted by Root 2026-10-14 from the owner-authorized real DEV acceptance.
Amends V1.4 without changing request/schema/history budgets or action authority.

DEV49 at 0d186cd3 produced a valid selected-lesson proposal with no explanatory
prose; the API's Russian `(пустой ответ)` fallback was misleading although the
proposal and follow-up context worked. For such a valid selected-target, nonempty,
bounded proposal only, return a short RU/KK/EN acknowledgement inviting review
before manual application. Never assert that the lesson was changed. A foreign,
course-level, empty or oversized marker must not receive apply authority or this
acknowledgement. Preserve the existing fail-closed screening of every originally
emitted reply/proposal/title field and replay eligibility.

No additional provider call, automatic rewrite/application, database migration,
durable dialogue, role/tenant bypass, flag, resource or provider-tier change.
Require marker-only language regressions RED then GREEN, existing policy/history
neighbors and fresh exact-SHA DEV/production gates. The model's response to an
exact sentence-count instruction remains a reviewed probabilistic quality result,
not a new guaranteed formatter contract.


## Proposed complete-context addendum — 2026-11-14 / assistant111

Same endpoint, authoring roles, tenant/actor history, untrusted-history admission,
selected-lesson marker and source-checked correction authority. No new mutation
or publication authority. Load complete owned lesson text and quiz cards, authored
keys/explanations as untrusted claims, and course-pinned approved working text as
source evidence. Never silently substitute a newer source for a bad/missing pin.
Unavailable editions produce an explicit server notice; no full-source pass may
be claimed. Native provider context limits remain authoritative; no local input clipping
is permitted. Incomplete model output returns422 without an applicable partial proposal.
Use the existing generation.editorial_luna_max_tokens budget for compatible editorial
replies without new database keys or migrations. History budgets
and existing proposal/application size constraints remain unchanged. No schema,
provider plan/order or customer-course mutation. LOCAL regressions and real DEV /
production model acceptance are separate gates; current delivery pending.
