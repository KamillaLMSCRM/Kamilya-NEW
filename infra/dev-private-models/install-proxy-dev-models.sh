#!/usr/bin/env bash
# kamilya-target: proxy
# kamilya-mode: mutation
# kamilya-correlation: DEV-PRIVATE-20261016
# kamilya-output: sanitized
set -Eeuo pipefail
test "$(id -u)" = 0
test "$(ip -4 -o addr show dev wg0 | awk '{split($4,address,"/"); print address[1]}')" = '10.77.77.1'
stage=/run/kamilya-dev-models-20261016
policy=/etc/ssh/sshd_config.d/90-kamilya-dev-models-20261016.conf
keys=/etc/ssh/kamilya-dev-models-20261016.keys
account=kamilya-dev-models
test -d "$stage"
test -f "$stage/policy.conf"
test -f "$stage/authorized_keys"
test "$#" = 2
[[ "$1" =~ ^[0-9a-f]{64}$ && "$2" =~ ^[0-9a-f]{64}$ ]]
test ! -L "$stage"
test "$(stat -c '%u:%a' "$stage")" = 0:700
for item in policy.conf authorized_keys; do
  test ! -L "$stage/$item"
  test "$(stat -c '%u:%a' "$stage/$item")" = 0:600
done
printf '%s  %s\n' "$1" "$stage/policy.conf" "$2" "$stage/authorized_keys" | sha256sum -c >/dev/null
test "$(wc -l < "$stage/authorized_keys")" = 2
test "$(grep -c '^restrict,port-forwarding ssh-ed25519 [A-Za-z0-9+/=]* kamilya-dev-' "$stage/authorized_keys")" = 2
/usr/sbin/sshd -t
existing_users=$(getent passwd | cut -d: -f1 | grep -v -Fx "$account" | sort)
existing_policy() {
  for address in 127.0.0.1 10.77.77.2 8.8.8.8; do
    while IFS= read -r principal; do
      /usr/sbin/sshd -T -C "user=$principal,host=localhost,addr=$address"
    done <<< "$existing_users"
  done | sha256sum | cut -d' ' -f1
}
root_before=$(existing_policy)
created=false
installed=false
reconciled=false
if getent passwd "$account" >/dev/null || test -e "$policy" || test -e "$keys"; then
  test ! -L "$policy"
  test ! -L "$keys"
  test "$(stat -c '%u:%a' "$policy")" = 0:644
  test "$(stat -c '%u:%a' "$keys")" = 0:644
  printf '%s  %s\n' "$1" "$policy" "$2" "$keys" | sha256sum -c >/dev/null
  test "$(getent passwd "$account" | cut -d: -f6-7)" = /nonexistent:/usr/sbin/nologin
  reconciled=true
fi
rollback() {
  result=$?
  if test "$result" != 0; then
    if test "$installed" = true; then
      chmod 000 "$keys"
      rm -f -- "$policy" "$keys"
      /usr/sbin/sshd -t
      systemctl reload ssh
    fi
    if test "$created" = true; then userdel "$account"; fi
    printf 'EVIDENCE|dev_private_proxy=rolled_back\n'
  fi
  exit "$result"
}
trap rollback EXIT
if test "$reconciled" = false; then
  useradd --system --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin --user-group "$account"
  created=true
  passwd -l "$account" >/dev/null
  install -o root -g root -m 644 "$stage/authorized_keys" "$keys"
  installed=true
  install -o root -g root -m 644 "$stage/policy.conf" "$policy"
fi
passwd -S "$account" | awk '$2=="L" {locked=1} END {exit locked ? 0 : 1}'
/usr/sbin/sshd -t
root_after=$(existing_policy)
test "$root_before" = "$root_after"
effective=$(/usr/sbin/sshd -T -C user=kamilya-dev-models,host=localhost,addr=127.0.0.1)
for expected in 'allowtcpforwarding local' 'permitlisten none' 'permittty no' 'allowagentforwarding no' 'allowstreamlocalforwarding no' 'maxsessions 0' 'passwordauthentication no' 'authenticationmethods publickey' 'permitopen 10.77.77.2:18999 10.77.77.4:18005' 'gatewayports no' 'x11forwarding no' 'permituserrc no' 'permittunnel no' 'kbdinteractiveauthentication no' 'forcecommand /usr/bin/false'; do
  printf '%s\n' "$effective" | grep -Fx "$expected" >/dev/null
done
test "$(id -nG "$account")" = "$account"
systemctl reload ssh
printf 'EVIDENCE|dev_private_proxy=installed|existing_users_policy=unchanged|password=locked|public_ports_added=0|sudo_access=false\n'
