# Kamilya YouTube caption relay

Small authenticated relay used by the development contour when the Render
egress address is blocked by YouTube. It accepts only an 11-character YouTube
video id and the allowlisted `ru`, `kk`, and `en` language codes. It never
accepts arbitrary URLs, downloads media, uses cookies, or bypasses private or
restricted content.

Runtime controls:

- HTTPS is terminated by the existing Caddy service;
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
