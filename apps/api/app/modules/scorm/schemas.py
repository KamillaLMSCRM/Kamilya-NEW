from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ScormPackageResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    course_id: UUID
    version: Literal["scorm_1_2", "scorm_2004", "unknown"]
    title: str
    entrypoint: str
    storage_key: str
    manifest_json: dict[str, Any]
    uploaded_by: UUID | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ScormImportResponse(BaseModel):
    course_id: UUID
    package: ScormPackageResponse


class ScormLaunchInfo(BaseModel):
    course_id: UUID
    package_id: UUID
    launch_url: str
    version: Literal["scorm_1_2"]
    title: str


class ScormCommitRequest(BaseModel):
    cmi: dict[str, Any]


class ScormCommitResponse(BaseModel):
    status: str
    attempt_id: UUID
    completed: bool = False
    certificate_id: str | None = None
    certificate_number: str | None = None
