# Protected backend activation V1.1 — effective legacy flag readback

Status: Accepted by root integration owner, 2026-10-06. Supersedes only V1's
selected-literal Docker environment readback mechanism; all other V1 gates remain.
Reason: fresh production38 preflight proves the old immutable image supports
workbench/document flags but has no correction setting in any of four processes.
Git source370f56fb confirms this. Demanding an explicit false environment entry
would prevent a safe first activation and would confuse absent capability with
enabled behavior. Root's first probe imported a nonexistent settings singleton;
preserved A/B harness failures were repaired with canonical get_settings(), not
new credentials or weaker host gates. C readback succeeded without mutation.

Fixed read-only Docker exec imports get_settings() in each existing container and
emits only the three named flags with typed supported/enabled values. It never
prints a raw environment or secrets. Candidate/replay require all three settings
supported and exactly equal to the manifest. Previous/rollback permit an absent
setting only when its explicitly approved expected value is false. Missing active
capability, nonboolean/unknown/missing/duplicate readback, unsupported enabled
value or configuration import failure refuses release. The exception is confined
to the previous immutable image and does not authorize new candidate omissions.

Source/write scope adds only existing backend activation tests and one isolated
test_correction_backend_runtime_contract.py oracle. Verify real getter/health
producer names, modeled merged Compose environment, adversarial readbacks,
missing old correction compatibility, strict missing candidate refusal, Alembic
failure after backup and sanitized evidence with no worker stop. No host/runtime
file, privilege, plan, resource, business policy or external authority changes.
Runtime controller/bundle installation and exact production acceptance remain
separate protected gates, not inferred from local tests.
