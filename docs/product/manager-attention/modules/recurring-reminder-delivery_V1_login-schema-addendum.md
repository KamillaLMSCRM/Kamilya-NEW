# R2a login-schema correction and acceptance V1

Accepted by root 2026-09-05. Extends UI acceptance and implementation addenda.
Evidence: isolated schema-only clone of DEV 0151 fails actual migration0152 with
SQLSTATE 42703, `column u.has_login_access does not exist`; cleanup remaining=0.
User.has_login_access is a Python property, not a physical database column.

Root owns correction to undeployed 0152 and SQL fixtures. Preserve public interface
has_login_access boolean; derive it from nonempty password_hash OR telegram_id
not null OR email_verified_at not null, exactly matching User property. This is
compatibility repair, no new login method, invitation or credential disclosure.
Verify every branch and no-access behavior against actual column schema.

Assembled DEV gate copies only table structure (LIKE INCLUDING ALL) of explicit
dependencies into UUID-scoped schema; reject sequence defaults, copy no data,
grant only isolated objects and drop exact schema with independent readback.
Apply actual0152 there. Legacy FK/triggers/RLS not copied by LIKE: reconstruct
bounded tenant policies for test routing and explicitly label legacy parity gap.
No full historical migration-chain claim. Production schemas/roles untouched.

Actual API router and materializer/store/email renderer can be exercised through
test-only dependency bindings: SQLAlchemy schema_translate_map for ORM; exact
allowlisted reminder function namespace mapping for textual SQL; tenant-context
function local shim; credential decoding replaced with synthetic active user;
initial-assignment email enqueue stubbed (separate channel); Resend transport
replaced with synthetic recorder. Celery memory broker tests local queue/worker
dispatch only, not live Valkey/process/timer. No product code namespace workaround.
Cross-tenant/role negatives, rollback, durable terminal status and duplicate
delivery are required. Any new real schema mismatch blocks until corrected.
