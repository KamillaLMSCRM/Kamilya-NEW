# Protected backend activation V1.2 — neutral host feature defaults

Status: Accepted by root integration owner, 2026-10-06. Compatible successor to
V1.1; supersedes only subprocess inheritance of the three known feature names.
Reason: review identified a legacy Compose-precedence risk. Source confirms the
existing compose CLI --env-file already supplies runtime-file interpolation when
host values are absent (the broad absent-host finding was not valid). Explicit
ambient host values could nevertheless override that file through the new anchor.

SubprocessRunner removes only the three feature names from inherited host env,
then overlays explicit per-slot env. Schema1 has no feature overrides, so existing
CLI runtime.env remains authoritative. Schema2 supplies exact candidate/previous
values and takes precedence deliberately. No runtime file is read into artifacts,
rewritten or merged manually. Other environment variables remain unchanged.

Write scope adds only the existing backend controller/runtime-contract test.
Verify actual --env-file argument, ambient false versus runtime true for schema1,
schema2 explicit overrides, and preservation of unrelated env. No new host file,
resource, permission or external operation. All earlier version/schema/rollback/
effective settings gates remain mandatory. Local proof is not production GO.
