#!/usr/bin/env bash
# Tenant-id security gate.
#
# Enforces AGENTS.md §Multi-tenancy:
#   "Every query filters by tenant_id ... Any PR without tenant filter = rejected."
#
# Strategy:
#   - Find every place that calls `select(<Model>)` where Model has a `tenant_id` column.
#   - Within ~30 lines after that select, look for `tenant_id` reference.
#   - If missing → exit 1.
#   - Whitelist escape hatch: add `# tenant-gate: allow` on the same line or the line
#     above the select() to suppress the check (e.g. superadmin endpoints, system jobs).
#
# This is intentionally lightweight (grep-based). A more sophisticated AST-based
# check is planned (scripts/ci/tenant_gate_ast.py) but not needed for v1.

set -euo pipefail

# Anchor to repo root regardless of where the script is invoked from.
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${REPO_ROOT}"

PY_FILES=$(find apps/api/app -name "*.py" -not -path "*/migrations/*" -not -path "*/tests/*")
if [ -z "${PY_FILES}" ]; then
  echo "tenant-gate: no python files found, nothing to check."
  exit 0
fi

# Tenant-scoped tables (mirrors alembic/versions/0019_rls_policies.py).
# Update this list when adding new tenant-scoped tables.
TENANT_MODELS=(
  "User"
  "Tenant"        # Tenant itself does not have tenant_id — special-case.
  "Course"
  "CourseModule"
  "Lesson"
  "Quiz"
  "Question"
  "QuizAttempt"
  "Document"
  "DocumentChunk"
  "DocumentEmbedding"
  "Enrollment"
  "Progress"
  "Certificate"
  "Position"
  "JobDescription"
  "AuditEvent"
  "Integration"
  "ProviderKey"
)

# Exclude Tenant — it IS the tenant, not owned by one. Build this list
# explicitly: Bash parameter substitution would leave an empty element, which
# turns the search into a broad `select(\\b` match.
FILTERED_MODELS=()
for model in "${TENANT_MODELS[@]}"; do
  if [ "${model}" != "Tenant" ]; then
    FILTERED_MODELS+=("${model}")
  fi
done

# The gate normally requires a direct tenant_id predicate. These reviewed
# locations are bounded by a previously tenant-scoped parent or intentionally
# public data. Keep the allowlist line-specific so any new unscoped query
# fails until it receives an explicit security review.
REVIEWED_SCOPE_LOOKUPS=(
  # Public registration must check globally unique identities before a tenant exists.
  "apps/api/app/modules/auth/telegram_register.py:88:User"
  "apps/api/app/modules/tenants/router.py:141:User"
  # AI rewrites first validate the module/lesson tenant, then use its descendants.
  "apps/api/app/modules/ai/router.py:621:Course"
  "apps/api/app/modules/ai/router.py:625:Lesson"
  "apps/api/app/modules/ai/router.py:706:Quiz"
  "apps/api/app/modules/ai/router.py:809:Course"
  "apps/api/app/modules/ai/router.py:830:Quiz"
  # Questions are bounded by a tenant-filtered quiz set in the same service.
  "apps/api/app/modules/quizzes/service.py:56:Question"
  # Kiosk courses/enrollments are bounded by the tenant-scoped kiosk link.
  "apps/api/app/modules/users/kiosk_service.py:237:Position"
  "apps/api/app/modules/users/kiosk_service.py:363:Course"
  "apps/api/app/modules/users/kiosk_service.py:369:Enrollment"
  # Public certificate-number verification is deliberately cross-tenant.
  "apps/api/app/modules/certificates/service.py:250:Certificate"
)

violations=0
checked=0

for model in "${FILTERED_MODELS[@]}"; do
  # Find every select(<Model>) call site. Read grep output line-by-line:
  # shell word splitting corrupts source lines containing spaces and can silently
  # skip checks or abort the gate under `set -u`.
  while IFS=: read -r file lineno _source; do
    [ -n "${file}" ] || continue

    for allowed in "${REVIEWED_SCOPE_LOOKUPS[@]}"; do
      if [ "${file}:${lineno}:${model}" = "${allowed}" ]; then
        checked=$((checked + 1))
        continue 2
      fi
    done

    # Skip whitelisted (annotation).
    if sed -n "${lineno}p" "${file}" | grep -q "tenant-gate: allow"; then
      continue
    fi
    prev=$((lineno - 1))
    if [ "${prev}" -gt 0 ] && sed -n "${prev}p" "${file}" | grep -q "tenant-gate: allow"; then
      continue
    fi

    # Inspect a 30-line window starting at the select() call.
    window_end=$((lineno + 30))
    window=$(sed -n "${lineno},${window_end}p" "${file}")

    # Check that window mentions tenant_id (filter or .where(User.tenant_id ...) etc.)
    if echo "${window}" | grep -q "tenant_id"; then
      checked=$((checked + 1))
      continue
    fi

    # Special case: superadmin endpoints may legitimately query without tenant_id.
    # We accept if the surrounding function clearly indicates superadmin scope.
    if echo "${window}" | grep -Eq "(is_superadmin|require_superadmin|require_role\(.*superadmin|tenant_id\s*==\s*None|User\.tenant_id\.is_\(None\))"; then
      checked=$((checked + 1))
      continue
    fi

    # Special case: bulk/admin export queries — reviewed and approved per PR.
    if echo "${file}" | grep -Eq "(admin/export|admin/service|audit/superadmin)"; then
      checked=$((checked + 1))
      continue
    fi

    # Otherwise → violation.
    echo "::error file=${file},line=${lineno}::select(${model}) without tenant_id filter (or 'tenant-gate: allow' annotation). See AGENTS.md §Multi-tenancy."
    violations=$((violations + 1))
  done < <(
    grep -rn --include="*.py" "select(${model}\\b" apps/api/app \
      | grep -v "/migrations/" || true
  )
done

echo
echo "tenant-gate summary: ${checked} queries checked, ${violations} violations."

if [ "${violations}" -gt 0 ]; then
  exit 1
fi
