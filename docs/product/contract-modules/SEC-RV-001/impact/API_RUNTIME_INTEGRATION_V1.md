# API runtime integration impact addendum V1

Status: Accepted
Approved by: Product owner via security-plan continuation on 2026-09-04

`apps/api/Dockerfile` gains a fixed non-login runtime account after dependency
installation and switches to it only after all application bytes are copied. The two
KZ release Compose manifests apply the same numeric identity and confinement controls
to API and workers through their shared anchor. Commands invoke binaries already in
the image virtual environment; HTTP routes, task registrations, migrations, schemas,
provider configuration and business behavior are unchanged.

The existing certificate bind mount is the only expected durable application write
surface. Its host ownership is not changed by this packet and must be verified against
UID/GID 10001 before deployment. A local Docker daemon was unavailable during source
implementation, so static checks do not establish runtime compatibility.
