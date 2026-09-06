# Rare Delegation Procedures

Read this reference only when a root is considering delegated external access or
nested delegation. Current project instructions and explicit owner authority prevail.

## Delegated external read

External delegated access is exceptional. The root must give the agent the exact
provider/system, target object or endpoint, canonical access path, safe output fields,
prohibited payloads, credential-handling method, stopping condition, and evidence
label. Do not provide credentials or production routes to a low-cost/isolated worker
merely because the requested action is read-only. The worker must not infer approval
from a previous task, a plan, browser state, memory, or credential presence.

No agent may perform a destructive, costly, production-mutating, or scope-expanding
external action unless the root transfers an exact current approval gate. General
workstream approval is insufficient. On an unknown external-write outcome, reconcile
the existing operation read-only before an authorized retry; never retry by habit.

## Nested delegation

Leaf-only is the default. Nested delegation is allowed only if the root explicitly
sets why the first-level agent must coordinate, maximum depth and child count,
disjoint scopes, inherited authority/data boundaries, how every child handoff reaches
root, and who closes agents and cleans temporary artifacts. Without that contract,
descendant creation is forbidden.

## Escalation detail

After two materially identical failures, hand back the exact target, attempts/error
classes, ruled-out evidence, authority or decision needed, safe default while waiting,
and temporary artifacts requiring cleanup. Materially identical means the same target
and evidence layer with the same error class and no new permitted evidence or
authority. This stops blind repetition; it does not prevent the root from selecting a
new safe, evidence-based method within the original authority.

## Adaptation note

This compact entrypoint/reference split adapts the portable engineering guide,
sections 4.2, 4.4, and 6 (consulted 2026-09-05), as reference rather than authority.
It intentionally retains local model routing and Kamilya safeguards. It adds no hooks,
integrations, credentials, automatic updates, or new spending.
