#!/usr/bin/env bash
# kamilya-target: asus-connector
# kamilya-mode: mutation
# kamilya-correlation: DEV-PRIVATE-20261016
# kamilya-output: sanitized
set -Eeuo pipefail
test "$(hostname)" = gx10-a721
test "$(id -u)" = 1000
test "$HOME" = /home/gx10-4
test "$(loginctl show-user 1000 --property=Linger --value)" = yes
base=/home/gx10-4/.local/share/kamilya-dev-glm-relay-20261016
unit=/home/gx10-4/.config/systemd/user/kamilya-dev-glm-relay-20261016.service
stage=/home/gx10-4/.local/share/kamilya-dev-glm-stage-20261016
test -d "$stage"
test -f "$stage/glm_relay.py"
test -f "$stage/relay.service"
test "$#" = 2
[[ "$1" =~ ^[0-9a-f]{64}$ && "$2" =~ ^[0-9a-f]{64}$ ]]
test "$(realpath -m "$base")" = "$base"
test "$(realpath -m "$unit")" = "$unit"
test ! -L "$stage"
test "$(stat -c '%u:%a' "$stage")" = 1000:700
for item in glm_relay.py relay.service; do
  test ! -L "$stage/$item"
  test "$(stat -c '%u:%a' "$stage/$item")" = 1000:600
done
printf '%s  %s\n' "$1" "$stage/glm_relay.py" "$2" "$stage/relay.service" | sha256sum -c >/dev/null
created=false
unit_created=false
reconciled=false
if test -e "$base" || test -e "$unit"; then
  test ! -L "$base/glm_relay.py"
  test ! -L "$unit"
  test "$(stat -c '%u:%a' "$base/glm_relay.py")" = 1000:500
  test "$(stat -c '%u:%a' "$unit")" = 1000:600
  printf '%s  %s\n' "$1" "$base/glm_relay.py" "$2" "$unit" | sha256sum -c >/dev/null
  reconciled=true
fi
rollback() {
  result=$?
  if test "$result" != 0; then
    if test "$unit_created" = true; then
      systemctl --user disable --now kamilya-dev-glm-relay-20261016.service || true
      rm -f -- "$unit"
      systemctl --user daemon-reload
    fi
    if test "$created" = true; then
      rm -f -- "$base/glm_relay.py"
      rmdir -- "$base"
    fi
    printf 'EVIDENCE|dev_private_glm_relay=rolled_back\n'
  fi
  exit "$result"
}
trap rollback EXIT
if test "$reconciled" = false; then
  if test ! -d /home/gx10-4/.config/systemd/user; then
    install -d -m 700 /home/gx10-4/.config/systemd/user
  fi
  install -d -m 700 "$base"
  created=true
  install -m 500 "$stage/glm_relay.py" "$base/glm_relay.py"
  install -m 600 "$stage/relay.service" "$unit"
  unit_created=true
fi
systemctl --user daemon-reload
systemctl --user enable --now kamilya-dev-glm-relay-20261016.service
systemctl --user is-active --quiet kamilya-dev-glm-relay-20261016.service
printf 'EVIDENCE|dev_private_glm_relay=active|existing_units_changed=0|sudo_used=false\n'
