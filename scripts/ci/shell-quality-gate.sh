#!/usr/bin/env bash
# Validate every tracked shell script without mutating it.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${REPO_ROOT}"

mapfile -d '' -t shell_scripts < <(git ls-files -z -- '*.sh')

# These files deliberately run through an interpreter rather than as executable
# host commands: the PostgreSQL image sources its init file, and the pgbench
# host-stage driver is consumed by its remote Bash harness. Keep exceptions
# exact so a new non-executable shell script cannot bypass this gate.
NON_EXECUTABLE_SHELL_SCRIPTS=(
  "infra/init-pgvector.sh"
  "tests/load/pgbench/run-hostkz-stage.sh"
)

# Regression coverage: these paths used to be missed when enumeration was
# restricted to scripts/**/*.sh. The gate must fail if either disappears.
REQUIRED_SHELL_SCRIPTS=(
  "infra/init-pgvector.sh"
  "tests/load/pgbench/run-hostkz-stage.sh"
)

if [ "${#shell_scripts[@]}" -eq 0 ]; then
  echo "shell-quality-gate: no tracked *.sh files found."
  exit 0
fi

violations=0

contains_shell_script() {
  local expected="$1"
  local script
  for script in "${shell_scripts[@]}"; do
    [ "${script}" = "${expected}" ] && return 0
  done
  return 1
}

is_non_executable_exception() {
  local script="$1"
  local exception
  for exception in "${NON_EXECUTABLE_SHELL_SCRIPTS[@]}"; do
    [ "${script}" = "${exception}" ] && return 0
  done
  return 1
}

for expected in "${REQUIRED_SHELL_SCRIPTS[@]}"; do
  if ! contains_shell_script "${expected}"; then
    echo "::error file=${expected}::repository-wide shell enumeration missed required regression path."
    violations=$((violations + 1))
  fi
done

echo "shell-quality-gate: regression coverage includes ${REQUIRED_SHELL_SCRIPTS[*]}."

for script in "${shell_scripts[@]}"; do
  mode="$(git ls-files -s -- "${script}" | awk '{print $1}')"
  if is_non_executable_exception "${script}"; then
    expected_mode="100644"
  else
    expected_mode="100755"
  fi
  if [ "${mode}" != "${expected_mode}" ]; then
    echo "::error file=${script}::tracked shell script must use Git mode ${expected_mode} per the shell executable policy (got ${mode:-missing})."
    violations=$((violations + 1))
  fi

  eol="$(git check-attr eol -- "${script}" | sed 's/.*: //')"
  if [ "${eol}" != "lf" ]; then
    echo "::error file=${script}::shell script must have the .gitattributes eol=lf attribute."
    violations=$((violations + 1))
  fi

  if git show ":${script}" | LC_ALL=C grep -q $'\r'; then
    echo "::error file=${script}::tracked shell source contains CRLF line endings."
    violations=$((violations + 1))
  fi

  if ! bash -n "${script}"; then
    echo "::error file=${script}::shell syntax validation failed."
    violations=$((violations + 1))
  fi
done

if [ "${violations}" -gt 0 ]; then
  echo "shell-quality-gate: ${violations} violation(s)."
  exit 1
fi

echo "shell-quality-gate: ${#shell_scripts[@]} tracked shell scripts passed repository-wide LF, CRLF-blob, executable-policy, and syntax checks."
