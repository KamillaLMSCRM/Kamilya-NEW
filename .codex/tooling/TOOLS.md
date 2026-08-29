# Kamilya Agent Tooling

This directory records the reproducible desired state for agent-only packages.
It is not proof that a package is currently installed. Always pair the manifest
with a live import and version probe.

## Environment

- Local environment convention:
  `%USERPROFILE%\.codex\tool-envs\kamilya-agent-tools`
- Dependency manifest: `.codex/tooling/requirements.txt`
- Scope: agent validators and deterministic helpers only.
- Exclusions: backend/frontend runtime, production images, CI, and global/shared
  Python unless separately justified and reviewed.

Create or synchronize the isolated environment from PowerShell:

```powershell
$base = 'C:\Users\user\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$toolEnv = Join-Path $env:USERPROFILE '.codex\tool-envs\kamilya-agent-tools'
if (-not (Test-Path (Join-Path $toolEnv 'Scripts\python.exe'))) {
    & $base -m venv $toolEnv
}
$toolPython = Join-Path $toolEnv 'Scripts\python.exe'
& $toolPython -m pip install --disable-pip-version-check --no-input `
    --only-binary=:all: --no-deps `
    -r .codex\tooling\requirements.txt
```

Before installing a new package, follow the provenance, version, license,
install-hook, vulnerability, conflict, and approval checks in `AGENTS.md`.

## Discovery order

1. Read this file and `.codex/tooling/requirements.txt` for the intended tool.
2. Probe the isolated environment for the actual import and version.
3. Check application manifests only when the package is required by application
   code; do not assume an application dependency is available to agent tooling.
4. If absent, research the official package source and install only after the
   safety checks. Do not search arbitrary global paths or old environments first.

Generic live probe:

```powershell
$toolPython = Join-Path $env:USERPROFILE `
    '.codex\tool-envs\kamilya-agent-tools\Scripts\python.exe'
& $toolPython -c "import importlib.metadata as m; print(m.version('PyYAML'))"
```

## Packages

### PyYAML 6.0.3

- Import: `yaml`
- Purpose: YAML frontmatter parsing for the canonical Codex skill validator.
- Invocation:

```powershell
$toolPython = Join-Path $env:USERPROFILE `
    '.codex\tool-envs\kamilya-agent-tools\Scripts\python.exe'
& $toolPython `
    "$env:USERPROFILE\.codex\skills\.system\skill-creator\scripts\quick_validate.py" `
    '.codex\skills\kamilya-evidence-reconciliation'
```

- Safety: use `yaml.safe_load()` for untrusted YAML. Never use an unsafe object
  loader for workspace, external, generated, or user-provided YAML.

### Paramiko 5.0.0

- Import: `paramiko`
- Purpose: typed SSH transport for `scripts/ops/kz_remote_exec.py`. The helper
  sends reviewed script bytes through the canonical proxy without putting a
  password or script body in command-line arguments.
- Direct dependencies are pinned in `requirements.txt` so the existing
  `--no-deps` installation contract remains reproducible.
- Scope: agent-only local tooling. It is not an application, CI, container, or
  production dependency.
- Safety: the helper loads known hosts with a reject policy, disables legacy
  ciphers/KEX/MAC/host-key algorithms, suppresses raw remote output, and never
  enables SSH agent or local-key fallback. Paramiko is LGPL-2.1; the official
  PyPI wheel has no install hook. Recheck official release/security metadata
  before changing the pin.
- Invocation:

```powershell
$toolPython = Join-Path $env:USERPROFILE `
  '.codex\tool-envs\kamilya-agent-tools\Scripts\python.exe'
& $toolPython scripts\ops\kz_remote_exec.py --help
```
