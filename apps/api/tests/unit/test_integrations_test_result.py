from datetime import UTC

from app.modules.integrations.schemas import TestResult as IntegrationTestResult


def test_integration_test_result_adds_timestamp_when_endpoint_omits_it() -> None:
    result = IntegrationTestResult.model_validate({"ok": True, "detail": "bot: @example_bot"})

    assert result.ok is True
    assert result.timestamp.tzinfo == UTC
