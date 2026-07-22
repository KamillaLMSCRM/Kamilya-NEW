# CI tenant gate hardening

Date: 2026-07-21

## 1. Separate blocking security checks from legacy lint debt

- Split the current mixed backend lint/tenant-gate CI job so Ruff and mypy remain explicitly warn-only while the tenant-isolation check is its own blocking job.
- Remove any job-level masking that could hide a failing tenant gate.
- Verify the workflow YAML structure and the local tenant gate result.

**What changed:** `.github/workflows/ci.yml` now has a separate `release-security-gates` job with no job- or step-level `continue-on-error`. It runs the shell, tenant-isolation, and release-contract checks. `backend-lint` is explicitly named legacy warn-only; Ruff remains step-level warn-only, and the existing mypy/frontend lint debt remains unchanged and warn-only.

**Checks:** `scripts/ci/tenant-gate.sh` completed with `144 queries checked, 0 violations`.

**Status:** completed

## 2. Enforce portable shell-file attributes and validate shell scripts

- Add `.gitattributes` to require LF for shell scripts without rewriting existing files.
- Add a deterministic shell-script gate that rejects CRLF and non-executable tracked `*.sh` files, and runs Bash syntax validation.
- Run the gate locally.

**What changed:** Added `.gitattributes` with `*.sh text eol=lf`, set Git executable mode (`100755`) on the six tracked `scripts/**/*.sh` files, and added `scripts/ci/shell-quality-gate.sh`. The gate checks the Git LF attribute, CRLF-free tracked source, executable mode, and Bash syntax without rewriting files.

**Checks:** `shell-quality-gate.sh` completed successfully for all six tracked scripts.

**Status:** completed

## 3. Add a dependency-free release-contract check

- Add a deterministic local script that statically validates one connected Alembic revision chain with exactly one head and verifies the Celery include/task registration contract from source.
- Add the script as a blocking CI gate without loading settings, `.env`, or making network requests.
- Run the check locally.

**What changed:** Added `scripts/ci/release-contract-gate.py`, a Python-standard-library AST check. It verifies exactly one connected Alembic root/head chain and the declared Celery includes/task names without importing application settings, reading `.env`, or using the network. It is a blocking workflow step.

**Checks:** The check completed with `66 revisions, head=0068` and the expected `ai.generate_course`, `ai.ingest_document`, and `positions.apply_course_rules` task registrations.

**Status:** completed

## 4. Verify and document the final gate policy

- Validate YAML and shell syntax, run all new checks, and inspect the diff and final git status.
- Record exact files, commands, results, and any limitations under each completed item.
- Do not commit, push, or contact external systems.

**What changed:** Reviewed the workflow’s gate placement and indentation, verified Python and Bash syntax, and inspected only the scoped diff. No commit, push, deployment, DNS, or database action was performed.

**Checks:** `python -m py_compile scripts/ci/release-contract-gate.py`, both new shell gates, and `git diff --check --cached` pass. A parser-based YAML check could not run locally because `actionlint`, `yq`, Ruby, and Python/Node YAML parsers are not installed; installing one would require external package access, outside this task’s authorization. The workflow structure was inspected directly.

**Status:** completed with the YAML-parser limitation documented

## Correction — repository-wide shell coverage (2026-07-22)

- Correct the shell gate’s legacy `scripts/**/*.sh` enumeration to cover every tracked `*.sh` path using NUL-delimited Git output.
- Apply the LF attribute, CRLF-free blob, Bash syntax, and executable-mode policy to all discovered paths. Keep any non-executable entries as exact, documented policy exceptions.
- Add a deterministic regression self-check for `infra/init-pgvector.sh` and `tests/load/pgbench/run-hostkz-stage.sh`, then rerun all blocking release gates and available YAML validation.

**What changed:** `scripts/ci/shell-quality-gate.sh` now uses `git ls-files -z -- '*.sh'` and NUL-delimited Bash array input, covering all eight tracked shell scripts rather than only `scripts/**/*.sh`. LF attribute, indexed CRLF-byte, Bash syntax, and executable mode are checked for every path. `infra/init-pgvector.sh` and `tests/load/pgbench/run-hostkz-stage.sh` remain explicit `100644` interpreter-run exceptions; every other tracked shell script must be `100755`. The regression self-check fails if either formerly missed path is absent from enumeration.

**Checks:** Graphify was queried before inspection and refreshed with `graphify . --update --code-only`; its semantic refresh was skipped because no LLM key was supplied. The shell gate passed for eight scripts and printed both regression paths. The tenant gate passed with `144 queries checked, 0 violations` after four line-specific, already-reviewed AI exception entries were moved to match unrelated source line shifts. The release-contract gate passed (`66 revisions`, head `0068`, expected Celery tasks) and `python -m py_compile` passed. `actionlint`, `yq`, and Ruby are not installed, so no parser-based YAML command was available; `git diff --cached --check` was run.

**Status:** completed
