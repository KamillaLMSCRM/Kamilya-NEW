# API runtime identity mini-spec

## Identity

| Field | Value |
|---|---|
| Module ID | `API-RUNTIME-IDENTITY` |
| Name | API image and KZ release-service confinement |
| Status | Accepted |
| Document version | V1 |
| Owning extension | `../EPIC_EXTENSION_RUNTIME_V1.md` |

## Responsibility

Ensure API and worker processes execute as a fixed non-root identity with no ambient
Linux capabilities, no privilege escalation and no writable container root filesystem.

## Invariants

- The image creates and runs as UID/GID `10001:10001` with a nologin shell.
- Application source and `/app/.venv` are installed before `USER` and stay root-owned.
- Python bytecode writes are disabled; writable transient state is confined to a
  bounded `noexec,nosuid,nodev` `/tmp` tmpfs.
- KZ release services use `read_only`, `cap_drop: ALL` and
  `no-new-privileges:true` and execute installed binaries directly.
- Durable writes are limited to explicitly mounted storage whose host permissions are
  verified before rollout.
- Database migration ownership, image digest pinning and release-plane authority do not
  change.

## Verification

Static contract tests cover Dockerfile instruction ordering and both KZ Compose files.
`docker compose config` must parse both manifests. An actual image build and runtime
probe (`id`, read-only root rejection, `/tmp` write and certificate-volume write) remain
mandatory release evidence.

## Rollback

Rollback is the exact prior immutable image and prior release-plane Compose revision.
Do not repair a permission failure by running the application as root or granting broad
host-directory permissions.
