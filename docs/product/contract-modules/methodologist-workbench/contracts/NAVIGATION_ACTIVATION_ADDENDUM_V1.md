# Workbench navigation and final activation addendum V1

Status: Accepted by root2026-10-02 BEFORE implementation under owner's agreed
stepwise release request. Extends assignment/staged contracts, not voice scope.
Root/module owner: root; product owner: human owner; reviewer: independent leaf
and Test Runner. Change control: root review, additive version; retain predecessor.

## Verified impact and interface

Shared route registry owns the private methodologist-workbench canonical route.
Existing getNavigationRoutes and canAccessRegisteredRoute interfaces unchanged;
Sidebar, CommandPalette and Layout role-policy consume this same registry.
Add one route with manage_assignments, delivery section, dedicated en/ru/kk label,
and a code-owned workbench feature discriminator. Its single private predicate
accepts only NEXT_PUBLIC_METHODOLOGIST_WORKBENCH_ENABLED literal string true.
When OFF/missing/malformed, no navigation or direct registered access. When ON,
only active methodologist may enter; no capability union/admin/student/superadmin.
Route is never public; no auth/session/API/persistence/data-owner change.

Stateless feature visibility; no domain mutation, caching, storage or provider.
Existing manual assignments and every other role/route remain unchanged. Flag OFF
is UI rollback; API remains independently guarded. Root owns registry and tests;
cheap leaf may own only three locale nav keys, no shared release/config edits.

## Verification and rollout

Focused registry/interface tests exercise sidebar/palette/direct route under
true/false/missing/malformed values and all roles, plus existing IA/role-policy/
component/localization neighbors. Full web checks/build and exact CI are required
for B. Default OFF candidate27 is frozen and unaffected by local next-step edits.
Only later B exact schema172/compatible API rollback/DEV live acceptance permits
explicit controlled frontend/API activation. Build/packet flag bindings must be
accepted before adding an enabled artifact; no implicit default change.
No scheduler, AI/STT/mail, paid resources, cleanup or customer fixture side effects.
Stop on unexpected shared impact, weak role/flag tests or missing final-head gates.
Done requires exact activated build, authenticated live flow and synthetic cleanup,
not only route discovery or green tests.
