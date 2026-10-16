#!/usr/bin/env bash
# kamilya-target: asus-connector
# kamilya-mode: rollback-owned
# kamilya-correlation: DEV-PRIVATE-20261016
# kamilya-output: sanitized
set -Eeuo pipefail
test "$(hostname)" = gx10-a721
test "$(id -u)" = 1000
test "$#" = 2
[[ "$1" =~ ^[0-9a-f]{64}$ && "$2" =~ ^[0-9a-f]{64}$ ]]
base=/home/gx10-4/.local/share/kamilya-dev-glm-relay-20261016
unit=/home/gx10-4/.config/systemd/user/kamilya-dev-glm-relay-20261016.service
test "$(realpath -m "$base")" = "$base"
test "$(realpath -m "$unit")" = "$unit"
test ! -L "$base/glm_relay.py"
test ! -L "$unit"
printf '%s  %s\n' "$1" "$base/glm_relay.py" "$2" "$unit" | sha256sum -c >/dev/null
systemctl --user disable --now kamilya-dev-glm-relay-20261016.service
test "$(systemctl --user is-active kamilya-dev-glm-relay-20261016.service || true)" = inactive
rm -- "$base/glm_relay.py" "$unit"
rmdir -- "$base"
systemctl --user daemon-reload
printf 'EVIDENCE|dev_private_glm_relay=owned_installation_removed|existing_units_changed=0\n'
