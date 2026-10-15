# Assignment intent transport deadline V1.4

Status: Accepted for bounded repair, 2026-10-15.
Supersedes: V1.3 only for per-provider transport timing; all authority, history,
preview, execution, schema, billing and live release obligations remain.
Approved by Root under the owner's current repair/DEV/production request.

DEV52 twice returned `intent_provider_unavailable` after approximately30seconds,
without an assignment. Sanitized browser/server receipts are retained. DeepSeek's
official status page reported an ongoing partial API outage. The existing first
provider can wait120seconds, while the entire intent operation is limited30seconds;
an unresponsive primary therefore starves the already-approved transport fallback.
Factory resolution from the canonical DEV settings completed in2.907seconds in a
separate read-only probe; this is not proof of exact server-side phase latency.

Keep the outer30second deadline, output1200token ceiling, admission/refund rules,
provider/model order, tenant BYOK isolation and explicit human confirmation.
Only assignment-intent invocation opts into an8second **wall-clock** deadline
for each provider through a keyword-only `ainvoke` argument. Each bounded attempt
uses a cloned one-attempt provider client. HTTP inactivity
timeouts alone do not bound a provider that sends keepalives. No shared config or
existing unbounded caller is mutated. Cancellation must propagate, not trigger
failover. A transport timeout may reach the next provider in the existing enabled
route; invalid semantic/JSON output must never cause another provider call.

The reusable invocation seam validates finite positive deadlines, preserves exact
route credentials/models/endpoints/order, suppresses provider retry overrides in
the bounded clone only, and uses existing sanitized failover logging. No parallel
race, new endpoint/model/provider, routing/configuration write, budget bypass,
schema change or additional observability service is introduced.

Required deterministic regressions: hanging primary reaches existing fallback;
all hanging providers terminate; external cancellation propagates without fallback;
invalid semantic response is not retried; bounded clone preserves original config
and default behavior; invalid deadlines reject before calls; actual intent factory
uses8seconds and actual admission/application path can interpret fallback output.
Then repeat real DEV dialogue/confirmation/reload/learner acceptance before prod.
