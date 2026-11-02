"""Preclaim timing policy; this module does not dispatch or alter job state."""
from __future__ import annotations

import math
import time
from contextvars import ContextVar
from dataclasses import dataclass


class PreclaimYieldError(RuntimeError):
    """A new provider generation has not been claimed or dispatched."""


@dataclass(frozen=True)
class CooperativeBudget:
    deadline: float
    generation_seconds: float = 600.0
    count_seconds: float = 60.0
    safety_seconds: float = 120.0

    @classmethod
    def start(cls, now: float | None = None) -> CooperativeBudget:
        start = time.monotonic() if now is None else now
        if not math.isfinite(start):
            raise ValueError("cooperative_clock_invalid")
        return cls(deadline=start + 1200.0)

    def before_count(self, now: float | None = None, *, generation_seconds: float | None = None) -> None:
        self._require(self.count_seconds + self._generation(generation_seconds) + self.safety_seconds, now)

    def before_claim(self, now: float | None = None, *, generation_seconds: float | None = None) -> None:
        self._require(self._generation(generation_seconds) + self.safety_seconds, now)

    def _generation(self, seconds: float | None) -> float:
        value = self.generation_seconds if seconds is None else seconds
        if isinstance(value, bool) or not math.isfinite(value) or not 0 < value <= 3600:
            raise PreclaimYieldError("generation_deadline_unverified")
        return value

    def _require(self, needed: float, now: float | None) -> None:
        current = time.monotonic() if now is None else now
        if not math.isfinite(current) or not math.isfinite(self.deadline):
            raise PreclaimYieldError("generation_time_budget_unverified")
        if self.deadline - current < needed:
            raise PreclaimYieldError("generation_time_budget_exhausted")


# Installed only by a claimed Celery generation delivery. Completed journal
# replays remain usable after the deadline; only a fresh provider call yields.
active_budget: ContextVar[CooperativeBudget | None] = ContextVar("generation_cooperative_budget", default=None)
