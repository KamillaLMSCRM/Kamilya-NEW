# Local Graphify operations

Use this reference only when the CLI path, index integrity, creation, or update is
part of the task.

## Workstation setup

CLI: `graphify`, package `graphifyy==0.9.23` in pipx.
Python: `C:/Users/user/AppData/Local/pipx/pipx/venvs/graphifyy/Scripts/python.exe`.
Run from the actual repository root, never `C:/Kamilya New`. Recheck the
version/import before trusting this machine-specific path after drift.

`graphify-out/.graphify_python` must be UTF-8 text containing that interpreter
path, not executable bytes. `.graphify_root` must name the actual repository.

## Diagnose or update

- For an ordinary CLI failure, try the documented Python with `-m graphify`.
- Validate integrity with
  `graphify diagnose multigraph --json --max-examples 1`; do not run it before
  every query.
- `graphify update .` is AST-only in the pinned CLI.
- For a missing index use `graphify extract . --code-only --max-workers 2`.
- Before rebuilding, verify exclusions, exact root, dirty files and existing
  index. Keep the shrink guard and review removed sources before any force.
- After creation/update, check counts and source existence and compare one
  representative query/path with source. Exit code alone is insufficient.

The canonical local output is `graphify-out/graph.json`. It is derived navigation
data, not a deliverable, deployed artifact or replacement for documentation.
