# Editor chat history V1.1 — refusal admission

Status: Accepted by Root 2026-10-14 before repair.
Amends EDITOR_CHAT_HISTORY_V1.md; all bounds/ownership/exclusions remain active.
Reason: API and UI regression each RED proves that a successfully returned scope
refusal otherwise becomes a completed historical pair. A subsequent legitimate
question is then refused again by historical screening, poisoning the session.

Compatible local/public seam: AIChatResponse adds history_eligible: bool=True.
Current-message/history refusal and unsafe-output refusal return False. This is
only admission metadata, never an accuracy, grounding or execution certificate.
Client retains a refusal in visible messages, but adds no completed history pair
when history_eligible is False. Missing field retains old-client/old-server
compatibility. Accepted exchanges remain subject to all later history validation,
redaction/refusal and current server scope checks.

Root additionally owns AIChatResponse and new refusal admission tests, plus the
ERRORS.md recurrence entry. No other scope expansion. False refusal admission
must pass API and UI regressions and ordinary follow-up tests; existing output
and selected-target policy tests remain mandatory. This addendum does not grant
release, inference, DB or provider mutation authority. V1 is preserved unchanged.
