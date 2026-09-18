"""Development-only semantic evaluation for frozen course artifacts.

This package is intentionally located under ``scripts/dev``.  Production API
and web runtimes must not import it.
"""

from .adapters import CacheMissError, CachedEvaluator, TypeSafeHTTPAdapter
from .artifact import load_artifact
from .domain import AdapterResult, EvaluationRequest, PrivacyViolation
from .evaluator import evaluate_generation
from .report import render_markdown, write_report
from .rubric import DEFAULT_RUBRIC

__all__ = [
    "DEFAULT_RUBRIC",
    "AdapterResult",
    "CacheMissError",
    "CachedEvaluator",
    "EvaluationRequest",
    "PrivacyViolation",
    "TypeSafeHTTPAdapter",
    "evaluate_generation",
    "load_artifact",
    "render_markdown",
    "write_report",
]
