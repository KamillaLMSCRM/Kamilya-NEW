"""Onboarding status — P0.6 first-tenant hardening.

A single endpoint that tells a tenant admin "what's left to do before
the first paying user gets value out of the LMS".

Each step is a boolean derived from real DB state, not a checklist
the user has to tick manually — that way the dashboard reflects truth.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class OnboardingStep(BaseModel):
    """A single onboarding step with status and link.

    `done` is true once the underlying state satisfies the step.
    `href` is the URL the admin lands on to complete the step.
    """

    id: Literal[
        "team",
        "staff_import",
        "documents",
        "first_course",
        "first_assignment",
        "invitation",
        "training_log",
    ]
    label: str
    done: bool
    href: str
    # Optional context: number of users, courses etc. for the step badge.
    badge: str | None = None
    # Ownership is explicit so each role sees only the work it can complete.
    owner: Literal["admin", "methodologist"] = "methodologist"

    model_config = ConfigDict(extra="forbid")


class OnboardingStatus(BaseModel):
    """Overall onboarding status for the current tenant."""

    steps: list[OnboardingStep]
    # All steps done?
    completed: bool = False
    # Trial window info — surfaces the deadline so the user knows
    # when the free tier ends.
    trial_ends_at: str | None = None
    trial_days_remaining: int | None = None
    plan: str | None = None
    max_users: int | None = None
    active_users: int | None = None
    role: Literal["admin", "methodologist", "superadmin"] | None = None
    trial_state: Literal["active", "nearing_expiry", "expired", "not_trial"] = "not_trial"
    trial_access_state: Literal["available", "limited", "support_required", "not_applicable"] = "not_applicable"
    trial_exhausted_limits: list[str] = Field(default_factory=list)
    trial_usage: dict[str, dict[str, int | None]] = Field(default_factory=dict)


class OnboardingMessage(BaseModel):
    """Empty Pydantic wrapper for i18n strings the frontend can display."""

    title: str = "Подготовка к обучению"
    subtitle: str = "Пройдите эти шаги — каждый шаг помогает сотрудникам быстрее получить пользу от LMS."

    model_config = ConfigDict(extra="forbid")
