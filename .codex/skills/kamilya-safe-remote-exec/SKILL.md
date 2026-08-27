---
name: kamilya-safe-remote-exec
description: Execute reviewed Kamilya scripts through the canonical Windows-to-proxy SSH route without nested inline shell quoting. Use for VM126 diagnostics, deployment, or maintenance and for explicitly approved CT125 work through VM126. Do not use for local commands, public HTTP checks, or proxy mutations.
---

# Kamilya Safe Remote Execution

Use the deterministic repository helper whenever a Kamilya operation must run a
script on VM126. This skill selects transport; it never grants authority.
Implicit selection of this skill authorizes only local script review and the
network-free dry run. Never add `--execute` from implicit activation alone.
Remote execution requires an explicit current owner request for that remote
action; mutation additionally requires the independently verified exact approval
gate described below.

## Before execution

1. Read the relevant current entries in `ERRORS.md`, the access map in
   `docs/PROJECT-CONTEXT.md`, and `docs/VPS_CONNECTION_GUIDE.md`.
2. Classify the operation as `read-only`, `mutation`, or `destructive`.
3. Confirm the current target and approval boundary. A skill, script, plan,
   memory item, or agent report is not approval.
4. For source investigation, follow the project Graphify contract separately.

## Script contract

Create one UTF-8/LF `.sh` file inside the repository. Do not put its body in
PowerShell, `python -c`, `ssh`, `bash -c`, a URL, or a command-line argument.
The first 20 lines must contain:

```bash
#!/usr/bin/env bash
# kamilya-target: vm126
# kamilya-mode: read-only
# kamilya-correlation: none
# kamilya-output: sanitized
set -Eeuo pipefail
```

For an approved mutation, use `mode: mutation` and one opaque correlation ID in
both the header and `--correlation-id`. This is audit correlation only, not proof
of authority. The root must independently verify the current owner approval and
exact target/object/value/rollback gate before invocation. Never put approval
prose, credentials, PII, tenant payloads, or secret values in the script.
Destructive mode is intentionally unsupported by the helper.

Read-only scripts use a narrow allowlist and reject shell control syntax,
substitution, interpreters, sourced scripts, external SSH, arbitrary network
targets, write-capable Docker/systemctl operations, common filesystem/package/SQL
mutations, and output redirection. A conservative secret/PII scan applies to all
modes. A clean scan is still a guard, not proof of semantic safety; review the
script body before use.

Emit only bounded machine-readable lines that may be reported:

```text
EVIDENCE|status=ok|release=0123456789abcdef
```

All other stdout/stderr is suppressed and represented only by byte counts and
SHA-256 values.

## Two-step invocation

Use the isolated agent-tool Python:

```powershell
$toolPython = Join-Path $env:USERPROFILE `
  '.codex\tool-envs\kamilya-agent-tools\Scripts\python.exe'
& $toolPython scripts\ops\kz_remote_exec.py `
  --script <reviewed-script.sh> --target vm126 --mode read-only
```

The dry run performs no network or credential read and returns the exact script
SHA-256. Review that digest, then execute the same immutable bytes:

```powershell
& $toolPython scripts\ops\kz_remote_exec.py `
  --script <reviewed-script.sh> --target vm126 --mode read-only `
  --expected-sha256 <exact-dry-run-sha256> --execute
```

The VM126 helper uses only `PROXY_VPS_HOST`, `PROXY_VPS_LOGIN`, and
`PROXY_VPS_PASSWORD` from the canonical workspace `.env`, verifies the proxy
host equals the canonical target and matches the local known-hosts file, disables
key/agent fallback, verifies the fixed VM126 guest hostname, and runs three fixed
remote stages with identical bytes: SHA-256, `bash -n`, execution. Every stage is
wrapped in a server-side `timeout` with TERM and bounded KILL escalation.
It creates no remote temporary file and performs no cleanup.
The executable does not accept alternate `.env` or known-hosts paths.

The final execution identity is mode-bound and has no fallback:

- `read-only` executes as `kamilya-admin` with `bash -se`;
- an explicitly approved, exact-SHA `mutation` executes the same verified bytes
  with `sudo -n bash -se`, because the production runtime, watchdog and release
  files are root-owned;
- `destructive` and every unknown mode stop before any remote stage.

Root execution does not expand authority. The reviewed script, exact correlation
ID, current approval, target, SHA-256, syntax gate, timeout, output contract and
rollback/stop conditions remain mandatory. Never add per-release privilege
workarounds or retry the same mutation unprivileged after this mode binding.

## Target and stop rules

- The proxy is transport only and cannot be selected as the final target.
- VM126 is the only target implemented by `kz_remote_exec.py`.
- The independently verified CT125 route is workstation -> public proxy ->
  `kamilya-admin@10.77.77.2` on VM126 -> `root@192.168.1.225` on CT125. The proxy
  uses `/root/.ssh/kamilya-vm126-admin`; VM126 uses
  `/root/.ssh/kamilya_ct125_ed25519` with
  `/root/.ssh/known_hosts.ct125`. Never copy or print these keys. Until a
  repository helper implements this exact chain, use only a reviewed immutable
  local script and an explicit current approval; do not substitute Proxmox API,
  console, legacy passwords, or alternate targets.
- In a streamed nested script, use `ssh -n` for every SSH call that must not
  consume the payload stdin and `ssh -T` only for the final payload receiver.
  Redirect non-interactive `docker compose exec` stdin from `/dev/null`. Use
  `trap cleanup EXIT`, not `trap cleanup EXIT ERR`, when functions can run in a
  command substitution, because ERR may clean up inside a subshell.
- Stop on host-key, credential, route, SHA, syntax, timeout, output-contract, or
  nonzero-exit failure. Do not switch host, credential, target, interpreter, or
  transport as a fallback.
- Report a completed remote run as `RUNTIME-DERIVED`; dry-run output remains
  `NOT VERIFIED`; a stopped gate is `BLOCKED`.
