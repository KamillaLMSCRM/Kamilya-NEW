# Existing-session reuse V1

Accepted root2026-10-16, same DEV-only scope. Authenticated handlers already own
an RLS-bound DB session. Resolving settings with a second connection before
admission commit could exhaust the small DEV pool under concurrency. Extend the
internal resolver with optional `db` parameter: same immutable snapshot and
validation, caller session remains caller-owned, no commit/identity change. Use
one nested savepoint for expand-compatible missing-table handling so a failed
read cannot poison the caller transaction. Scoped consumers still reuse their
already-resolved snapshot without I/O. Standalone worker/client factories retain
one short owned session. This introduces no environment pool/capacity change.

Consumer changes: assignment/document intent, document dialogue/content answers,
and model-routing admin response pass existing sessions. Tests demonstrate no
session-factory call/commit on this branch, cleanup on failed read, and existing
role/tenant/budget contracts. No public migration shape change, so prior final31
SQL constraint result remains valid; re-run service snapshot gate for resolver
delta before public migration. No production or ASUS action.
