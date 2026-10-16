"""Read-only source inventory: names/locations/types, never string values.

Heuristic candidates are review inputs, NOT a claim that every constant should
become a hot setting. No .env, dependencies, Git mutations or network access.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HINT = re.compile(r"timeout|deadline|model|retry|retries|batch|interval|temperature|threshold|max_|limit|ttl|poll|expire", re.I)
JS = re.compile(r"\b(?:const|let)\s+([A-Z][A-Z0-9_]+)\s*=|\b(setInterval|setTimeout)\s*\(")


def inventory(root=ROOT):
    rows, files, gaps = [], [], []
    for base, suffixes in ((root / "apps/api/app", {".py"}), (root / "apps/web/src", {".ts", ".tsx"})):
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.is_symlink() or path.suffix not in suffixes or "node_modules" in path.parts or "__pycache__" in path.parts:
                continue
            relative = path.relative_to(root).as_posix()
            source = path.read_text(encoding="utf-8-sig")
            files.append(relative)
            if path.suffix == ".py":
                try:
                    tree = ast.parse(source)
                except SyntaxError:
                    gaps.append(relative)
                    continue
                for node in ast.walk(tree):
                    names = []
                    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                        names = [node.target.id]
                    elif isinstance(node, ast.Assign):
                        names = [target.id for target in node.targets if isinstance(target, ast.Name)]
                    for name in names:
                        if name.isupper() and HINT.search(name):
                            rows.append({"file": relative, "line": node.lineno, "symbol": name, "candidate": "declared_parameter"})
                    if isinstance(node, ast.Call):
                        for keyword in node.keywords:
                            if keyword.arg and HINT.search(keyword.arg) and isinstance(keyword.value, ast.Constant):
                                rows.append({"file": relative, "line": keyword.value.lineno, "symbol": keyword.arg, "candidate": "literal_call_option"})
            else:
                for match in JS.finditer(source):
                    symbol = match.group(1) or match.group(2)
                    if HINT.search(symbol) or symbol in {"setTimeout", "setInterval"}:
                        rows.append({"file": relative, "line": source.count("\n", 0, match.start()) + 1, "symbol": symbol, "candidate": "ui_constant_or_timer"})
    return {"status": "REVIEW_INPUT", "scope": "all_api_app_and_web_src_source_files", "source_files": len(files),
            "candidate_occurrences": len(rows), "parse_gaps": gaps, "candidates": rows,
            "limitations": "heuristic_not_semantic_completeness; dynamic_defaults_and_imported_values_need_source_review; no_string_values_exported"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path)
    args = parser.parse_args()
    report = inventory()
    if args.evidence:
        args.evidence.write_text(json.dumps(report, indent=2), encoding="utf8")
    print(json.dumps({key: value for key, value in report.items() if key != "candidates"}))


if __name__ == "__main__":
    main()
