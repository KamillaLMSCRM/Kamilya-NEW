#!/usr/bin/env bash
set -Eeuo pipefail

SHA="67477ed5a9fabed92e1bd4805c263697a14826d0"
SHORT="67477ed5a9fa"
IMAGE="kamilya-api:${SHORT}"
ARCHIVE="/tmp/kamilya-release-${SHA}.tar.gz"
BUILD_DIR="/tmp/kamilya-build-${SHORT}"
RUNTIME="/opt/kamilya-runtime"
OPS_CONF="/etc/kamilya/ops-check.conf"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
COMPOSE_BACKUP="$RUNTIME/backups/compose-before-$SHORT-$STAMP.yml"
ENV_BACKUP="$RUNTIME/backups/runtime-before-$SHORT-$STAMP.env"
OPS_BACKUP="$OPS_CONF.before-$SHORT-$STAMP"

rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"
tar -xzf "$ARCHIVE" -C "$BUILD_DIR"
docker build --pull=false -t "$IMAGE" -f "$BUILD_DIR/apps/api/Dockerfile" "$BUILD_DIR"

cp -a "$RUNTIME/compose.yml" "$COMPOSE_BACKUP"
cp -a "$RUNTIME/runtime.env" "$ENV_BACKUP"
if [[ -f "$OPS_CONF" ]]; then
  cp -a "$OPS_CONF" "$OPS_BACKUP"
fi

rollback() {
  set +e
  cp -a "$COMPOSE_BACKUP" "$RUNTIME/compose.yml"
  cp -a "$ENV_BACKUP" "$RUNTIME/runtime.env"
  if [[ -f "$OPS_BACKUP" ]]; then
    cp -a "$OPS_BACKUP" "$OPS_CONF"
  fi
  cd "$RUNTIME"
  docker compose up -d --no-deps --force-recreate api worker-ai worker-documents worker-ops
  echo "ROLLBACK_APPLIED"
}
trap 'rc=$?; rollback; exit $rc' ERR

sed -i -E "s#image: kamilya-api:[0-9a-f]+#image: kamilya-api:$SHORT#g" "$RUNTIME/compose.yml"
sed -i "s#^RELEASE_SHA=.*#RELEASE_SHA=$SHA#" "$RUNTIME/runtime.env"
if grep -q '^EXPECTED_RELEASE=' "$OPS_CONF"; then
  sed -i "s#^EXPECTED_RELEASE=.*#EXPECTED_RELEASE=$SHA#" "$OPS_CONF"
fi
if grep -q '^EXPECTED_API_IMAGE=' "$OPS_CONF"; then
  sed -i "s#^EXPECTED_API_IMAGE=.*#EXPECTED_API_IMAGE=$IMAGE#" "$OPS_CONF"
fi

cd "$RUNTIME"
docker compose config -q
docker compose up -d --no-deps --force-recreate api worker-ai worker-documents worker-ops

for attempt in $(seq 1 45); do
  health="$(curl -fsS --max-time 5 http://10.77.77.2:8000/health || true)"
  if grep -q "$SHA" <<<"$health" && grep -q '"status":"ok"' <<<"$health"; then
    break
  fi
  [[ "$attempt" -lt 45 ]]
  sleep 2
done

for name in kamilya-runtime-api-1 kamilya-runtime-worker-ai-1 kamilya-runtime-worker-documents-1 kamilya-runtime-worker-ops-1; do
  docker inspect -f '{{.Name}}|{{.Config.Image}}|{{.State.Status}}|{{.RestartCount}}' "$name"
done

printf 'PRIVATE_HEALTH='
curl -fsS http://10.77.77.2:8000/health
systemctl start kamilya-ops-check.service
printf '\nOPS='
systemctl show kamilya-ops-check.service -p Result -p ExecMainStatus --value | paste -sd'|' -

trap - ERR
echo "DEPLOY_OK"
