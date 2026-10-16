# Draft date follow-up context V1.7

Accepted bounded prompt-contract repair,2026-10-16. Root owns implementation,
integration and DEV deployment; independent reviewer owns review. Owner explicitly
permits DEV checks only; production and ASUS remain untouched. Extends V1.6 without
changing public API, schema, model route, retry, budget or execution guards.

Owner's subsequent exact request extends DeepSeek's assignment-only attempt to30s.
Keep ChatGPT40s/default8s and increase the overall provider-resolution/chain cap to90s
so the reserve retains its budget after a30s primary wait. No other consumer or
provider HTTP configuration changes. Virtual-clock regressions must prove a20s
healthy DeepSeek is not prematurely failed over, primary30s+reserve26s succeeds,
and primary30s+reserve39s is not starved by the earlier60s cap. The actual DEV
API-only expiring probe now uses the same date-only history input, a35s loopback
hang to exercise the real30s primary wall cap, and a95s acceptance guard. Both
permitted providers must retain exact names/date/options and accounting deltas;
the ephemeral route still excludes ASUS. This supersedes V1.6 timing only under
the owner's new explicit30s request; no global policy or automatic retries.

## Defect and compatible change

Root's real DEV browser run on c7d4cf3a received intent_clarification for a date-only
follow-up even though instruction_history contained the explicitly named course
and department. A complete instruction succeeded. The prompt had competing rules:
use draft user history, but corrections may modify only a previous candidate.
No saved previous_candidate exists during pre-preview draft clarification.

The internal USER JSON now distinguishes context_source current_instruction,
user_instruction_history and owned_previous_candidate. The existing owned-plan
path still excludes client history on the server. Add a textual-only
latest_instruction_has_absolute_date hint; it does not validate a calendar date
or authorize any action. Raw bounded history remains unmodified untrusted USER
data, never interpolated into SYSTEM policy or treated as assistant facts.

SYSTEM policy explicitly permits completion of the draft from user history with
no saved plan, retains an explicitly named course/department on a date-only turn,
and lets a new absolute deadline replace earlier relative wording without guessing
that older relative date. Missing/ambiguous combined fields still clarify. A small
synthetic example explains the operation, not a hidden default resource mapping.
There is no server-side semantic output repair, name extraction, guessed identity,
additional inference, automatic retry or new conversation store.

## Negative space and gates

All calendar/future/timezone/output validation, history bounds, subgroup rejection,
server-owned previous-plan isolation, explicit preview/confirmation, tenant/RLS,
budget/refund and cancellation remain unchanged. New metadata does not override
those checks. The current-only case cannot invent prior names, newer explicit
resource changes still override history, and a date cannot silently discard a
previous unsupported audience filter. No document/lesson dialogue changes.

Deterministic prompt/application regressions prove the context contract, not
real-model comprehension. Preserve the earlier failed real scenario and any fresh
baseline. Focused neighbors/one full risk suite/quality/exact CI precede the same
existing Free DEV API/worker deployment. Live normal API and browser must pass the
original RU follow-up, a date-only message with no names, and a KK equivalent,
plus missing-context/relative-date/subgroup regressions. No plan confirmation or
new domain fixture is required; reuse the exact existing synthetic QA course and
actors, verify enrollment state unchanged. No production release or ASUS call.
