"""Purpose-bound step-up authentication contracts."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class StepUpChallengeRequest(BaseModel):
    """An empty request; confirmation data comes from the immutable event."""

    model_config = ConfigDict(extra="forbid")


class StepUpChallengeResponse(BaseModel):
    challenge_id: str
    event_id: UUID
    expires_in: int
    retry_after: int | None = None


class StepUpVerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    challenge_id: str = Field(min_length=16, max_length=128)
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class StepUpVerifyResponse(BaseModel):
    confirmed: bool
    confirmation_id: UUID
