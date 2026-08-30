#!/usr/bin/env bash
set -Eeuo pipefail

PUBLIC_HOST="${PUBLIC_HOST:-caption-dev.173-249-51-164.sslip.io}"
INSTALL_DIR="${INSTALL_DIR:-/opt/kamilya-caption}"
IMAGE_TAG="${1:?exact release SHA is required}"
CONTAINER_NAME="kamilya-caption-dev"
CADDYFILE="/etc/caddy/Caddyfile"

if [[ "$(id -u)" != "0" ]]; then
  echo "deploy must run as root" >&2
  exit 1
fi
if [[ ! "$IMAGE_TAG" =~ ^[0-9a-f]{40}$ ]]; then
  echo "exact 40-character Git SHA is required" >&2
  exit 1
fi

install -d -m 0700 "$INSTALL_DIR"
if [[ ! -f "$INSTALL_DIR/.env" ]]; then
  umask 077
  printf 'CAPTION_SERVICE_TOKEN=%s\n' "$(openssl rand -hex 32)" > "$INSTALL_DIR/.env"
fi
chmod 0600 "$INSTALL_DIR/.env"

docker build -t "kamilya-caption:${IMAGE_TAG}" "$INSTALL_DIR/source"
docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
docker run -d \
  --name "$CONTAINER_NAME" \
  --restart unless-stopped \
  --env-file "$INSTALL_DIR/.env" \
  --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=16m \
  --security-opt no-new-privileges \
  --cap-drop ALL \
  -p 127.0.0.1:18080:8080 \
  "kamilya-caption:${IMAGE_TAG}" >/dev/null

backup="${CADDYFILE}.before-kamilya-caption-$(date -u +%Y%m%dT%H%M%SZ)"
cp --preserve=mode,ownership,timestamps "$CADDYFILE" "$backup"
if ! grep -q "# BEGIN KAMILYA CAPTION DEV" "$CADDYFILE"; then
  cat >> "$CADDYFILE" <<EOF

# BEGIN KAMILYA CAPTION DEV
${PUBLIC_HOST} {
	request_body {
		max_size 4KB
	}
	reverse_proxy 127.0.0.1:18080
}
# END KAMILYA CAPTION DEV
EOF
fi

if ! caddy validate --config "$CADDYFILE"; then
  cp "$backup" "$CADDYFILE"
  exit 1
fi
systemctl reload caddy

for _ in $(seq 1 30); do
  if curl -fsS --max-time 5 "https://${PUBLIC_HOST}/health" >/dev/null; then
    printf 'CAPTION_DEPLOY_OK host=%s sha=%s\n' "$PUBLIC_HOST" "$IMAGE_TAG"
    exit 0
  fi
  sleep 2
done
echo "caption service health check failed" >&2
exit 1
