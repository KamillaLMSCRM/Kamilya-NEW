from app.modules.training_responsibility.policy import ReportingScopeMode, decide_reporting_scope


def test_tenant_administrators_always_keep_tenant_wide_reporting() -> None:
    assert decide_reporting_scope("admin", has_responsibilities=True) is ReportingScopeMode.TENANT
    assert decide_reporting_scope("superadmin", has_responsibilities=True) is ReportingScopeMode.TENANT


def test_methodologist_scope_is_backward_compatible_but_explicit_when_configured() -> None:
    assert decide_reporting_scope("methodologist", has_responsibilities=False) is ReportingScopeMode.TENANT
    assert decide_reporting_scope("methodologist", has_responsibilities=True) is ReportingScopeMode.RESTRICTED


def test_unprivileged_role_never_gains_reporting_from_the_policy() -> None:
    assert decide_reporting_scope("student", has_responsibilities=False) is ReportingScopeMode.DENIED
    assert decide_reporting_scope("student", has_responsibilities=True) is ReportingScopeMode.DENIED
