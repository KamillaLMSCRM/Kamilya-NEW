"""HTTP orchestration contracts for YouTube import. No network or database."""

import hashlib
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.modules.youtube_transcript import operations
from app.modules.youtube_transcript import router as youtube_router
from app.modules.youtube_transcript.schemas import YouTubeAnalysisConfirmRequest, YouTubeImportRequest
from app.modules.youtube_transcript.url_resolver import YouTubeURLValidationError


class FakeDB:
    def __init__(self):
        self.commits = 0

    async def commit(self):
        self.commits += 1


def _enabled(monkeypatch):
    monkeypatch.setattr(
        youtube_router,
        "get_settings",
        lambda: SimpleNamespace(
            YOUTUBE_IMPORT_ENABLED=True,
            YOUTUBE_MAX_VIDEO_DURATION_SECONDS=7200,
            YOUTUBE_MAX_TOTAL_CHARS=500_000,
        ),
    )


@pytest.mark.asyncio
async def test_eager_analysis_dispatch_uses_current_event_loop(monkeypatch):
    from app.modules.youtube_transcript import operations, tasks

    calls = []
    monkeypatch.setattr(
        youtube_router,
        "get_settings",
        lambda: SimpleNamespace(
            YOUTUBE_INLINE_EXECUTION=True,
            DEPLOYMENT_ENVIRONMENT="render-development",
        ),
    )
    async def fake_run(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(operations, "run_youtube_analysis", fake_run)
    monkeypatch.setattr(
        tasks.youtube_analyze_task,
        "apply_async",
        lambda **kwargs: pytest.fail("eager dispatch must not use the broker"),
    )

    await youtube_router._dispatch_youtube_analysis(
        job_id="youtube-job-1",
        tenant_id=uuid4(),
        url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        languages=["ru"],
    )

    assert calls[0]["job_id"] == "youtube-job-1"
    assert calls[0]["preferred_languages"] == ["ru"]


def test_inline_execution_is_rejected_outside_render_development(monkeypatch):
    monkeypatch.setattr(
        youtube_router,
        "get_settings",
        lambda: SimpleNamespace(
            YOUTUBE_INLINE_EXECUTION=True,
            DEPLOYMENT_ENVIRONMENT="production",
        ),
    )

    with pytest.raises(RuntimeError, match="restricted to render-development"):
        youtube_router._youtube_inline_execution_enabled()


def test_request_schema_validates_url_canonically():
    request = YouTubeImportRequest(url="https://youtu.be/dQw4w9WgXcQ")
    assert request.validated_video_ref().video_id == "dQw4w9WgXcQ"


def test_request_schema_rejects_disallowed_host():
    request = YouTubeImportRequest(url="https://evil.example.com/watch?v=dQw4w9WgXcQ")
    with pytest.raises(YouTubeURLValidationError):
        request.validated_video_ref()


@pytest.mark.asyncio
async def test_import_endpoint_rejects_invalid_url_before_job(monkeypatch):
    _enabled(monkeypatch)
    called = False

    async def fake_create(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(youtube_router, "create_ai_job", fake_create)
    with pytest.raises(YouTubeURLValidationError):
        await youtube_router.import_youtube_transcript(
            YouTubeImportRequest(url="https://127.0.0.1/watch?v=dQw4w9WgXcQ"),
            db=FakeDB(),
            user=SimpleNamespace(id=uuid4(), tenant_id=uuid4()),
        )
    assert called is False


@pytest.mark.asyncio
async def test_import_endpoint_persists_job_before_dispatch(monkeypatch):
    _enabled(monkeypatch)
    db = FakeDB()
    dispatched = []

    async def fake_create(*args, **kwargs):
        return SimpleNamespace(id="youtube-job-1")

    monkeypatch.setattr(youtube_router, "create_ai_job", fake_create)
    monkeypatch.setattr(youtube_router, "_dispatch_youtube_import", AsyncMock(side_effect=lambda **kwargs: dispatched.append(kwargs)))
    response = await youtube_router.import_youtube_transcript(
        YouTubeImportRequest(url="https://youtu.be/dQw4w9WgXcQ", preferred_languages=["ru", "ru"]),
        db=db,
        user=SimpleNamespace(id=uuid4(), tenant_id=uuid4()),
    )
    assert db.commits == 1
    assert response.job_id == "youtube-job-1"
    assert response.status_url == "/api/v1/youtube/imports/youtube-job-1"
    assert dispatched[0]["languages"] == ["ru"]


@pytest.mark.asyncio
async def test_analysis_endpoint_does_not_create_a_document_before_confirmation(monkeypatch):
    _enabled(monkeypatch)
    db = FakeDB()
    created_params = []
    dispatched = []

    async def fake_create(*args, **kwargs):
        created_params.append(kwargs["params"])
        return SimpleNamespace(id="youtube-analysis-1")

    monkeypatch.setattr(youtube_router, "create_ai_job", fake_create)
    monkeypatch.setattr(youtube_router, "_dispatch_youtube_analysis", AsyncMock(side_effect=lambda **kwargs: dispatched.append(kwargs)))

    response = await youtube_router.analyze_youtube_transcript(
        YouTubeImportRequest(url="https://youtu.be/dQw4w9WgXcQ", preferred_languages=["ru"]),
        db=db,
        user=SimpleNamespace(id=uuid4(), tenant_id=uuid4()),
    )

    assert created_params == [{
        "action": "youtube_analysis",
        "video_id": "dQw4w9WgXcQ",
        "canonical_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "preferred_languages": ["ru"],
    }]
    assert response.status_url == "/api/v1/youtube/analyses/youtube-analysis-1"
    assert dispatched and db.commits == 1


class ConfirmDB(FakeDB):
    def __init__(self, analysis):
        super().__init__()
        self.analysis = analysis

    async def scalar(self, statement):
        return self.analysis


@pytest.mark.asyncio
async def test_confirmation_is_single_use_and_dispatches_the_existing_import_path(monkeypatch):
    tenant_id = uuid4()
    analysis = SimpleNamespace(
        id="youtube-analysis-1",
        tenant_id=tenant_id,
        status="completed",
        completed_at=datetime.now(UTC),
        params={
            "action": "youtube_analysis",
            "video_id": "dQw4w9WgXcQ",
            "canonical_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "preferred_languages": ["ru"],
        },
        result={"preview": {"title": "Видео"}},
    )
    db = ConfirmDB(analysis)
    dispatched = []

    async def fake_create(*args, **kwargs):
        return SimpleNamespace(id="youtube-import-1")

    monkeypatch.setattr(youtube_router, "create_ai_job", fake_create)
    monkeypatch.setattr(youtube_router, "_dispatch_youtube_import", AsyncMock(side_effect=lambda **kwargs: dispatched.append(kwargs)))

    response = await youtube_router.confirm_youtube_analysis(
        analysis.id,
        YouTubeAnalysisConfirmRequest(action="create_course"),
        db=db,
        user=SimpleNamespace(id=uuid4(), tenant_id=tenant_id),
    )

    assert response.job_id == "youtube-import-1"
    assert response.action == "create_course"
    assert analysis.result["confirmation_job_id"] == "youtube-import-1"
    assert dispatched[0]["url"] == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert dispatched[0]["analysis_job_id"] == analysis.id

    with pytest.raises(Exception) as exc:
        await youtube_router.confirm_youtube_analysis(
            analysis.id,
            YouTubeAnalysisConfirmRequest(action="create_course"),
            db=db,
            user=SimpleNamespace(id=uuid4(), tenant_id=tenant_id),
        )
    assert getattr(exc.value, "status_code", None) == 409
    assert exc.value.detail["code"] == "analysis_already_confirmed"


@pytest.mark.asyncio
async def test_status_endpoint_rejects_non_youtube_job(monkeypatch):
    async def fake_get(*args, **kwargs):
        return None

    monkeypatch.setattr(
        youtube_router,
        "get_ai_job",
        fake_get,
    )
    with pytest.raises(Exception) as exc:
        await youtube_router.get_youtube_import(
            "missing",
            db=FakeDB(),
            user=SimpleNamespace(tenant_id=uuid4()),
        )
    assert getattr(exc.value, "status_code", None) == 404


def test_feature_flag_defaults_off():
    from app.core.config import Settings

    settings = Settings(JWT_SECRET="x" * 48)
    assert settings.YOUTUBE_IMPORT_ENABLED is False


class ArtifactStorage:
    def __init__(self, payload=None):
        self.payload = payload
        self.reads = 0

    def get_bytes(self, key):
        self.reads += 1
        if self.payload is None:
            raise KeyError(key)
        return self.payload


@pytest.mark.parametrize(
    "payload, digest",
    [
        (b"{}", hashlib.sha256(b"{}").hexdigest()),
        (b"{}", "0" * 64),
        (
            json.dumps(
                {
                    "version": 1,
                    "tenant_id": str(uuid4()),
                    "analysis_job_id": "analysis-1",
                    "expires_at": "2099-01-01T00:00:00+00:00",
                    "video_id": "dQw4w9WgXcQ",
                    "canonical_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                    "language": "ru",
                    "content_sha256": "0" * 64,
                    "document": {},
                },
                sort_keys=True,
            ).encode(),
            None,
        ),
    ],
)
def test_confirmed_import_artifact_fail_closed(payload, digest):
    if digest is None:
        digest = hashlib.sha256(payload).hexdigest()
    with pytest.raises(operations.YouTubeAnalysisArtifactError):
        operations._load_analysis_artifact(
            storage=ArtifactStorage(payload),
            artifact_key="tenants/tenant/youtube-analysis/analysis-1.json",
            artifact_sha256=digest,
            tenant_id=uuid4(),
            analysis_job_id="analysis-1",
            expected_video_id="dQw4w9WgXcQ",
            expected_canonical_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            expected_preferred_languages=["ru"],
        )


def test_confirmed_import_missing_artifact_fails_closed():
    with pytest.raises(operations.YouTubeAnalysisArtifactError):
        operations._load_analysis_artifact(
            storage=ArtifactStorage(),
            artifact_key="tenants/tenant/youtube-analysis/analysis-1.json",
            artifact_sha256="0" * 64,
            tenant_id=uuid4(),
            analysis_job_id="analysis-1",
            expected_video_id="dQw4w9WgXcQ",
            expected_canonical_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            expected_preferred_languages=["ru"],
        )


def test_confirmed_import_rejects_non_scoped_artifact_key_before_storage_read():
    storage = ArtifactStorage(b"not-read")
    tenant_id = uuid4()
    with pytest.raises(operations.YouTubeAnalysisArtifactError):
        operations._load_analysis_artifact(
            storage=storage,
            artifact_key="tenants/other/youtube-analysis/analysis-1.json",
            artifact_sha256="0" * 64,
            tenant_id=tenant_id,
            analysis_job_id="analysis-1",
            expected_video_id="dQw4w9WgXcQ",
            expected_canonical_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            expected_preferred_languages=["ru"],
        )
    assert storage.reads == 0


def test_confirmed_import_artifact_language_mismatch_fails_closed():
    from uuid import UUID

    tenant_id = uuid4()
    plain_text = "# Video\n\nContent"
    content_sha256 = hashlib.sha256(plain_text.encode()).hexdigest()
    payload = json.dumps(
        {
            "version": 1,
            "tenant_id": str(tenant_id),
            "analysis_job_id": "analysis-1",
            "expires_at": "2099-01-01T00:00:00+00:00",
            "video_id": "dQw4w9WgXcQ",
            "canonical_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "language": "kk",
            "content_sha256": content_sha256,
            "document": {
                "title": "Video",
                "filename": "youtube-dQw4w9WgXcQ-kk.md",
                "content_type": "text/markdown",
                "plain_text": plain_text,
                "source_revision": f"document:{content_sha256}",
                "content_sha256": content_sha256,
                "provenance": {"language": "kk"},
            },
        },
        sort_keys=True,
    ).encode()
    with pytest.raises(operations.YouTubeAnalysisArtifactError):
        operations._load_analysis_artifact(
            storage=ArtifactStorage(payload),
            artifact_key=f"tenants/{tenant_id}/youtube-analysis/analysis-1.json",
            artifact_sha256=hashlib.sha256(payload).hexdigest(),
            tenant_id=UUID(str(tenant_id)),
            analysis_job_id="analysis-1",
            expected_video_id="dQw4w9WgXcQ",
            expected_canonical_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            expected_preferred_languages=["ru"],
        )
