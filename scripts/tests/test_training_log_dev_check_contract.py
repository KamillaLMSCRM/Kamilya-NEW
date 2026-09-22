from pathlib import Path


def test_training_log_dev_gate_requires_explicit_revision_and_current_model_columns():
    source = (Path(__file__).parents[1] / "ops" / "training_log_dev_check.py").read_text(encoding="utf-8")

    assert '"--expected-revision"' in source
    assert '"expected_revision_required"' in source
    assert "revision != [expected_revision]" in source
    assert "organization_unit_id" in source
    assert "is_head_office" in source
    assert "len(columns) != 4" in source
