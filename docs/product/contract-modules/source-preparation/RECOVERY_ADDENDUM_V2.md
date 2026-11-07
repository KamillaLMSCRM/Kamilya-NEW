# Source preparation staged recovery V2

Status frozen for the owner-authorized two-file DEV acceptance on 2026-11-07.
Actual DEV cash review85 timed out at editor_request after all ten images and the
verified manifest were durable. The PDF completed. Keep both original receipts.

## Observable behavior

Preparation and semantic checking progress automatically through bounded worker
turns. A complete image or model response is reused after a worker interruption.
No larger arbitrary global timeout, extra critic, weaker source approval, provider
change or client-data mutation is introduced. The existing750/820/850-second
budgets remain; sufficient per-request wall time must remain before a new POST.

## Shared handshake

- Existing analysis_block events own source-bound per-request intent, completed
  result and usage. Keys bind the exact original, selected manifest/text, policy
  and messages; claim identity fences writes but does not destroy cold reuse.
- A durable verified manifest is an automatic handoff boundary before semantic
  editing. Under the document lock, verify original/current claim/exact binding,
  append one successor queued event, commit, then dispatch its exact event ID.
  A duplicate delivery cannot claim twice. Lost acknowledgement may redispatch
  only that still-latest queued event; no new model stage is created by dispatch.
- Near the worker budget, defer only before a POST is sent. Visual deferral is a
  known-not-sent rejection so existing batch-intent reconciliation remains valid.
  Semantic calls need a response checkpoint immediately after completion, before
  the next stage or whole-block validation. Completed errors replay as errors;
  no repeated paid call merely to recreate a known invalid response.
- Unknown in-flight requests stay fenced. Explicit new-attempt acknowledgement
  records actor, request ID and exact failed event, retains unknown outcome/cost,
  and authorizes at most a separate bounded attempt. It never changes the old
  failure into success. No automatic acknowledgement or provider lookup is assumed.
- ReviewCommand adds optional strict acknowledge_outcome_and_cost_unknown only
  for start. Absent fields stay absent from legacy command digests. Public review
  adds optional requires_retry_acknowledgement and continuation_pending booleans.
  Unrecoverable visual unknown exposes retry_blocked_unknown_visual instead of
  promising an unsupported retry. Pre-manifest known-not-sent continuation may
  have no preparation binding; exact source/parent-claim ancestry still applies.
  New queued payload records acknowledged_unknown or continuation_from. Existing
  immutable approvals/digests and prior decisions remain unchanged until success.
- Usage is retained per completed request and counted once across continuation;
  legacy failed usage remains distinguishable, missing cost stays unknown.
- Stale legacy running/analysis-block records without a terminal outcome are
  held for reconciliation. They cannot start a new request or change selection.
  This bounded package does not expose automatic recovery of every killed worker;
  exact verified queued continuations remain redispatchable without another event.

## Ownership and acceptance

Terra asset_seams owns analysis orchestration, a bounded request-custody helper
and their tests. Terra parts_review_seams owns API/service/domain/UI acknowledgement
and redispatch behavior plus tests. English-only communication; root owns this
contract, integration, actual execution and release. Writers cross-review the
other delta after handoff. No new model call while implementing or testing.

Saved synthetic gates cover: before/after-intent interruption; response committed
before later-stage failure; exact cold replay; unknown blocked; strict explicit
ack/new attempt; stale/foreign source/selection; duplicate continuation delivery;
dispatch acknowledgement loss; usage counted once; historical approval readback.
Then exact CI/DEV rollout and resume retained real files, never repeating their
completed native image readings. Full course and production acceptance remain
separate gates.
