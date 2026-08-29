"""Canonical YouTube URL parsing, allowlist, and SSRF guards.

Only normalized `https` URLs on allowed YouTube hosts are accepted. Private
IP literals, localhost, credentials in URL, non-http schemes, and non-canonical
hosts are rejected before any network boundary could be reached.
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

ALLOWED_HOSTS = frozenset(
    {
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "music.youtube.com",
        "youtu.be",
        "www.youtu.be",
    }
)

VIDEO_ID_PATTERN = re.compile(r"^[0-9A-Za-z_-]{11}$")

_SHORT_PATH_ERROR_CODES = frozenset({"error", "notfound", "unavailable"})


class YouTubeURLValidationError(ValueError):
    """Canonical input rejection with a stable machine-readable code."""

    def __init__(self, code: str, message_ru: str):
        super().__init__(message_ru)
        self.code = code
        self.message_ru = message_ru


@dataclass(frozen=True)
class YouTubeVideoRef:
    """A validated, canonical YouTube video reference."""

    video_id: str
    canonical_url: str
    source_url: str


def _reject(code: str, message_ru: str) -> YouTubeURLValidationError:
    return YouTubeURLValidationError(code, message_ru)


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def extract_video_id(source_url: str) -> YouTubeVideoRef:
    """Validate a YouTube URL and extract the canonical 11-char video id.

    Raises YouTubeURLValidationError with a stable code on every rejection
    path. No DNS resolution or network I/O happens here by design.
    """
    if not source_url or not isinstance(source_url, str):
        raise _reject("invalid_url", "Укажите ссылку на YouTube-видео.")
    candidate = source_url.strip()
    if len(candidate) > 2048:
        raise _reject("invalid_url", "Ссылка слишком длинная.")
    try:
        parts = urlsplit(candidate)
    except ValueError as exc:
        raise _reject("invalid_url", "Некорректная ссылка.") from exc

    if parts.scheme.lower() != "https":
        raise _reject("invalid_url", "Поддерживается только ссылка вида https://…")
    host = (parts.hostname or "").lower()
    if not host or parts.username or parts.password:
        raise _reject("invalid_url", "Некорректная ссылка.")
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
        raise _reject("invalid_url", "Допустимы только ссылки на youtube.com или youtu.be.")
    if _is_ip_literal(host):
        raise _reject("invalid_url", "IP-адреса не поддерживаются, укажите ссылку YouTube.")
    if host not in ALLOWED_HOSTS:
        raise _reject("invalid_url", "Допустимы только ссылки на youtube.com или youtu.be.")

    query = parse_qs(parts.query)
    if "v" in query and parts.path in ("", "/", "/watch"):
        raw_id = (query["v"] or [""])[0]
    elif host.endswith("youtu.be") and len(parts.path) > 1:
        raw_id = parts.path.lstrip("/")
    elif "/shorts/" in parts.path:
        raw_id = parts.path.split("/shorts/", 1)[1]
    elif "/embed/" in parts.path:
        raw_id = parts.path.split("/embed/", 1)[1]
    elif "/live/" in parts.path:
        raw_id = parts.path.split("/live/", 1)[1]
    else:
        raise _reject("invalid_url", "Не удалось распознать идентификатор видео.")

    video_id = raw_id.split("/", 1)[0].strip()
    if not VIDEO_ID_PATTERN.match(video_id):
        raise _reject("invalid_url", "Идентификатор видео имеет неверный формат.")

    playlist = (query.get("list") or [""])[0]
    if playlist:
        raise _reject("playlist_not_supported", "Плейлисты не поддерживаются, укажите отдельное видео.")

    canonical_url = f"https://www.youtube.com/watch?v={video_id}"
    return YouTubeVideoRef(video_id=video_id, canonical_url=canonical_url, source_url=candidate)
