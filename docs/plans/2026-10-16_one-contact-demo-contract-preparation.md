# One-contact demo: contract preparation

Status: DRAFT_FOR_OWNER_REVIEW; no implementation or publication approval claimed.
Date: 2026-10-16.
Source: landing marketing/requirements-2026-10-16/ТЗ-01-Демо-через-один-контакт.md.
Root: Codex /root. Product owner: Askar. Independent source inventories: demo and
learning audit agents. Accepted implementation contract and reviewer: not assigned.

This temporary plan owns preparation, not a second product specification. Before
implementation, freeze a compact versioned epic contract under the V2 standard
(ADR-0024/0025); do not treat this draft as an accepted mini-spec.

## Verified starting point

- Existing landing form and LMS public lead API require name, company and email;
  preserve that B2B personal-show contract and its callers.
- Public `/login/example` is an interactive example, not the demo cabinet.
- `/login/demo` already offers methodologist and student demo roles.
- Current public landing is not the dirty campaign-relaunch checkout. Preserve
  unrelated redesign files; do not publish that checkout incidentally.
- Existing contact success emits a finance-lead conversion. The new demo flow
  must not emit it or count a demo contact as a personal-show request.
- CodeGraph preparation was NOT_READY for current source. The source inventory
  used bounded direct inspection, not graph completeness or runtime assumptions.

## Proposed business seam (not frozen)

`Landing demo CTA -> save_demo_access -> durable platform-owned contact -> opaque
transition -> existing demo role picker -> existing demo login`.

The demo-access owner concentrates validation, consent, idempotency, durable
ownership, transition lifecycle and notification intent. HTTP handlers and UI
remain adapters. Do not make one business module per endpoint or screen.

Proposed request: `attempt_id`, `contact_channel` (`email|whatsapp`), one
`contact_value`, `locale`, allowlisted `source_section`/attribution and current
`consent_version`. Explicit affirmative consent must be represented and checked.
Reject extra tenant, role, status and arbitrary redirect inputs. WhatsApp format
validation does not verify that a WhatsApp account exists or a message was sent.

Proposed result after commit: `request_id`, short-lived `transition_token`,
`transition_expires_at` and fixed/allowlisted demo path. No contact in URLs,
browser storage, analytics, logs or error strings. The token is not authentication
and grants no tenant membership or privilege.

Same attempt + same payload returns the same durable request. Same attempt +
changed payload conflicts. Define token expiry/consumption/recovery explicitly;
do not silently make a supposedly one-use credential reusable on retry. Unknown
save outcomes reconcile; closing the form must not trigger a late redirect.

Commit the contact before any transition. Notification status is separate from
contact persistence; notification failure cannot erase a saved contact or block
the demo. Never claim client email/WhatsApp delivery from successful persistence.

## Impact and protected behavior

| Owner / seam | Proposed work | Must remain unchanged |
|---|---|---|
| Landing | Separate demo form, client/server adapter, exact CTA map, RU/KK/EN copy | Existing B2B form, trial and lesson-example links outside the approved map |
| LMS demo-access | Additive schema, validation/idempotency, platform-owned persistence, restricted owner read, transition policy | Ordinary TenantLead and tenant/RBAC/auth ownership |
| Demo web | Consume transition then reuse role picker | Normal login, existing demo roles and direct-entry policy |
| Analytics / notifications | Distinct anonymous demo events, existing approved operator channel if suitable | No finance-lead conversion, PII/hash/request ID export or new CRM dependency |

Do not invent a customer tenant ID for platform contacts. Define restricted
runtime permissions and RLS for this new ownership class; tenant/demo users must
be denied, not handed platform data through a nullable-tenant exception.

## Decisions required before accepting the contract

1. Exact contact retention, deletion and consent text: do not reuse assistant-plan
   24-hour/90-day retention or invent a new duration. Existing privacy purposes
   must be checked against this nameless email/WhatsApp flow.
2. Canonical owner view and existing internal notification recipient: select one
   authorized source of truth; no real notification in a read-only audit.
3. Token exchange, consumed/expired replay and saved-but-navigation-failed recovery.
4. Exact CTA list and direct `/login/demo` policy. Default: preserve existing
   direct entry; therefore do not claim every demo viewer supplied a contact.

## Verification and rollout gates

1. Freeze root-owned epic interface, ownership, state machine, impact and rollback;
   assign bounded modules only after that. Drafts are not implementation authority.
2. Focused schema/state tests: both channels, invalid and extra inputs, missing
   consent, stale consent version, allowlists, bots and origin/rate policy.
3. Executable landing-to-API seam tests: real status/body contract, repeated and
   concurrent attempts, changed payload, unknown outcome, failed notification,
   expired/consumed token and recovery. Do not mock away the interface under test.
4. Approved Supabase DEV contour: additive migration and exact cleanup, platform
   access policy plus tenant/demo negative tests, public-schema neutrality.
5. DEV browser: email and WhatsApp through demo role picker; back/cancel, delayed
   response, retry, navigation failure, RU/KK/EN, mobile and keyboard. Check no PII
   in URL/storage/events; smoke existing B2B form, trial, example and normal login.
6. Independent review and one risk-based candidate suite. No production migration,
   dispatch, push or public-content change without separate owner agreement.
7. After authorized publication only: exact API/landing/web revision readback,
   synthetic end-to-end saved request/demo login, analytics negative checks and
   exact synthetic-state cleanup. Delivery and receipt are separate evidence.

LLM routing is not a dependency of this contact-to-demo flow. Its separate DEV
private-connector blocker must not trigger a new public gateway or postpone pure
contract work; current route evidence is owned by docs/PROJECT-CONTEXT.md.
