# Local Graphify operations

Use this reference only when the CLI path, index integrity, creation, or update is
part of the task.

## Workstation setup

CLI: `graphify` from the pipx environment below. Run `graphify --version` and
compare its actual `--help` before using version-sensitive flags; the workstation
version is not an architectural invariant and must not be frozen in this runbook.
Python: `C:/Users/user/AppData/Local/pipx/pipx/venvs/graphifyy/Scripts/python.exe`.
Run from the actual repository root, never `C:/Kamilya New`. Recheck the
version/import before trusting this machine-specific path after drift.

`graphify-out/.graphify_python` must be UTF-8 text containing that interpreter
path, not executable bytes. `.graphify_root` must name the actual repository.

## Diagnose or update

- For a new linked checkout use the combined readiness gate
  `node scripts/dev/prepare_navigation.cjs` before graph-dependent work. Missing
  runtime/index/receipt is a checkout-local setup gap, not proof that the machine
  lacks the tool. Follow `docs/runbooks/codegraph-local.md`, then run explicit
  `--prepare` and read-only preflight. Never copy another branch's index.
- The combined helper supplies `codegraph.json` exclusions to AST extraction,
  checks source/index content hashes, the root marker and zero LLM tokens. Its
  receipt is ignored local evidence; it is not runtime or graph-completeness proof.
- For an ordinary CLI failure, try the documented Python with `-m graphify`.
- Validate integrity with
  `graphify diagnose multigraph --json --max-examples 1`; do not run it before
  every query.
- `graphify update .` is AST-only in the pinned CLI.
- For a missing index use `graphify extract . --code-only --max-workers 2`.
  Success requires a readable `graphify-out/graph.json`; an exit code of zero or
  a populated `graphify-out/cache/` alone is not success. If the file is absent,
  record Graphify as unavailable for this task and use bounded source/import
  inspection instead of repeating extraction or claiming graph evidence.
- Before rebuilding, verify exclusions, exact root, dirty files and existing
  index. Keep the shrink guard and review removed sources before any force.
- After creation/update, check counts and source existence and compare one
  representative query/path with source. Exit code alone is insufficient.

The canonical local output is `graphify-out/graph.json`. It is derived navigation
data, not a deliverable, deployed artifact or replacement for documentation.
