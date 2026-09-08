from __future__ import annotations

import re
import tomllib
from pathlib import Path

_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
_API_ROOT = Path(__file__).resolve().parents[2]
_PYPROJECT = _API_ROOT / "pyproject.toml"


def _read_product_version() -> str:
    data = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    value = data.get("tool", {}).get("poetry", {}).get("version")
    if not isinstance(value, str) or _SEMVER_RE.fullmatch(value) is None:
        raise RuntimeError("API product version is missing or invalid")
    return value


PRODUCT_VERSION = _read_product_version()
