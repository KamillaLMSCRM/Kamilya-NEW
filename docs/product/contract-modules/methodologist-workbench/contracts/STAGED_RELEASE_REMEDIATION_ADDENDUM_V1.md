# Staged release remediation addendum V1

Accepted by root2026-10-02 BEFORE correction of CI36969240393 candidate9480fe20.
Current owner request remains bounded staged release to production. No public
schema/provider/runtime mutation has occurred. Original failed evidence is retained.

## Exact changes and unaffected contracts

1. Unapplied169/172 migration modules must expose revision metadata to Alembic
   without importing application packages at catalog-load time. Lazily import
   the existing shared bootstrap installer only at execution. Preserve the
   callable seam, SQL bytes, schema validation, ownership/ACL and revision chain.
   Isolated subprocess with no application import path must discover one head172;
   existing captured-SQL equivalence and actual owned74 runtime must remain green.
   Do not weaken KB-RAG catalog checks or inject ambient path into their callers.
2. CI image dependency audit reports7 advisories on pypdf6.17.0, all fixed by
   6.19.0. Pin pyproject, exact lock and requirements to6.19.0, updating ONLY that
   package's metadata/hash and lock content hash. Verify upstream release and
   advisories, regress extraction/PDF export/certificates and repeat blocking
   production image graph audit. No new dependency or audit suppression.
3. Existing native frontend build must explicitly pass
   NEXT_PUBLIC_METHODOLOGIST_WORKBENCH_ENABLED=false for compatibility A and
   record this false value in its immutable manifest. No alternate builder,
   controller, provider tier/resource, backend release-plane change or implicit
   feature activation. Confirm manifest inspection accepts/preserves extra evidence.

## Release gate

Independent focused acceptance of changed scope, same SQL/runtime behavior,
version0.11.26, new immutable source SHA and all7CI gates. Previous765frontend
result may be carried as unchanged product/test evidence, but native bundle must
be built from the new exact SHA. DEV flags configured/read back explicitly via
existing provider configuration seam by root; provider deployment still owned by
canonical controller. Actual API disabled404 before DB, every worker startup,
QA preservation and final169 receipt are required before contract172. Production
controller/protected runner/backup/readbacks remain mandatory. No release GO here.
