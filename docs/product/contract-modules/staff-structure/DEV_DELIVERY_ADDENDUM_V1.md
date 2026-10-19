# DEV-only delivery contract

Status: Accepted technical scope, 2026-10-17. Production/master promotion excluded.
Root owns scripts/deploy/dev_release_controller.py and its V6 acceptance tests.

V1–V5 packets keep their existing behavior. New strict V6 activation packet requires
schema0182 evidence, explicit staff_structure_enabled boolean and an exact
configuration_source_branch (codex/*, not master/dev). All previous workbench,
document-draft and lesson-correction flags are explicit preservation constraints;
V6 may change only the new staff flags in existing DEV API, worker and frontend.

Before configuration changes, require successful exact-SHA CI from a same-repository
pull request targeting dev, exact source branch readback, unchanged expected dev
branch SHA and current Free/Free/Hobby provider identities. A master CI/promotion is
not a prerequisite for this DEV-only packet and must not be performed as a workaround.
Public DEV schema remains owned by the separate canonical schema gate. The existing
controller execute path subsequently pushes the exact preserving DEV candidate and
checks CI/provider SHA/health. Feature configuration is not runtime/product acceptance.

Observed Render DEV APP_ENV is intentionally production while DEPLOYMENT_ENVIRONMENT
is render-development. Keep that secure runtime setting unchanged. Workspace opt-in
accepts this exact deployment contour, or local development/dev/test; unknown and
kz-production contours remain disabled even if the flag is accidentally true.

No new resource, billing, provider tier, production service, DNS, SSH or Proxmox.
Rollback can disable the new UI; retain the marker-aware enrollment kernel while
durable preservation facts exist. Browser acceptance and synthetic cleanup remain
independent required gates after exact-SHA deployment.
