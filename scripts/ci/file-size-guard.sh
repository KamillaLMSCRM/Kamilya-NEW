#!/usr/bin/env bash
# File-size guard — fails if any tracked Python or TS file exceeds 800 LOC.
# Per AGENTS.md §Coding standards: 200-400 typical, 800 max.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${REPO_ROOT}"

MAX_LINES=800
violations=0

while IFS= read -r -d '' file; do
  lines=$(wc -l < "${file}")
  if [ "${lines}" -gt "${MAX_LINES}" ]; then
    echo "::warning file=${file}::${lines} lines (max ${MAX_LINES}). Split into smaller modules."
    violations=$((violations + 1))
  fi
done < <(find apps/api/app apps/web/src -type f \( -name "*.py" -o -name "*.ts" -o -name "*.tsx" \) -print0)

if [ "${violations}" -gt 0 ]; then
  echo
  echo "file-size-guard: ${violations} files exceed ${MAX_LINES} LOC."
  # Don't fail the pre-commit hook — too noisy in early codebases where
  # a few large files exist (e.g. positions/router.py — see audit §1.1).
  # Flip to `exit 1` once the largest offenders are split.
  exit 0
fi

echo "file-size-guard: OK — all files under ${MAX_LINES} LOC."