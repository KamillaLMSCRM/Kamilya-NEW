# LI-API model discovery addendum

Status: Accepted; Approved by: root within implementation authority; 2026-09-06.
Extends EPIC_V1 without superseding its user-facing contract.

Evidence: Alembic env.py loads model tables only via app/models/registry.py.
Root additionally owns one additive MODEL_MODULES registration in that file.
No existing model module is removed. Verify load_all_models and migration contracts.
Root verification scope includes scripts/ops/learning_insights_dev_check.py and
apps/api/tests/integration/test_learning_insights_db.py for disposable DEV checks.
Dependency setup uses existing installed node_modules through worktree junctions;
no package/lockfile or shared dependency modification is authorized.

Root additionally owns the affected `apps/web/tests/trainingLogDeadlineView.test.tsx`
fixture correction: its translation mock must retain the same function identity
as the real useT hook, and its API mock acknowledges the new catalog request.
No deadline assertions are removed or weakened. The isolated legacy-row test
reproduced a request/render loop before this correction and passed afterward.
