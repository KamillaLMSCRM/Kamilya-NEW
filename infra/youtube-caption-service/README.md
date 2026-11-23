# Kamilya YouTube caption relay

Small authenticated relay used by the development contour when the Render
egress address is blocked by YouTube. It accepts only an 11-character YouTube
video id and the allowlisted `ru`, `kk`, and `en` language codes. It never
accepts arbitrary URLs, downloads media, uses cookies, or bypasses private or
restricted content.

Runtime controls:

- HTTPS is terminated on the existing development gateway. The live gateway
  uses the dedicated Nginx vhost `/etc/nginx/conf.d/kamilya-caption-dev.conf`.
  The Caddy setup in `deploy.sh` describes the original deployment;
- bearer token is generated on the VPS and stored only in a root-readable
  environment file;
- one process, two provider slots, 30 requests per minute;
- 20-second provider timeout, 500,000-character and 50,000-segment limits;
- container is read-only, non-root, capability-free, and reachable directly
  only through `127.0.0.1:18080`.

Deploy from an exact Git SHA by transferring this directory to
`/opt/kamilya-caption/source` and running `deploy.sh <40-character-sha>`. Set
the resulting service URL and secret in the Render development environment as
`YOUTUBE_CAPTION_SERVICE_URL` and `YOUTUBE_CAPTION_SERVICE_TOKEN`. Never print
or pass the token as a command-line argument.

This deployment does not authorize CT125, VM126, production, DNS, tenant-data,
or credential changes.

## DEV workstation route

When an existing relay egress is denied access to public captions, the
known-working workstation can serve the same relay over a reverse SSH tunnel.
The Render caption URL and bearer credential remain unchanged. The dedicated
Nginx vhost prefers the forwarded loopback relay at `127.0.0.1:18081` for
`/v1/transcripts` and retains the original container at `127.0.0.1:18080` as
backup. Take a copy of the exact vhost, validate and gracefully reload Nginx.
Verify that relief applies only to the caption route and that a request without
a bearer still returns 401.

`scripts/ops/dev_caption_workstation_bridge.py` runs the same caption app on
workstation loopback and authenticates SSH against the pinned legacy host key.
Supply the workspace API Python executable with `--relay-python` and the
canonical Kamilya legacy environment file with `--legacy-env`. Use the
existing Python launcher with Paramiko, outside the API virtual environment.
The helper reads the active caption token in process memory and reconnects
after a connection interruption. The workstation must be online while this
route is in use. The helper does not register itself for Windows startup.

Rollback restores the saved copy of the exact vhost, validates Nginx and
reloads it before stopping the owned workstation helper. The host configuration
of the original caption container and its secret are retained.
