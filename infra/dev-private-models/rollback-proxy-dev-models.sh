#!/usr/bin/env bash
# kamilya-target: proxy
# kamilya-mode: rollback-owned
# kamilya-correlation: DEV-PRIVATE-20261016
# kamilya-output: sanitized
set -Eeuo pipefail
test "$(id -u)" = 0
test "$#" = 2
[[ "$1" =~ ^[0-9a-f]{64}$ && "$2" =~ ^[0-9a-f]{64}$ ]]
policy=/etc/ssh/sshd_config.d/90-kamilya-dev-models-20261016.conf
keys=/etc/ssh/kamilya-dev-models-20261016.keys
test ! -L "$policy"
test ! -L "$keys"
printf '%s  %s\n' "$1" "$policy" "$2" "$keys" | sha256sum -c >/dev/null
test "$(getent passwd kamilya-dev-models | cut -d: -f6-7)" = /nonexistent:/usr/sbin/nologin
test "$(id -nG kamilya-dev-models)" = kamilya-dev-models
# Revoke the exact new keys before removing the restrictive Match policy.
chmod 000 "$keys"
rm -- "$keys" "$policy"
/usr/sbin/sshd -t
systemctl reload ssh
userdel kamilya-dev-models
printf 'EVIDENCE|dev_private_proxy=owned_installation_removed|existing_users_changed=0\n'
