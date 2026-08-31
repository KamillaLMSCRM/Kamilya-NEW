# Render-like KZ release plane

## Goal

Replace per-release production scripting with one tested immutable-image,
two-slot release mechanism while retaining VM126, CT125 and all existing safety
and approval boundaries.

## Local implementation

- [x] Strict release manifest and root-owned host configuration contracts.
- [x] VM126 blue/green API controller with one active worker set.
- [x] Exact-SHA/digest health and container readback.
- [x] Stable encrypted-backup freshness and CT125 revision gate.
- [x] GHCR build, provenance attestation and protected production workflow.
- [x] Append-only sanitized release ledger.
- [x] Focused tests and workflow contracts: 11 passed; existing version
      contracts: 17 passed; Ruff, Python compile, Git Bash syntax and YAML parse
      are green; real `docker compose config --quiet` also accepts the slot file.
- [x] Graphify index updated after implementation.

## Production bootstrap gate

- [ ] Review exact committed SHA and green GitHub CI.
- [ ] Create the protected `kz-production` GitHub environment.
- [ ] Provision a narrowly permissioned runner on VM126 without general sudo.
- [ ] Install controller/config bytes and record hashes.
- [ ] Read back current SHA, immutable image and Alembic revision.
- [ ] Convert the current runtime to the initial blue slot while preserving the
      legacy compose deployment as rollback.
- [ ] Rehearse a no-migration candidate, forced private-health failure, worker
      failure, post-switch public-health failure and successful rollback.
- [ ] Rehearse one additive migration with fresh backup and CT125 readback.
- [ ] Switch normal release operations to the protected workflow only.

No production mutation is authorized by this plan itself.
