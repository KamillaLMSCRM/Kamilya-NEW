"""Deterministic identity for verified source-bound question shapes, not truth.

The caller must prove the construction or exact owned binary-predicate shape.
An identity never establishes source entailment, assessment coverage or quality.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def source_rule_identity(stem: str, base: str, *, assessed_focus: str = "") -> str:
    values = [" ".join(value.casefold().replace("ё", "е").split()) for value in (base, stem)]
    focus = " ".join(assessed_focus.casefold().replace("ё", "е").split())
    if focus and focus != values[0]:
        values.append(focus)
    return "source-rule:" + hashlib.sha256(json.dumps(values, ensure_ascii=False).encode()).hexdigest()


def assessment_inventory_binding(question: Any, identity: str) -> str:
    """Bind a server-owned dedup token, NEVER a truth or containment exemption.

    Integrity against stale in-process copies, not authentication of model input.
    Only the worker after both critics may populate the corresponding fields.
    """
    values = [identity, question.prompt, list(question.options), question.correct_answer,
              question.source_quote, list(question.evidence_fact_ids)]
    return hashlib.sha256(json.dumps(values, ensure_ascii=False).encode()).hexdigest()
