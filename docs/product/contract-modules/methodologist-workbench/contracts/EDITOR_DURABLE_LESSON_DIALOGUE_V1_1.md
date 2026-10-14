# Durable dialogue V1.1 — ownership race and interrupted readback

Accepted by Root2026-10-14 after independent review, before repair. Amends V1.
Source review: absent target data was nonfatal in legacy chat; ownership could
move during inference; GET hid an expired reservation without telling the user.

Only durable callback fails closed on absent lesson focus before inference.
Before completing a reservation, reauthorize and FOR SHARE-lock the current
lesson/module/course relation in the completion transaction. Never hold those
locks or a DB connection across the external model call. A changed relation
closes the still-owned pending request as failed/interrupted (or accepts its FK
cascade absence), returns404, and creates no archived result/action. Active role
revocation remains protected by authenticated API/RLS, never a bypass closure.
Known callback scope/validation failures are interrupted rather than mislabeled
provider failures. Provider failures retain provider_unavailable; no raw detail.

GET adds optional interrupted_request_id (UUID|null) for the latest scope row
when failed or older-than-10min pending. It is explicit UI information, not an
automatic retry. Old completed history remains readable; a new consciously
entered question may continue. Pending fresh reservations still block sends.
No restored proposal action, new provider call, voice, role or retention change.

Root owns service/router/schema/UI and focused regressions. DEV verifier owner
may add same-tenant move during inference, absent durable target before inference,
expired pending readback, API sibling/foreign/language reads and actor-private
writes to its existing matrix. Final isolated gate, seam/full suite and independent
review must bind the revised source before rollout. Previous21 PASS is retained
but does not prove this delta. Prior accepted contracts remain immutable.
