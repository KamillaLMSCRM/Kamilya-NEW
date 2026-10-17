"""No-secret, no-network tests for the destructive DEV maintenance boundary."""

import hashlib
import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))
SPEC = importlib.util.spec_from_file_location("staff_structure_dev_retention", OPS / "staff_structure_dev_retention.py")
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


@pytest.mark.parametrize("environment", [None, "production", "prod", "staging"])
def test_non_dev_label_is_rejected_before_any_connection_or_config_resolution(tmp_path, environment):
    env_file = tmp_path / ".env.dev"  # A misleading filename grants no authority.
    env_file.write_text(f"APP_ENV={environment}\n" if environment else "", encoding="utf-8")
    with patch.object(module, "canonical_config") as canonical, patch.object(module, "create_async_engine") as connect:
        with pytest.raises(ValueError, match="dev_environment_required"):
            module.dev_config(env_file)
        canonical.assert_not_called()
        connect.assert_not_called()


def test_matching_urls_in_another_project_are_not_canonical_dev(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("APP_ENV=development\n", encoding="utf-8")
    with patch.object(module, "canonical_config", return_value={"supabase_url": "https://foreignproject.supabase.co"}), \
         patch.object(module, "create_async_engine") as connect:
        with pytest.raises(ValueError, match="canonical_dev_project_required"):
            module.dev_config(env_file)
        connect.assert_not_called()


def test_mismatched_owner_runtime_project_is_not_overridden_by_dev_label(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("APP_ENV=test\n", encoding="utf-8")
    with patch.object(module, "canonical_config", side_effect=ValueError("canonical_dev_identity_mismatch")), \
         patch.object(module, "create_async_engine") as connect:
        with pytest.raises(ValueError, match="canonical_dev_identity_mismatch"):
            module.dev_config(env_file)
        connect.assert_not_called()


def test_explicit_dev_label_and_exact_identity_are_both_required(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("APP_ENV=dev\n", encoding="utf-8")
    synthetic = {"supabase_url": "https://syntheticdev.supabase.co"}
    digest = hashlib.sha256(b"syntheticdev").hexdigest()
    with patch.object(module, "canonical_config", return_value=synthetic), \
         patch.object(module, "DEV_PROJECT_REF_SHA256", digest):
        assert module.dev_config(env_file) == synthetic
