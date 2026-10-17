# Ambiguous confirmation recovery

Status: Accepted technical refinement, 2026-10-17; DEV only.
Root owns acceptance; prior immutable contracts remain preserved.

Network errors and HTTP5xx, including intermediary502/504, do not prove the
transaction failed. The browser must keep the same server-owned preview ID.
Before confirmation, persist only that opaque ID in session-scoped storage,
namespaced by authenticated tenant+actor. Do not store commands, personal names,
preview snapshots, passwords or tokens. If persistence fails, do not send a new
confirmation. Session-scoped data is not a server audit or an authorization grant.

While confirmation is pending/ambiguous, do not discard it through modal close,
Cancel, Escape or backdrop. On remount/reload, restore a retry-only recovery prompt;
never automatically execute. Explicit user retry uses the same confirmation URL
and {confirmed:true}. A succeeded server receipt replays even after preview expiry;
a still-ready expired/stale plan gives its definite rejection. Success or a definite
4xx rejection clears pending state; network/5xx retains it. Another tenant/actor
cannot see or retry it from this UI; server ownership remains the ultimate guard.

Acceptance: pending and unknown dismissal denied; unknown survives remount; no
automatic POST; no new preview on recovery; same ID replay; account-scope isolation;
successful cleanup; inaccessible session storage causes no confirmation request.
