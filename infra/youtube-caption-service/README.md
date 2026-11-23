# Kamilya YouTube caption relay

Small authenticated relay for the development environment. It accepts only an 11-character YouTube
video id and the allowlisted `ru`, `kk`, and `en` language codes. It never
accepts arbitrary URLs, downloads media, uses cookies, or bypasses private or
restricted content.

Runtime controls:

- HTTPS is terminated on the existing development gateway. The live gateway
  uses the dedicated Nginx vhost `/etc/nginx/conf.d/kamilya-caption-dev.conf`.
  The Caddy setup in `deploy.sh` describes the original deployment;
- the gateway's original relay uses a random bearer token from a root-readable
  environment file. A relay can also authenticate the same requests using only
  its SHA-256 verifier in `CAPTION_SERVICE_TOKEN_SHA256`. Set exactly one of
  these two variables;
- one process, two provider slots, 30 requests per minute;
- 20-second provider timeout, 500,000-character and 50,000-segment limits;
- containers are read-only, non-root and capability-free. Both relay ports are
  bound to server loopback.

Deploy from an exact Git SHA by transferring this directory to
`/opt/kamilya-caption/source` and running `deploy.sh <40-character-sha>`. Set
the resulting service URL and secret in the Render development environment as
`YOUTUBE_CAPTION_SERVICE_URL` and `YOUTUBE_CAPTION_SERVICE_TOKEN`. Never print
or pass the token as a command-line argument.

These legacy gateway deployment steps apply only to that gateway. The active
DEV server route has its own container and startup configuration below.

## DEV server routes

The remote caption URL and credential configured in Render stay the same.
The GX10-7 route terminates on Nginx loopback port `18084`. The original
gateway relay on `18080` remains a fallback. The server application and
Python environment are under `~gx10-7/.local/share/kamilya-dev-caption`. The
`kamilya-dev-caption.service` and `kamilya-dev-caption-forward.service`
units run under the host account's user manager with linger enabled.
The tunnel key can only open port `18084` on gateway loopback.

With `CAPTION_CACHE_DB` set to the service's private SQLite file, successful
public caption reads are reused for 24 hours and the 32 most recent entries
are retained. The cache is keyed by exact video ID and ordered preferred
languages. Authentication still applies on cache hits. Upstream failures do
not enter the cache. A cold miss depends on YouTube availability from the
selected server.

The prior VM126 route still listens on gateway port `18083`. The container
`kamilya-dev-caption-relay` is bound to VM126 loopback port `18082`; its
configuration is under `/opt/kamilya-dev-caption`.

On VM126, `kamilya-dev-caption-forward.service` starts at boot after
`network-online.target` and `docker.service` and reconnects on failure.
Its dedicated unprivileged account owns the SSH private key. The gateway key
allows remote forwarding only on `127.0.0.1:18083`; the service verifies the
gateway host key before connecting. The former workstation helper and port
`18081` are retired from the active route.

To check recovery, restart only the caption container and its tunnel, then
check the tunnel's boot enablement, unauthenticated HTTP 401, authenticated
caption retrieval for two public videos, and author-side question proposal
with no subtitle request body. A healthy `/health` alone proves process
availability only.

For rollback, restore the exact saved DEV vhost only after confirming its
upstream is currently healthy. Validate the configuration with `nginx -t`,
then reload Nginx and repeat the authenticated caption checks. A saved vhost
that still points to the retired workstation port requires a route adjustment
before it can restore service.
