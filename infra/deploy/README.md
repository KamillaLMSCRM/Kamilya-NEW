# Kamilya release plane

This directory defines the stable VM126 deployment layer. It replaces
per-release source archives and generated mutation scripts with one immutable
GHCR image, one strict JSON manifest and a two-slot controller.

## Safety contract

- The release manifest contains identities only and cannot provide commands,
  paths, credentials or smoke scripts.
- VM126 configuration is root-owned and fixed outside GitHub artifacts.
- `blue` and `green` share the existing Valkey network and blob storage, but
  only the candidate API starts before private health succeeds.
- Old workers stop before candidate workers start. The previous API stays warm
  until the next successful release.
- A failed candidate restores the previous workers and, if necessary, the
  previous Nginx upstream before it is removed.
- Exact migrations require `rollback_compatible=true`, a matching current
  revision and a fresh verified encrypted CT125 archive.
- After the backup gate succeeds, the controller persists an exact root-owned
  migration receipt. A retry may accept an already-applied target revision only
  when that receipt matches the same release, image and from/to revisions.
- Evidence is append-only and contains no command output, environment values or
  tenant data.

## One-time production bootstrap

Bootstrap is a separately authorized infrastructure change, not an application
release. Install reviewed bytes under `/opt/kamilya-release-plane`, copy the
host configuration to `/etc/kamilya-release-plane/config.json`, create an
initial `state.json` from independently read-back current SHA/image, and adapt
Nginx once to proxy through `kamilya_api_active`. Preserve the existing compose
deployment as the initial rollback target until a complete blue/green rehearsal
passes.

The GitHub production environment must require owner approval. Its runner must
have labels `self-hosted`, `linux`, `x64`, and
`kamilya-production-release`. The runner account receives only passwordless
permission for the exact installed controller invocation; it must not receive a
general root shell. The deploy job deliberately performs no repository checkout.

## Operator flow

1. Wait for an exact successful `CI` run and record its run ID.
2. Dispatch `Render-like KZ release` with exact current/next identities.
3. Leave `deploy_to_production=false` to build and attest the image plus validate
   the manifest without touching VM126.
4. After artifact review, dispatch with `deploy_to_production=true`; protected
   environment approval releases the fixed controller job.
5. Confirm the separate production-smoke workflow and business acceptance.

The first VM126 installation and slot conversion require the production deploy
skill, exact owner authority, rollback packet and independent readback.
