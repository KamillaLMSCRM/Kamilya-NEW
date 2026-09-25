from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
RENDER_REQUIREMENTS = REPO_ROOT / "apps" / "api" / "requirements.txt"


def test_render_installs_sqlalchemy_asyncio_runtime() -> None:
    requirements = {
        line.strip().lower()
        for line in RENDER_REQUIREMENTS.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert any(line.startswith("sqlalchemy[asyncio]") for line in requirements), (
        "Render starts SQLAlchemy's asyncio extension, so its independent "
        "requirements.txt must request the asyncio extra (and greenlet) explicitly"
    )
