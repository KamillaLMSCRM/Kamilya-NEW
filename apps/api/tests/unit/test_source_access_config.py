from dataclasses import replace

import pytest

from app.modules.admin.runtime_configuration.catalog import RuntimeSnapshot, default_snapshot, effective_values
from app.modules.ai.v3.source_access_config import BOUNDED_JOINT_EDITOR, checked_settings, pin_settings


@pytest.mark.parametrize(
    "change",
    [
        {"policy": "foreign"},
        {"literal_chars": True},
        {"lookup_rounds": True},
        {"literal_chars": 999},
        {"literal_chars": 120001},
        {"lookup_rounds": 4},
        {"runtime_revision": -1},
        {"runtime_revision": None},
        {"foreign": "instruction"},
        {"joint_editor": "foreign"},
    ],
)
def test_pinned_settings_reject_unsupported_job_config(change):
    value = pin_settings(default_snapshot())
    with pytest.raises(ValueError, match="pinned_settings_invalid"):
        checked_settings({**value, **change})


def test_pin_is_a_copy_and_later_runtime_edits_do_not_change_job_context():
    snapshot = RuntimeSnapshot(7, effective_values({"generation.reference_literal_chars": 5000}))
    pinned = pin_settings(snapshot)
    new = replace(snapshot, revision=8, values=effective_values({"generation.reference_literal_chars": 8000}))
    assert checked_settings(pinned)["literal_chars"] == 5000
    assert pin_settings(new)["literal_chars"] == 8000
    returned = checked_settings(pinned)
    returned["literal_chars"] = 9000
    assert pinned["literal_chars"] == 5000 and pinned["runtime_revision"] == 7


def test_joint_editor_scope_is_pinned_on_admission_without_changing_existing_jobs():
    pinned = pin_settings(default_snapshot())
    assert checked_settings(pinned)["joint_editor"] == BOUNDED_JOINT_EDITOR
    legacy = {key: value for key, value in pinned.items() if key != "joint_editor"}
    assert checked_settings(legacy) == legacy
