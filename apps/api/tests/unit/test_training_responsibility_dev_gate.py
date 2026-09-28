from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[4] / "scripts" / "ops" / "training_responsibility_dev_gate.py"
if str(SCRIPT.parent) not in sys.path:
    sys.path.insert(0, str(SCRIPT.parent))
SPEC = importlib.util.spec_from_file_location("training_responsibility_dev_gate", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_main_loads_explicit_env_before_importing_application_scope(monkeypatch, tmp_path) -> None:
    env_file = tmp_path / "dev.env"
    env_file.write_text("APP_ENV=test\n", encoding="utf-8")
    observed: list[tuple[Path, bool]] = []

    monkeypatch.setattr(
        MODULE,
        "load_dotenv",
        lambda path, *, override: observed.append((Path(path), override)),
    )
    monkeypatch.setattr(
        MODULE,
        "dotenv_values",
        lambda _path: {
            "MIGRATION_DATABASE_URL": "postgresql://owner@example.test/postgres",
            "DATABASE_URL": "postgresql://lms_app@example.test/postgres",
            "SUPABASE_URL": "https://example.test",
        },
    )

    async def fake_run_gate(*_args):
        assert observed == [(env_file, True)]
        return {"status": "PASSED"}

    monkeypatch.setattr(MODULE, "run_gate", fake_run_gate)
    monkeypatch.setattr(
        sys,
        "argv",
        [str(SCRIPT), "--env-file", str(env_file), "--execute"],
    )

    assert MODULE.main() == 0
