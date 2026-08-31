# ADR 0023: Render-like release plane on KZ infrastructure

- Status: Accepted for implementation; production bootstrap pending
- Date: 2026-08-31

## Context

KZ production runs the API and three workers on VM126 and PostgreSQL on CT125.
Historical releases repeatedly generated SHA-specific transfer, build,
migration, watchdog and cleanup scripts. The checks were conservative, but the
mechanism itself changed between releases. Production also built images from
source archives, so build, deployment and rollback were coupled to VM126.

Moving the application to a managed PaaS would simplify deployment but would
also move the application away from the current Kazakhstan infrastructure and
introduce a remote application-to-database path. The required improvement is a
stable deployment control plane, not a hosting-provider migration.

## Decision

Kamilya will use:

1. GitHub Actions to validate the exact successful CI run, build the exact Git
   SHA once and push an immutable GHCR digest with provenance attestation.
2. A strict non-executable release manifest containing only release, previous
   release, image and migration identities.
3. A root-owned VM126 release controller and host configuration installed once.
4. Blue/green API slots on private ports. The candidate receives traffic only
   after exact-SHA private health and four-service image readback.
5. One active worker set. Old workers stop before candidate workers start;
   rollback restores the previous set.
6. A stable CT125 gate that accepts a recently verified encrypted archive or
   creates one, then confirms the exact pre-migration revision.
7. Additive, rollback-compatible migration contracts. Destructive schema
   contraction is a later release after the previous application is retired.
8. Append-only sanitized release evidence and an exact previous-state guard.
9. A protected GitHub `kz-production` environment and narrowly permissioned
   production runner. The production job performs no source checkout.

## Consequences

- VM126 no longer builds application images for normal releases.
- A failed candidate before proxy switching does not affect public traffic.
- A failure after switching restores the previous proxy and workers.
- The initial conversion from the legacy single compose project to two slots is
  a separately approved infrastructure cutover with independent readback.
- PostgreSQL rollback is not automated. Application rollback depends on the
  declared and reviewed expand-compatible migration contract.
- Current and previous slot images are retained; older registry and host image
  retention is handled only after successful release readback.
