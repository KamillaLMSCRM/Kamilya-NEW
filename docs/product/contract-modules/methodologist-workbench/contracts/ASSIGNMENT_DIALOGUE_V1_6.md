# Assignment reserve timing V1.6

Accepted bounded extension, 2026-10-16. Root owns the shared interface and
integration; independent reviewer owns review only. Current owner authorizes DEV
repair and real synthetic assignment acceptance, not production or ASUS access.
Supersedes V1.4 timing only; V1.5 lookup and all other authority guards remain.

## Outcome and evidence

Actual DEV private ChatGPT returned tiny JSON in16.349s (earlier API parent) and
25.538s (current worker). These are connectivity observations, not an SLA.
The real intent application replay with a virtual clock reproduces cancellation
at16s for a hanging8s primary and26s reserve: the uniform8s cap is insufficient;
the old outer30s cap also cannot accommodate that sequence.

## Compatible interface delta

Only assignment interpretation uses an outer60s wall-clock cap (including factory
resolution), default8s per provider, and40s for the resolved client named
`chatgpt-reserve`. It does not insert or enable a provider. Existing route order,
tenant BYOK, output1200tokens, single attempt, admission/refund and semantic
validation remain unchanged. Total cap can cut a later attempt; it is never reset
per provider. No background completion, hidden repair or semantic failover.

`ResilientLLMClient.ainvoke` adds an optional keyword-only
`provider_deadline_overrides: Mapping[str, float]`. Overrides require the existing
positive default deadline. Validate finite positive non-boolean values and nonempty
string names before calls; snapshot the map, select exact existing client names,
and clone bounded attempts with zero retries. Unmatched names do not add providers.
Calls without this option retain behavior, including the document evidence profile.
External cancellation propagates; caller and shared provider objects stay unchanged.

Frontend assignment uses normal axios transport without an explicit shorter cap;
live DEV browser execution must qualify the complete network path. No new frontend
protocol, schema, API route, provider/configuration, billing or resource change.

## Impact and gates

Root writes llm_client.py, intent_application.py, focused regressions and canonical
documentation. Shared-client regressions must cover unchanged defaults/evidence
profile, validation, cancellation, retry suppression, bounded exhaustion and tenant
single-provider isolation. Intent regressions cover real fallback parsing, budget
settlement, no semantic retry and no assignment side effects. One full risk suite
plus exact CI precedes controlled deployment to existing DEV Free API/worker.

Real forced-primary failure must be invocation-local on synthetic DEV inputs,
never a saved bad endpoint. Limit the ephemeral probe to DeepSeek/ChatGPT so it
cannot contact owner-deferred ASUS. Preserve content-free durable receipts, then
remove exact temporary opt-in settings/claims. Full ordinary-methodologist browser
journey requires clarification/correction, editable authoritative preview, explicit
confirmation, receipt/reload, deduplication and learner access on owned QA data.
No production, voice, ASUS, new paid service or global route mutation is allowed.
