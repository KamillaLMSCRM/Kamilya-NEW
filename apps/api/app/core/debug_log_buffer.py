"""In-memory ring buffer + LogRecord handler + stdout capture for runtime logs.

Why this exists:
  Render exposes `/v1/services/{id}/logs` only through the Dashboard UI,
  not the public API. AI agents and on-call engineers need runtime logs
  without a browser. The fix is to capture print()/logger output in a
  thread-safe ring buffer inside the running app, then expose it via
  a superadmin-only REST endpoint. The endpoint is mounted at
  `/v1/admin/debug/logs` (see apps/api/app/modules/admin/router.py).

Two capture paths:
  1. BufferHandler — receives every logging.LogRecord from the root
     logger and any logger that inherits from it.
  2. _StdoutTee — wraps sys.stdout/sys.stderr so direct print()
     calls and any third-party library that writes to stdout also
     land in the buffer. Render stdout is preserved because we
     chain back to the original stream after each line.

Thread safety:
  logging.Handler.emit() may be called from any thread (uvicorn workers,
  background tasks). All reads/writes go through a single threading.Lock.
  The buffer itself is a collections.deque with a maxlen, which is
  thread-safe for append/pop operations at opposite ends.
"""
from __future__ import annotations

import collections
import logging
import sys
import threading
import time
from typing import Any, TextIO

# Default capacity: ~500 lines. Render keeps stdout in the deploy log
# buffer, but our ring buffer is the only thing an agent can read via
# the API. 500 lines covers a typical ingest + AI-generation debug
# session; older lines fall off.
DEFAULT_CAPACITY = 500

_buffer: collections.deque[dict[str, Any]] = collections.deque(maxlen=DEFAULT_CAPACITY)
_lock = threading.Lock()
_stdout_tee: "_StdoutTee | None" = None
_stderr_tee: "_StdoutTee | None" = None


def _record(level: str, message: str) -> None:
    """Append a structured record to the ring buffer."""
    with _lock:
        _buffer.append({
            "ts": time.time(),
            "level": level,
            "message": message,
        })


def get_recent(
    limit: int = 100,
    level: str | None = None,
    since_ts: float | None = None,
) -> list[dict[str, Any]]:
    """Return the most recent records (newest last).

    Args:
      limit: max number of records to return.
      level: optional minimum level filter ('DEBUG' | 'INFO' | 'WARNING' | 'ERROR' | 'CRITICAL').
      since_ts: only records strictly after this unix timestamp.
    """
    _LEVEL_ORDER = {"DEBUG": 0, "INFO": 1, "WARNING": 2, "WARN": 2, "ERROR": 3, "CRITICAL": 4}
    min_level = _LEVEL_ORDER.get(level.upper(), 0) if level else 0

    with _lock:
        snapshot = list(_buffer)

    if since_ts is not None:
        snapshot = [r for r in snapshot if r["ts"] > since_ts]
    if level:
        snapshot = [r for r in snapshot if _LEVEL_ORDER.get(r["level"].upper(), 0) >= min_level]
    return snapshot[-limit:]


def clear() -> None:
    """Wipe the buffer. Useful for isolating a single request in tests."""
    with _lock:
        _buffer.clear()


class BufferHandler(logging.Handler):
    """logging.Handler that appends formatted records to the ring buffer."""

    def __init__(self, level: int = logging.DEBUG):
        super().__init__(level=level)
        self.setFormatter(logging.Formatter("%(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = record.levelname
            msg = self.format(record)
            _record(level, msg)
        except Exception:
            # Never let logging crash the app — silently swallow.
            pass


class _StdoutTee:
    """Wraps a TextIO stream, copying each write to the ring buffer.

    Why we need this:
      Code in this codebase uses `print(..., flush=True)` extensively
      for visibility in Render logs (the reasoning is documented in
      commit 01349f7). `print()` bypasses logging.Handler entirely,
      so the BufferHandler alone misses them. We tee by replacing
      sys.stdout / sys.stderr with this wrapper; the original stream
      is preserved so Render's log capture still receives every byte.
    """

    def __init__(self, original: TextIO, level: str):
        self._original = original
        self._level = level

    def write(self, s: str) -> int:
        # Always forward to the real stream so Render still sees the line.
        try:
            self._original.write(s)
        except Exception:
            pass
        # Only buffer non-empty, non-whitespace lines to avoid noise.
        if s and s.strip():
            for line in s.splitlines():
                if line.strip():
                    _record(self._level, line)
        return len(s)

    def flush(self) -> None:
        try:
            self._original.flush()
        except Exception:
            pass

    def isatty(self) -> bool:
        try:
            return self._original.isatty()
        except Exception:
            return False

    def __getattr__(self, name: str) -> Any:
        # Forward anything else (fileno, closed, mode, ...) to the original.
        return getattr(self._original, name)


_handler: BufferHandler | None = None


def handler() -> BufferHandler:
    global _handler
    if _handler is None:
        _handler = BufferHandler()
    return _handler


def install() -> None:
    """Attach the BufferHandler to root and tee stdout/stderr.

    Idempotent — safe to call from app.main startup multiple times.
    """
    global _stdout_tee, _stderr_tee
    root = logging.getLogger()
    # Only attach once.
    if not any(isinstance(h, BufferHandler) for h in root.handlers):
        root.addHandler(handler())
    if _stdout_tee is None:
        _stdout_tee = _StdoutTee(sys.stdout, "INFO")
        sys.stdout = _stdout_tee  # type: ignore[assignment]
    if _stderr_tee is None:
        _stderr_tee = _StdoutTee(sys.stderr, "ERROR")
        sys.stderr = _stderr_tee  # type: ignore[assignment]


def uninstall() -> None:
    """Reverse install() — used in tests to keep the original streams."""
    global _stdout_tee, _stderr_tee
    if _stdout_tee is not None:
        sys.stdout = _stdout_tee._original
        _stdout_tee = None
    if _stderr_tee is not None:
        sys.stderr = _stderr_tee._original
        _stderr_tee = None