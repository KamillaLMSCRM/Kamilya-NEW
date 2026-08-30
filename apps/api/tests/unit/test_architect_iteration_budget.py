"""Regression coverage for Architect agents that keep exploring until the budget ends."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.core import db as core_db
from app.modules.ai.architect import run_architect


class _Result:
    def __init__(self, rows=None):
        self._rows = rows or []

    def fetchall(self):
        return self._rows


class _Session:
    async def execute(self, statement, params=None):
        if "document_embeddings" in str(statement):
            return _Result([("doc-1", "Rules")])
        return _Result()


class _SessionContext:
    async def __aenter__(self):
        return _Session()

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _ExploringLLM:
    """Keeps calling a tool until Architect explicitly reserves a final turn."""

    def __init__(self):
        self.calls = 0
        self.messages = []

    async def ainvoke(self, messages):
        self.calls += 1
        self.messages = list(messages)
        latest = messages[-1]["content"].lower()
        if "do not use any more tools" in latest and "final course structure" in latest:
            payload = {
                "title": "Rules course",
                "description": "Grounded course",
                "modules": [
                    {
                        "title": "Rules",
                        "lessons": [
                            {
                                "title": "Core procedure",
                                "objectives": ["Apply the procedure"],
                                "source_doc_ids": ["doc-1"],
                                "relevant_headings": ["Procedure"],
                            }
                        ],
                    }
                ],
            }
            return SimpleNamespace(content=f"```json\n{json.dumps(payload)}\n```")
        return SimpleNamespace(
            content='```json\n{"tool":"list_documents","args":{}}\n```'
        )


class _BudgetCorrectingLLM:
    def __init__(self):
        self.calls = 0

    async def ainvoke(self, messages):
        self.calls += 1
        lesson_count = 2 if self.calls == 1 else 1
        payload = {
            "title": "Compact rules course",
            "description": "Grounded course",
            "modules": [
                {
                    "title": "Rules",
                    "lessons": [
                        {
                            "title": f"Procedure {index}",
                            "objectives": ["Apply the procedure"],
                            "source_doc_ids": ["doc-1"],
                            "relevant_headings": ["Procedure"],
                        }
                        for index in range(lesson_count)
                    ],
                }
            ],
        }
        return SimpleNamespace(content=f"```json\n{json.dumps(payload)}\n```")


@pytest.mark.asyncio
async def test_architect_reserves_a_final_turn_when_model_keeps_using_tools(monkeypatch):
    monkeypatch.setattr(core_db, "async_session_factory", lambda: _SessionContext())
    llm = _ExploringLLM()

    structure = await run_architect(
        llm=llm,
        tools={"list_documents": lambda: _async_value('[{"id":"doc-1"}]')},
        max_iterations=3,
        tenant_id="00000000-0000-0000-0000-000000000001",
    )

    assert structure.title == "Rules course"
    assert llm.calls == 2


@pytest.mark.asyncio
async def test_architect_rejects_oversized_structure_before_lesson_generation(monkeypatch):
    monkeypatch.setattr(core_db, "async_session_factory", lambda: _SessionContext())
    llm = _BudgetCorrectingLLM()

    structure = await run_architect(
        llm=llm,
        tools={"list_documents": lambda: _async_value('[{"id":"doc-1"}]')},
        num_modules=1,
        lessons_per_module=1,
        max_iterations=4,
        tenant_id="00000000-0000-0000-0000-000000000001",
    )

    assert len(structure.modules) == 1
    assert len(structure.modules[0].lessons) == 1
    assert llm.calls == 2


async def _async_value(value):
    return value
