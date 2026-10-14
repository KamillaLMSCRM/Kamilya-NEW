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
