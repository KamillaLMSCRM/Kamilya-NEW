import importlib.util
from pathlib import Path


def load_gate():
    path = Path(__file__).resolve().parents[1] / 'autonomous_editorial_acceptance_dev_gate.py'
    spec = importlib.util.spec_from_file_location('autonomous_acceptance_gate', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_no_dry_run_or_missing_guard_can_be_a_pass():
    gate = load_gate()
    all_checks = {name: True for name in gate.REQUIRED_CHECKS}
    assert gate.assess(all_checks, executed=False, cleanup_verified=True, public_unchanged=True)['status'] == 'BLOCKED'
    assert gate.assess(all_checks, executed=True, cleanup_verified=False, public_unchanged=True)['status'] == 'BLOCKED'
    assert gate.assess(all_checks, executed=True, cleanup_verified=True, public_unchanged=False)['status'] == 'BLOCKED'
    all_checks['foreign_tenant_and_foreign_job_denied'] = False
    outcome = gate.assess(all_checks, executed=True, cleanup_verified=True, public_unchanged=True)
    assert outcome['status'] == 'BLOCKED' and 'foreign_tenant_and_foreign_job_denied' in outcome['missing_checks']


def test_complete_explicit_evidence_is_required():
    gate = load_gate()
    checks = {name: True for name in gate.REQUIRED_CHECKS}
    assert gate.assess(checks, executed=True, cleanup_verified=True, public_unchanged=True)['status'] == 'PASS'
    checks['source_and_content_edits_invalidate_receipt'] = 1
    assert gate.assess(checks, executed=True, cleanup_verified=True, public_unchanged=True)['status'] == 'BLOCKED'


def test_only_real_lock_timeout_sqlstate_counts():
    from types import SimpleNamespace
    gate = load_gate()
    assert gate.is_lock_timeout(SimpleNamespace(orig=SimpleNamespace(sqlstate='55P03')))
    assert gate.is_lock_timeout(SimpleNamespace(orig=SimpleNamespace(sqlstate=None, __cause__=SimpleNamespace(sqlstate='55P03'))))
    assert not gate.is_lock_timeout(SimpleNamespace(orig=SimpleNamespace(sqlstate='57014')))
