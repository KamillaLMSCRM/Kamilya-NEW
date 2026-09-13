from pathlib import Path
import subprocess
import sys


SCRIPT = Path(__file__).with_name("ct137_native_deploy.py")


def test_verify_boundary_requires_rollback_sha_without_traceback() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--verify-boundary"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "--expected-rollback-sha is required" in result.stderr
    assert "Traceback" not in result.stderr
