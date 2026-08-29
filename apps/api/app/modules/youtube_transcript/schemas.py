"""YouTube transcript API schemas with Russian user-facing states."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.modules.youtube_transcript.url_resolver import YouTubeVideoRef, extract_video_id

YouTubeImportStatus = Literal["pending", "ready", "failed"]


class YouTubeImportRequest(BaseModel):
    """Create a transcript-backed course source from a YouTube URL."""

    url: str = Field(min_length=1, max_length=2048)
    preferred_languages: list[str] = Field(default_factory=lambda: ["ru"], max_length=5)

    def validated_video_ref(self) -> YouTubeVideoRef:
        return extract_video_id(self.url)


class TranscriptProvenanceOut(BaseModel):
    source_type: str
    provider: str
    video_id: str
    canonical_url: str
    title: str
    channel: str | None = None
    language: str
    is_auto_generated: bool
    duration_seconds: float | None = None
    segment_count: int = Field(ge=0)
    retrieved_at: datetime
    content_sha256: str


class YouTubeImportErrorOut(BaseModel):
    code: str
    retryable: bool
    message_ru: str


class YouTubeImportAccepted(BaseModel):
    """202-style ack with status polling contract."""

    status: Literal["pending"] = "pending"
    job_id: str
    status_url: str
    video_id: str
    canonical_url: str


class YouTubeImportStatusOut(BaseModel):
    """Tenant-scoped polling response for one transcript import."""

    job_id: str
    status: YouTubeImportStatus
    stage: str
    progress: int = Field(ge=0, le=100)
    message: str = ""
    video_id: str
    canonical_url: str
    document_id: UUID | None = None
    indexing_job_id: str | None = None
    idempotent_reuse: bool = False
    provenance: TranscriptProvenanceOut | None = None
    error: YouTubeImportErrorOut | None = None


class YouTubeAnalysisAccepted(BaseModel):
    status: Literal["pending"] = "pending"
    job_id: str
    status_url: str
    video_id: str
    canonical_url: str


class YouTubePreviewOut(BaseModel):
    title: str
    channel: str | None = None
    summary: str = Field(min_length=1, max_length=360)
    language: str
    is_auto_generated: bool
    duration_seconds: float | None = None
    recommended_course_format: Literal["brief", "standard", "detailed"]
    quality_warnings: list[str] = Field(default_factory=list)


class YouTubeAnalysisStatusOut(BaseModel):
    job_id: str
    status: YouTubeImportStatus
    stage: str
    progress: int = Field(ge=0, le=100)
    message: str = ""
    video_id: str
    canonical_url: str
    preview: YouTubePreviewOut | None = None
    error: YouTubeImportErrorOut | None = None


class YouTubeAnalysisConfirmRequest(BaseModel):
    action: Literal["create_course", "save_captions"]


class YouTubeAnalysisConfirmAccepted(YouTubeImportAccepted):
    action: Literal["create_course", "save_captions"]
