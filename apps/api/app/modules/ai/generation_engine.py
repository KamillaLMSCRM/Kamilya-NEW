"""Single supported course-generation engine contract."""

from __future__ import annotations

from typing import Any

CURRENT_GENERATION_ENGINE = "evidence_v2"
CURRENT_SOURCE_ANALYSIS_MODE = "direct_source"
RETIRED_GENERATION_ENGINE_CODE = "generation_engine_retired"
RETIRED_GENERATION_ENGINE_MESSAGE = (
    "Эта генерация создана старой версией движка и больше не может быть продолжена. "
    "Создайте новую генерацию из исходных документов."
)


def uses_current_generation_engine(source_analysis: object) -> bool:
    """Return true only for the one executable course-generation contract."""
    return bool(
        isinstance(source_analysis, dict)
        and source_analysis.get("generation_engine") == CURRENT_GENERATION_ENGINE
        and source_analysis.get("analysis_mode") == CURRENT_SOURCE_ANALYSIS_MODE
    )


def job_uses_current_generation_engine(job: Any) -> bool:
    """Read the engine contract from durable job parameters."""
    params = job.params if isinstance(getattr(job, "params", None), dict) else {}
    return uses_current_generation_engine(params.get("source_analysis"))
