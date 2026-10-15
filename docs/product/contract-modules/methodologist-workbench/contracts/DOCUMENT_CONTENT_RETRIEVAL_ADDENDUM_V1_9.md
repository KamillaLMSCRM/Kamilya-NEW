# Document evidence reasoning profile V1.9

DOCUMENT57, 2026-10-15 UTC. Extends V1.8. This is an implementation candidate,
not DEV/browser/production acceptance.

## Observed problem and rejected approaches

R11/3dc completed42 ordinary DEV cases but retained one false conflict: a card
supported its own rule while only referring to an unavailable opposing value.
R12–R18 local experiments did not justify a release. Policy accumulation,
private assessment/position envelopes, a two-call reviewer, and dimension-tagged
facts retained scope leakage or hid a real conflict. Archived outputs, reviews
and source snapshots remain. None was deployed or used to alter original oracles.

The managed DeepSeek client disables thinking by default. Local tests with
thinking/low on the same configured model exceeded8/12-second provider windows;
at45seconds,2000 and4000 generated-token caps ended with `finish_reason=length`
and no valid final answer. With8192 total generated tokens, three named probes
finished normally: authority/record retention, one-card unavailable rival, and
actual3/5-day opposing rules. Independent reviews confirm their bounded meaning.
This is evidence for a changed hypothesis, not a general accuracy guarantee.

## Request-local opt-in

Only document-content answers request `request_profile="evidence_low"`:

| Boundary | Managed provider named `deepseek` | Existing other providers/callers |
| --- | --- | --- |
| Reasoning | `thinking.type=enabled`, `reasoning_effort=low` | Original settings unchanged |
| Generated tokens | At most8192, including reasoning and final output | Original client maximum,2000 for document Q&A |
| Attempt wall-clock | At most45seconds, zero transport retries | Original caller deadline,8seconds for document Q&A |

The profile requires both provider name `deepseek` and the internal
`managed_evidence_profile` capability, default false. Only the global managed
DeepSeek builders set it, including the stored-global-key fallback. Tenant
override construction does not set it even when its display name is `deepseek`.
The profile creates a fresh per-attempt client/config. It never mutates shared
clients, saved routing/order, provider endpoints, model IDs, keys, tiers or reserve
state. A subsequent request without the profile retains the original settings.
Unknown profile values fail before a provider call. Other provider names,
including tenant-specific overrides, do not silently receive DeepSeek parameters.

One logical inference remains; only existing transport-failure fallback is allowed.
There is no semantic retry, critic, syntax repair loop or draft-answer fallback.
The whole document-content operation is bounded to60seconds, including retrieval
and admission; cancellation/refund and the existing durable failure path remain.
Assignment interpretation and other AI consumers retain their original deadlines.

`ModelAnswer` remains the V1.8 private protocol. `DocumentAnswer`, public status
values, citation/source trust,8000-character final answer,24000-character raw JSON,
old histories, roles/RLS and database schema remain unchanged. Reasoning content
is not returned to the caller, persisted, logged or carried into conversation.

## Cost, verification and compatibility

Use the existing provider account and normal `document_content_answer` budget
admission/refund. The2-cent reservation remains an estimate, not a new invoice
cap or a promise of zero cost. No provider spend limit, billing plan, capacity,
resource, voice setting or reserve activation is part of this change.

The three early probes returned9.5–32.641seconds of provider elapsed time and
1384–5440 completion tokens. These are small local application-module samples,
not HTTP, browser, production, human-speedup or SLA measurements. Actual request
metadata confirms the official host and returned `deepseek-flash` model. The
provider documents the configured legacy `deepseek-v4-flash` name as an alias
served by current Flash; do not infer an immutable upstream model snapshot.

References checked2026-10-15: [thinking](https://api-docs.deepseek.com/guides/thinking_mode/),
[API parameters](https://api-docs.deepseek.com/api/create-chat-completion/),
[model aliases/pricing](https://api-docs.deepseek.com/quick_start/pricing/).

Required gates: request-profile RED/GREEN/default-isolation/fallback/no-retry
tests; full API/driver suite; fresh canonical isolated Supabase DEV44checks with
the expanded45-source manifest (LLM client and V1.8/V1.9 included); independent
source/semantic review; full42-case ordinary DEV and browser control; protected
production release, actual runtime/routing/readback and synthetic live acceptance.
Native frontend56/public history compatibility requires separate readback.
