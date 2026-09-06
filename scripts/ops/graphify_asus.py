"""Bounded Graphify semantic sidecar on the owner's existing ASUS, never LMS runtime.

Run with Graphify's pinned pipx Python. Only the reviewed, hash-pinned ADRs below
may leave the workstation. No folder scanning, credentials, retries or fallback.
"""
from __future__ import annotations

import argparse
import hashlib
import http.client
import io
import json
import os
import tempfile
import time
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE_URL = "http://10.66.66.28:8000/v1"
MODEL = "LibertAIDAI/GLM-5.3-Flash-NVFP4"
GRAPHIFY_VERSION = "0.9.23"
OUTPUT = ROOT / "graphify-out" / "asus"
# Populated from root-reviewed non-personal engineering documents; changes require review.
REVIEWED: dict[str, str] = {
    "docs/adr/0008-auth-strategy.md": "5ad981db648e94ce0ff9419c7b8f1fe1bf2df840c9d35c6d45518da024217823",
    "docs/adr/0012-rbac-admin-vs-methodologist.md": "d82dfcf5871f39b2b900518d1bc59d6240946fdd854530df7f45c4eccebe7924",
}
SECTIONS = {
    "docs/adr/0008-auth-strategy.md": "## Token storage and session transport",
    "docs/adr/0012-rbac-admin-vs-methodologist.md": "### 1. Ownership boundaries",
}


def reviewed_sections(documents: dict[str, str]) -> dict[str, str]:
    selected = {}
    for name, text in documents.items():
        heading = SECTIONS[name]
        lines = text.splitlines()
        start = lines.index(heading)
        level = len(heading) - len(heading.lstrip("#"))
        end = len(lines)
        for index in range(start + 1, len(lines)):
            candidate = lines[index]
            depth = len(candidate) - len(candidate.lstrip("#"))
            if 0 < depth <= level and candidate[depth:depth + 1] == " ":
                end = index
                break
        excerpt = "\n".join(lines[start:end])
        if len(excerpt) > 3500:
            raise ValueError("section_requires_review")
        selected[name] = f"Original source lines L{start+1}-L{end}:\n{excerpt}"
    return selected


def approved_documents(root: Path = ROOT, manifest: dict | None = None) -> dict[str, str]:
    documents = {}
    for name, expected in (REVIEWED if manifest is None else manifest).items():
        path = (root / name).resolve()
        if not path.is_relative_to(root.resolve()) or path.suffix != ".md":
            raise ValueError("document_out_of_scope")
        raw = path.read_bytes()
        if len(raw) > 20000 or hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError("document_requires_review")
        documents[name] = raw.decode("utf-8")
    if not documents or len(documents) > 2:
        raise ValueError("invalid_document_count")
    return documents


def validate_result(data: dict, sources: set[str]) -> None:
    if data.get("finish_reason") != "stop":
        raise ValueError("generation_incomplete")
    nodes, edges = data.get("nodes"), data.get("edges")
    if not isinstance(nodes, list) or not nodes or not isinstance(edges, list) or not edges:
        raise ValueError("empty_or_invalid_graph")
    if len(nodes) > 6 or len(edges) > 6:
        raise ValueError("summary_budget_exceeded")
    ids = set()
    for node in nodes:
        if (not isinstance(node, dict) or not isinstance(node.get("id"), str)
                or not node["id"] or node["id"] in ids
                or not isinstance(node.get("label"), str)
                or node.get("source_file") not in sources):
            raise ValueError("invalid_node_or_provenance")
        ids.add(node["id"])
    for edge in edges:
        if (not isinstance(edge, dict) or edge.get("source") not in ids
                or edge.get("target") not in ids
                or edge.get("confidence") not in {"EXTRACTED", "INFERRED", "AMBIGUOUS"}
                or not isinstance(edge.get("relation"), str)):
            raise ValueError("invalid_edge")
    if {node["source_file"] for node in nodes} != sources:
        raise ValueError("missing_document_coverage")


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     suffix=".tmp", delete=False) as stream:
        temporary = Path(stream.name)
        json.dump(value, stream, ensure_ascii=False, indent=2)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def request_json(path: str, payload: dict | None = None) -> dict:
    if (path, payload is None) not in {("/v1/models", True), ("/v1/chat/completions", False)}:
        raise ValueError("request_out_of_scope")
    # Direct private socket: no ambient proxy, credentials, redirect or retry.
    connection = http.client.HTTPConnection("10.66.66.28", 8000, timeout=90)
    try:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
        connection.request("POST" if body is not None else "GET", path, body=body,
                           headers={"Content-Type": "application/json"})
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError(f"http_status_{response.status}")
        data = response.read(1_000_001)
        if len(data) > 1_000_000:
            raise ValueError("response_too_large")
        return json.loads(data)
    finally:
        connection.close()


def run(probe: bool = False) -> dict:
    from importlib.metadata import version
    if version("graphifyy") != GRAPHIFY_VERSION:
        raise ValueError("graphify_version_requires_review")
    from graphify.llm import _extraction_system, _parse_llm_json

    documents = ({"synthetic.md": "# Example\nLearner uses Course. Course contains Lesson.\n"}
                 if probe else reviewed_sections(approved_documents()))
    prompt = _extraction_system(deep=False)
    prompt += ("\nUse only the exact FILE paths supplied as source_file, never referenced paths."
               "\nThis is a bounded navigation summary, NOT exhaustive extraction."
               " Return at most 6 nodes and 6 edges in TOTAL, covering every supplied FILE."
               " Use short labels and reasons; omit hyperedges. Keep JSON below 1400 tokens.")
    request_text = "\n\n".join(f"FILE: {name}\n{text}" for name, text in documents.items())
    request_spec = {"model": MODEL, "graphify": GRAPHIFY_VERSION, "prompt": prompt,
                    "documents": documents, "max_output": 2048, "thinking": False}
    cache_key = hashlib.sha256(json.dumps(request_spec, sort_keys=True).encode()).hexdigest()
    cache_path = OUTPUT / "cache" / f"{cache_key}.json"
    cached = cache_path.exists() and not probe
    started = time.monotonic()
    if cached:
        result = json.loads(cache_path.read_text(encoding="utf-8"))
    else:
        if MODEL not in {model["id"] for model in request_json("/v1/models")["data"]}:
            raise ValueError("model_identity_mismatch")
        response = request_json("/v1/chat/completions", {
            "model": MODEL, "temperature": 0, "max_completion_tokens": 2048,
            "messages": [{"role": "system", "content": prompt},
                         {"role": "user", "content": request_text}],
            "chat_template_kwargs": {"enable_thinking": False},
        })
        if response.get("model") != MODEL:
            raise ValueError("response_model_mismatch")
        if not response.get("choices"):
            raise ValueError("empty_response")
        choice = response["choices"][0]
        usage = response.get("usage") or {}
        if choice.get("finish_reason") != "stop":
            raise ValueError("generation_incomplete")
        # Upstream parser logs invalid-response excerpts; never expose provider text.
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            result = _parse_llm_json(choice["message"].get("content") or "{}")
        result.update(finish_reason=choice.get("finish_reason"),
                      input_tokens=usage.get("prompt_tokens"),
                      output_tokens=usage.get("completion_tokens"))
    validate_result(result, set(documents))
    if probe:
        return {"status": "PROBE_PASS", "model": MODEL, "nodes": len(result["nodes"]),
                "edges": len(result["edges"]), "elapsed_seconds": round(time.monotonic()-started, 2),
                "input_tokens": result.get("input_tokens"), "output_tokens": result.get("output_tokens")}
    from graphify.build import build_from_json
    from networkx.readwrite import json_graph
    graph = build_from_json(result, directed=True, root=ROOT)
    evidence = {"status": "GRAPH_DERIVED_NOT_RUNTIME", "model": MODEL,
                "checked_at_utc": datetime.now(timezone.utc).isoformat(),
                "graphify_version": GRAPHIFY_VERSION, "cache_hit": cached,
                "cache_key": cache_key, "source_sha256": REVIEWED,
                "coverage": "bounded_summary_of_selected_sections", "sections": SECTIONS,
                "elapsed_seconds": round(time.monotonic()-started, 2),
                "input_tokens_this_run": 0 if cached else result.get("input_tokens"),
                "output_tokens_this_run": 0 if cached else result.get("output_tokens"),
                "nodes": graph.number_of_nodes(), "edges": graph.number_of_edges()}
    # The semantic sidecar never overwrites the existing AST graph or project truth.
    atomic_json(OUTPUT / "graph.json", json_graph.node_link_data(graph, edges="links"))
    atomic_json(OUTPUT / "evidence.json", evidence)
    if not cached:
        atomic_json(cache_path, result)
    return evidence


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe", action="store_true", help="One synthetic request; no graph writes")
    arguments = parser.parse_args()
    try:
        print(json.dumps(run(arguments.probe), ensure_ascii=False))
    except Exception as error:
        # Never serialize provider bodies, raw exception text, prompts or headers.
        print(json.dumps({"status": "FAILED", "error_class": type(error).__name__}))
        raise SystemExit(1) from None
