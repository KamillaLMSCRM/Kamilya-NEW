# Production SMTP private SSH egress — 2026-11-02

Status: RESTORED. Current API and worker-ops TLS/AUTH pass. An owner-only real email-code request returned 200; the new code was read in the owner mailbox in process and verified through the normal API (200). Owner-only welcome endpoint returned sent/200 and its message arrived. No code, password, session token or message body was saved. No customer employee message was sent.

Direct VM126 → mail.kml.kz:465 still times out. The precise upstream filtering cause remains unknown. Historical runtime backups use the same SMTP since August; current credentials were independently accepted through the working proxy route.

## Runtime

- Existing proxy: `kamilya-smtp-transit.service`, enabled, Restart=always with five-second backoff, pinned existing proxy→VM126 SSH key/known-hosts; remote listener VM loopback `127.0.0.1:24567` only. Remote SMTP destination remains mail.kml.kz:465.
- VM126: `kamilya-smtp-egress.socket` listens only on Docker gateway `172.18.0.1:24568`. Its service uses existing systemd-socket-proxyd to connect to localhost:24567. No public listener or SSH permission changes.
- VM126: exact tagged INPUT and DNAT rules match bridge br-f017093ed97e, production network 172.18.0.0/16 and original mail destination 144.91.117.51:465. Original hostname and standard TLS certificate validation remain unchanged. No provider or app configuration change and no API/container restart.
- VM refresh service/timer reconciles the tagged rules after Docker startup and every minute. All normal deployment operations must preserve/check the existing external production Docker network and these owned rules.
- Eight-minute automatic rollback timers were armed during installation and disarmed on both hosts only after successful actual-container and real-mail verification. Rollback scripts retained on each host at `/opt/kamilya-smtp-recovery-20261102/rollback`.

## Readback and limits

Both sender containers passed ordinary SMTP_SSL with their unchanged settings. Transit was restarted and both probes passed again. Current API plus all three workers running/restarts0; new units enabled and rollback timers inactive. Host reboot was not performed. DNS address or Docker bridge/network changes require revising this route before a deployment; current rules intentionally bind the reviewed exact destination and bridge. Treat a network-recreation or DNS drift as an operational gate, not permission to add a broad NAT rule.

## Rollback

Use canonical pinned SSH routes. On VM126 invoke root-only `/opt/kamilya-smtp-recovery-20261102/rollback`, then the same exact path on the proxy. VM rollback stops/drains its refresh before deleting only tagged rules; readback must show no kamilya-smtp-egress-v1 rules and no dedicated listener. Proxy rollback removes only its dedicated service. Original direct egress remains broken, so rollback restores preincident transport configuration but not email availability. Never flush firewall tables or disable TLS/SSH verification.

Source scripts and exact SHA manifest: `.release-evidence/dev/smtp-recovery-v1/`; sanitized acceptance receipt `receipt.json`. Dedicated unit and rule paths were verified absent before creation. The script artifacts are local evidence and must be preserved for any later maintenance.

## Engine-release preservation verification — 2026-11-05

The existing route was independently checked from VM126 before engine release:
current API certificate verification, stored-credential AUTH and NOOP250 pass;
no new message was sent by this verification. The production Docker network
remains `kamilya-runtime_default`, subnet `172.18.0.0/16`; the egress socket and
refresh timer are active/enabled. The root-only release environment still contains
the course-approval encryption key and it matches the current API. Preserve the
whole existing environment and external network during blue/green activation.

After activation, repeat the certificate/AUTH/NOOP probe against the new API and
worker-ops. Do not infer email delivery from a green health response, reset the
SMTP password, replace this route with direct VM egress, or disable the existing
refresh timer. Any topology or DNS drift is an explicit deployment gate.
Sanitized local proof: `v3-production/p27-release-plane-preservation-result.json`,
`p27-smtp-noop-before-result.json` and `p27-mail-route-readonly-result.json`.
