# Runtime configuration review disposition V1

Accepted by root 2026-10-16; additive clarification of EPIC_V1/MODULE_RUNTIME_V1, no owner authority expansion. Independent source review identified five points:

1. Shared public audit downgrade is forbidden in0182; owned isolated test schemas alone may exercise downgrade. Binary rollback retains tables/history.
2. Immutable snapshot consistency applies to the hot-settings bundle, not two independently owned policy stores. Existing generation_model_routing keeps its own validated revision/readiness. An operation may sample its enabled order and settings revision separately, just as tenant BYOK/key rotation were already independent. No API claims atomic multi-store updates; no combined write or automatic activation is introduced.
3. History before/after overrides are validated with the closed catalog before returning. Read failures receive safe503, no raw DB/value/exception text.
4. BYOK endpoint/model/key/config remain tenant-owned. Operation-level time/token ceilings intentionally apply to all callers, including BYOK, as existing operation safety policy already did. Global provider overrides never replace BYOK configuration.
5. DeepSeek/Qwen/GLM model identifiers are syntactically validated, operator-selected and not availability-guaranteed; save performs no model request and changes no endpoint/auth/paid plan. Unsupported names can cause ordinary provider failure/failover. UI must state this and preserve rollback. Current connector accepts only Luna, so its choice is fixed until connector protocol support changes. Embedding names are excluded because changing their space needs reindexing.

No claimed additional runtime acceptance. Add tests for all corrected behavior and retain independent review findings as design inputs, not runtime proof.
