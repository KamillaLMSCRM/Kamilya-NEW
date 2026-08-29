#!/usr/bin/env python3
"""Read Kamilya watchdog state-change mail without exposing mailbox content."""

from __future__ import annotations

import argparse
import email
from email.header import decode_header, make_header
import imaplib
import json
import os
from pathlib import Path
import re
import sys
from typing import Any


WATCHDOG_SUBJECT = re.compile(r"^\[Kamilya\].*operational watchdog$", re.IGNORECASE)


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def decode_subject(message: email.message.Message) -> str:
    return str(make_header(decode_header(message.get("Subject", ""))))


def text_body(message: email.message.Message) -> str:
    parts = message.walk() if message.is_multipart() else (message,)
    for part in parts:
        if part.get_content_type() != "text/plain":
            continue
        payload = part.get_payload(decode=True) or b""
        return payload.decode(part.get_content_charset() or "utf-8", errors="replace")
    return ""


def sanitize_message(uid: int, raw_message: bytes) -> dict[str, Any] | None:
    message = email.message_from_bytes(raw_message)
    subject = decode_subject(message)
    if not WATCHDOG_SUBJECT.match(subject):
        return None

    severity = "UNKNOWN"
    evidence: list[str] = []
    for raw_line in text_body(message).splitlines():
        line = raw_line.strip()
        if line.startswith("Severity:"):
            candidate = line.partition(":")[2].strip().upper()
            if candidate in {"OK", "WARNING", "CRITICAL"}:
                severity = candidate
        elif line.startswith("timestamp="):
            evidence.append(line[:2000])

    return {
        "uid": uid,
        "date": message.get("Date", ""),
        "subject": subject,
        "severity": severity,
        "evidence": evidence,
    }


def default_state_file() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "state"))
    return base / "Kamilya" / "watchdog-inbox-state.json"


def read_last_ack(path: Path) -> int:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return max(0, int(data.get("last_ack_uid", 0)))
    except (FileNotFoundError, ValueError, TypeError, json.JSONDecodeError):
        return 0


def write_ack(path: Path, uid: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    current = read_last_ack(path)
    target = max(current, uid)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"last_ack_uid": target}) + "\n", encoding="utf-8")
    temporary.replace(path)


def mailbox_config(env_file: Path) -> tuple[str, int, str, str]:
    values = load_env(env_file)
    host = values.get("IMAP_HOST", "mail.kml.kz")
    port = int(values.get("IMAP_PORT", "993"))
    username = values.get("email") or values.get("EMAIL") or ""
    password = values.get("email_password") or values.get("EMAIL_PASSWORD") or ""
    if not username or not password:
        raise RuntimeError("IMAP credentials are not configured")
    return host, port, username, password


def poll(env_file: Path, state_file: Path, max_events: int) -> int:
    host, port, username, password = mailbox_config(env_file)
    last_ack = read_last_ack(state_file)
    events: list[dict[str, Any]] = []

    with imaplib.IMAP4_SSL(host, port, timeout=20) as client:
        client.login(username, password)
        status, _ = client.select("INBOX", readonly=True)
        if status != "OK":
            raise RuntimeError("IMAP inbox selection failed")
        status, data = client.uid("search", None, f"UID {last_ack + 1}:*")
        if status != "OK":
            raise RuntimeError("IMAP UID search failed")
        uids = data[0].split() if data and data[0] else []
        for raw_uid in uids[-max_events:]:
            uid = int(raw_uid)
            status, parts = client.uid("fetch", raw_uid, "(BODY.PEEK[])")
            if status != "OK":
                continue
            raw_message = next((part[1] for part in parts if isinstance(part, tuple)), b"")
            event = sanitize_message(uid, raw_message)
            if event is not None:
                events.append(event)

    print(json.dumps({"last_ack_uid": last_ack, "events": events}, ensure_ascii=True))
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("poll", "ack"))
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--state-file", type=Path, default=default_state_file())
    parser.add_argument("--uid", type=int)
    parser.add_argument("--max-events", type=int, default=50)
    args = parser.parse_args()
    if args.command == "ack" and (args.uid is None or args.uid < 1):
        parser.error("ack requires --uid greater than zero")
    return args


def main() -> int:
    args = parse_args()
    try:
        if args.command == "ack":
            write_ack(args.state_file, args.uid)
            print(json.dumps({"last_ack_uid": read_last_ack(args.state_file)}))
            return 0
        return poll(args.env_file, args.state_file, args.max_events)
    except Exception as exc:
        print(
            json.dumps({"error": type(exc).__name__, "message": str(exc)}),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
