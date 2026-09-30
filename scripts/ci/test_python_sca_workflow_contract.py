from __future__ import annotations

import tomllib
from pathlib import Path


WORKFLOW = Path(__file__).parents[2] / ".github" / "workflows" / "ci.yml"


def test_pyjwt_runtime_and_lock_pin_the_verified_security_release() -> None:
    api = WORKFLOW.parents[2] / "apps" / "api"
    project = tomllib.loads((api / "pyproject.toml").read_text(encoding="utf-8"))
    lock = tomllib.loads((api / "poetry.lock").read_text(encoding="utf-8"))
    assert project["tool"]["poetry"]["dependencies"]["pyjwt"] == "2.14.0"
    package = next(item for item in lock["package"] if item["name"] == "pyjwt")
    assert package["version"] == "2.14.0"
    assert "pyjwt==2.14.0" in (api / "requirements.txt").read_text(encoding="utf-8").splitlines()


def test_python_sca_is_a_blocking_image_graph_derived_production_gate() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "python-sca:" in source
    job = source.split("  python-sca:", 1)[1].split("\n  backend-unit:", 1)[0]
    assert "poetry-plugin-export==1.8.0" in job
    assert "pip-audit==2.10.1" in job
    assert "poetry export" in job
    assert "--with observability" in job
    assert "--without dev" in job
    assert "--only main" not in job
    assert "--without-hashes" in job
    assert "--skip-editable" in job
    assert "--progress-spinner off" in job
    assert "--ignore-vuln" not in job
    assert "continue-on-error" not in job
    assert "|| true" not in job
