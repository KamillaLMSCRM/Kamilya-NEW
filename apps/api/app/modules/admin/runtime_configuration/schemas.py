"""Strict admin write commands; values are further checked by the closed catalog."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, StrictInt


class SettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: StrictInt = Field(ge=1)
    changes: dict[str, Any] = Field(min_length=1, max_length=50)
    reason: str = Field(min_length=3, max_length=240)


class SettingsRevert(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: StrictInt = Field(ge=1)
    target_revision: StrictInt = Field(ge=1)
    reason: str = Field(min_length=3, max_length=240)
