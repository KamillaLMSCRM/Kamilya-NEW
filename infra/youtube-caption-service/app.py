"""Small authenticated service for retrieving public YouTube captions."""

from __future__ import annotations

import asyncio
import os
import re
import secrets
import time
from collections import deque
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field
from youtube_transcript_api import (
    IpBlocked,
    NoTranscriptFound,
    RequestBlocked,
    TranscriptsDisabled,
    VideoUnavailable,
    YouTubeRequestFailed,
    YouTubeTranscriptApi,
)

SERVICE_TOKEN = os.environ.get("CAPTION_SERVICE_TOKEN", "")
if len(SERVICE_TOKEN) < 32:
    raise RuntimeError("CAPTION_SERVICE_TOKEN must contain at least 32 characters")

VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
SUPPORTED_LANGUAGES = {"ru", "kk", "en"}
MAX_REQUESTS_PER_MINUTE = 30
PROVIDER_TIMEOUT_SECONDS = 20.0

app = FastAPI(title="Kamilya caption relay", docs_url=None, redoc_url=None, openapi_url=None)
_provider_slots = asyncio.Semaphore(2)
_recent_requests: deque[float] = deque()
_rate_lock = asyncio.Lock()


class TranscriptRequest(BaseModel):
    video_id: str = Field(min_length=11, max_length=11)
    languages: list[str] = Field(default_factory=lambda: ["ru"], min_length=1, max_length=3)


async def require_token(authorization: Annotated[str | None, Header()] = None) -> None:
    prefix = "Bearer "
    supplied = authorization[len(prefix):] if authorization and authorization.startswith(prefix) else ""
    if not supplied or not secrets.compare_digest(supplied, SERVICE_TOKEN):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail={"code": "unauthorized"})


async def enforce_rate_limit() -> None:
    now = time.monotonic()
    async with _rate_lock:
        while _recent_requests and _recent_requests[0] <= now - 60:
            _recent_requests.popleft()
        if len(_recent_requests) >= MAX_REQUESTS_PER_MINUTE:
            raise HTTPException(status_code=429, detail={"code": "provider_unavailable"})
        _recent_requests.append(now)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "kamilya-caption-relay"}


@app.post("/v1/transcripts", dependencies=[Depends(require_token), Depends(enforce_rate_limit)])
async def transcript(request: TranscriptRequest) -> dict:
    if not VIDEO_ID_RE.fullmatch(request.video_id):
        raise HTTPException(status_code=422, detail={"code": "invalid_video_id"})
    languages = list(dict.fromkeys(code.lower() for code in request.languages))
    if any(code not in SUPPORTED_LANGUAGES for code in languages):
        raise HTTPException(status_code=422, detail={"code": "language_unavailable"})

    try:
        async with _provider_slots:
            fetched = await asyncio.wait_for(
                asyncio.to_thread(
                    YouTubeTranscriptApi().fetch,
                    request.video_id,
                    languages=languages,
                    preserve_formatting=False,
                ),
                timeout=PROVIDER_TIMEOUT_SECONDS,
            )
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail={"code": "provider_timeout"}) from exc
    except (RequestBlocked, IpBlocked) as exc:
        raise HTTPException(status_code=503, detail={"code": "provider_blocked"}) from exc
    except (TranscriptsDisabled, NoTranscriptFound) as exc:
        raise HTTPException(status_code=404, detail={"code": "transcript_unavailable"}) from exc
    except VideoUnavailable as exc:
        raise HTTPException(status_code=404, detail={"code": "video_unavailable"}) from exc
    except YouTubeRequestFailed as exc:
        raise HTTPException(status_code=503, detail={"code": "provider_unavailable"}) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail={"code": "provider_unavailable"}) from exc

    segments = []
    for item in fetched.to_raw_data():
        text = str(item.get("text", "")).strip()
        if not text:
            continue
        start = float(item.get("start", 0.0))
        duration = float(item.get("duration", 0.0))
        segments.append({"start": start, "end": start + duration, "text": text})
    if not segments:
        raise HTTPException(status_code=404, detail={"code": "transcript_unavailable"})
    if len(segments) > 50_000 or sum(len(item["text"]) for item in segments) > 500_000:
        raise HTTPException(status_code=413, detail={"code": "transcript_too_large"})

    return {
        "video_id": request.video_id,
        "title": f"Видео {request.video_id}",
        "channel": None,
        "language": fetched.language_code,
        "is_auto_generated": fetched.is_generated,
        "duration_seconds": segments[-1]["end"],
        "segments": segments,
    }
