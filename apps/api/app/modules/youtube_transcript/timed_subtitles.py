"""Read time-coded SRT and WebVTT without contacting a caption provider."""

import re
from html import unescape

from app.modules.youtube_transcript.provider import MAX_SEGMENTS, TranscriptSegment

_TIME = r"(?:\d{2,}:)?[0-5]\d:[0-5]\d[.,]\d{3}"
_TIMING = re.compile(rf"^({_TIME})[ \t]+-->[ \t]+({_TIME})(?:[ \t]+.*)?$", re.ASCII)
_TAGS = re.compile(r"</?(?:b|i|u|c(?:\.[\w.-]+)?|v(?: [^<>]*)?|lang(?: [^<>]*)?|ruby|rt)>")


def _seconds(raw: str) -> float:
    parts = raw.replace(",", ".").split(":")
    return sum(float(part) * factor for part, factor in zip(parts[::-1], (1, 60, 3600), strict=False))


def parse_timed_subtitles(value: str) -> list[TranscriptSegment]:
    value = value.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not value:
        raise ValueError("Empty subtitles")
    blocks = re.split(r"\n[ \t]*\n", value)
    webvtt = bool(re.match(r"^WEBVTT(?:[ \t]|\n|$)", blocks[0]))
    segments: list[TranscriptSegment] = []
    for block in blocks[1:] if webvtt else blocks:
        first, *lines = block.splitlines()
        if webvtt and re.fullmatch(r"(?:NOTE(?:[ \t].*)?|STYLE|REGION)", first):
            continue
        timing = _TIMING.fullmatch(first.strip())
        if timing is None and lines and "-->" not in first:
            timing = _TIMING.fullmatch(lines.pop(0).strip())
        if timing is None:
            raise ValueError("Invalid subtitle cue timing")
        start, end = map(_seconds, timing.groups())
        if end <= start:
            raise ValueError("Invalid subtitle cue interval")
        content = unescape(_TAGS.sub("", " ".join(lines))).strip()
        if content:
            segments.append(TranscriptSegment(start, end, content))
        if len(segments) > MAX_SEGMENTS:
            raise ValueError("Too many subtitle cues")
    if not segments:
        raise ValueError("No time-coded subtitle cues")
    return segments
