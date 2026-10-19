# First-four-block production delivery V1

Accepted root technical scope2026-10-19 following the owner's current request:
repair browser acceptance, then release these four improvements to production.
Extends the previously DEV-only delivery boundary; all business/tenant/HR/history
contracts remain unchanged. No voice/iSpring/ASUS/1C/model-route activation.

Production version0.11.63 applies additive0182 runtime settings and0183 staff
plans/retention markers from the independently verified0181 production baseline.
Require fresh signed backup/restore verification, exact schema/FORCE-RLS/runtime
role readback, source/CI/immutable artifact parity and synthetic live acceptance.
Never downgrade public0182 audit tables; binary rollback retains additive schema.
Keep the marker-aware enrollment preservation kernel while markers exist.

Staff workspace remains opt-in/default false. The flag may activate only exact
render-development, local dev/test, or explicitly approved kz-production contour;
unknown contours remain fail-closed. Do not infer activation from APP_ENV alone.
Existing workbench/document/correction flags and model route must remain unchanged.

Backend release manifest V3 adds literal boolean staff_structure to BOTH candidate
and previous flag objects. Preserve V1/V2 exact shapes/semantics. Activation requires
version>=0.11.63 and exact0183 schema; version63 correction epoch is0181->0183.
The typed, digest-bound protected release path sets/readbacks all four services;
rollback restores previous flags including staff=false on unsupported old images.
No arbitrary settings, command/path/secret/role/topology changes.

Native frontend packet V5/build-config V4 explicitly bind staff_structure_enabled,
requires version>=0.11.63, and preserves legacy packets/build configs. Build uses
NEXT_PUBLIC_STAFF_STRUCTURE_V3_ENABLED. Host privileged eight-field manifest stays
unchanged; do not add a new CT137 helper/privilege requirement. UI is optional and
must not expose staff workspace against a disabled backend. Public exact-SHA and
independent browser acceptance remain separate from build/technical receipts.

Owners: root release-plane/backend protocol/version/contracts/external operations;
bounded native writer owns native controller/build workflow/tests; bounded policy
writer owns contour predicate/slot-compose flag/tests. Reviewers do not review their
own writes. Stop on unknown migration/backup/rollback, mixed flags/SHA, tenant data
change or failed health. No destructive cleanup or billing/resource changes implied.
