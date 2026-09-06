"""Prepare a local-only, sanitized engineering Markdown corpus; never performs HTTP.

Selection and redactions are explicit evidence, not a claim to index every byte.
Root must review the resulting corpus and approve its digest before inference.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

from graphify_asus import ROOT, atomic_json

ROOT_FILES = {"AGENTS.md", "ERRORS.md", "PROJECT.md", "README.md", "CHANGELOG.md"}
EXCLUDED_DIRS = {
    "marketing",
    "customer",
    "legal",
    "presentations",
    "plans",
    "evidence",
    "audits",
    "test-assets",
    "testing",
}
HISTORICAL = {
    "AGENT_INSTRUCTION_V1.md",
    "EPIC_CHAIN_SPEC_V1.md",
    "MODULE_MINI_SPEC_V1.md",
    "WORKFLOW_NOTIFICATION_V1.md",
    "INFRA_KZ_OCR_MIGRATION_ANALYSIS.md",
    "2026-08-22_kamilya-pricing-policy-proposal.md",
    "compliance-course-catalog.md",
}
SENSITIVE_LINE = re.compile(
    r"(?i)(?:[\w.+-]+@[\w.-]+\.[a-z]{2,}|\b(?:\d{1,3}\.){3}\d{1,3}\b|"
    r"\+?7[\s(-]*\d{3}[\s)-]*\d{3}[\s-]*\d{2}[\s-]*\d{2}|"
    r"-----BEGIN |\b(?:gh[pousr]_|github_pat_|sk-|sb_secret_|eyJ)[A-Za-z0-9_-]{8,}|"
    r"(?:password|passwd|secret|token|api_key|authorization|cookie|парол)[\w-]*[\"'`]*\s*[:=]|"
    r"(?:postgres(?:ql)?|redis|amqps?)://|https?://[^\s/]+:[^\s/]+@|"
    r"tenant[_ -]?id\s*[:=]|user[_ -]?id\s*[:=]|"
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|"
    r"karcher|sandy[qk]|сандык|сандық)"
)
URL = re.compile(r"https?://[^\s)<>`]+")


def selection(path: str) -> str | None:
    p = Path(path)
    parts = [part.casefold() for part in p.parts]
    if p.suffix.lower() != ".md":
        return "not_markdown"
    if p.name in HISTORICAL:
        return "historical_reference_preserved"
    if len(p.parts) == 1:
        return None if path in ROOT_FILES else "outside_engineering_root_allowlist"
    if p.parts[0] == "docs":
        if any(part in EXCLUDED_DIRS | {"archive", "archives"} for part in parts[1:-1]) or re.search(
            r"(?i)(?:marketing|customer|legal|archive|pricing|proposal|catalog)", p.stem
        ):
            return "historical_evidence_or_nonengineering"
        if any(part in {"agents", "analysis", "prompts", "DocumentKZ", "Документы тенантов"} for part in p.parts):
            return "private_or_other_project"
        return None
    if path.startswith(".codex/"):
        if path.startswith(".codex/skills/graphify/references/"):
            return "upstream_reference_not_project_truth"
        if (
            path.startswith(".codex/skills/kamilya-")
            or path == ".codex/skills/graphify/SKILL.md"
            or path.startswith(".codex/agents/")
            or path == ".codex/tooling/TOOLS.md"
        ):
            return None
        return "outside_project_tooling_allowlist"
    return "outside_documentation_scope"


def sanitize(text: str) -> tuple[list[str], dict[str, int]]:
    lines = []
    counts = {"fenced_code": 0, "sensitive_line": 0, "urls": 0}
    fence = None
    for line in text.splitlines():
        marker = re.match(r"^\s*(`{3,}|~{3,})", line)
        if marker:
            token = marker.group(1)
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = None
            counts["fenced_code"] += 1
            lines.append("")
        elif fence:
            counts["fenced_code"] += 1
            lines.append("")
        elif SENSITIVE_LINE.search(line):
            counts["sensitive_line"] += 1
            lines.append("")
        else:
            cleaned, count = URL.subn("[URL OMITTED]", line)
            counts["urls"] += count
            lines.append(cleaned)
    return lines, counts


def chunks(lines: list[str], limit: int = 10000) -> list[dict]:
    result = []
    start, current, size = 1, [], 0
    for number, line in enumerate(lines, 1):
        if len(line) > limit:
            raise ValueError("oversize_line_requires_review")
        if current and size + len(line) + 1 > limit:
            if "\n".join(current).strip():
                result.append(
                    {"id": str(start), "start_line": start, "end_line": number - 1, "text": "\n".join(current)}
                )
            start, current, size = number, [], 0
        current.append(line)
        size += len(line) + 1
    if "\n".join(current).strip():
        result.append({"id": str(start), "start_line": start, "end_line": len(lines), "text": "\n".join(current)})
    return result


def prepare(root: Path = ROOT) -> dict:
    tracked = (
        subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z", "--", "*.md"],
            cwd=root,
            check=True,
            capture_output=True,
        )
        .stdout.decode("utf-8")
        .split("\0")
    )
    # Include newly reviewed project skills without scanning ignored or private trees.
    tracked += [p.relative_to(root).as_posix() for p in (root / ".codex/skills").rglob("*.md")]
    documents, excluded = [], []
    for name in sorted(set(filter(None, tracked))):
        reason = selection(name)
        if reason:
            excluded.append({"path": name, "reason": reason})
            continue
        path = (root / name).resolve()
        if not path.is_relative_to(root.resolve()) or not path.is_file():
            raise ValueError("source_outside_root_or_missing")
        raw = path.read_bytes()
        lines, redactions = sanitize(raw.decode("utf-8-sig"))
        parts = chunks(lines)
        if not parts:
            excluded.append({"path": name, "reason": "empty_after_sanitization"})
            continue
        documents.append(
            {
                "path": name,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "chunks": parts,
                "redactions": redactions,
                "source_lines": len(lines),
            }
        )
    return {
        "schema": 1,
        "coverage_definition": "eligible_sanitized_engineering_prose",
        "documents": documents,
        "excluded": excluded,
    }


if __name__ == "__main__":
    corpus = prepare()
    output = ROOT / "graphify-out/docs-corpus.json"
    atomic_json(output, corpus)
    print(
        json.dumps(
            {
                "documents": len(corpus["documents"]),
                "chunks": sum(len(d["chunks"]) for d in corpus["documents"]),
                "characters": sum(len(c["text"]) for d in corpus["documents"] for c in d["chunks"]),
                "excluded": len(corpus["excluded"]),
                "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
            }
        )
    )
