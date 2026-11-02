import copy
import socket
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from app.modules.ai.v3.qa_luna_pending_policy import DIRECT_POLICY, KEY
from app.modules.courses.router import get_course_preview


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("network forbidden")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(httpx.Client, "send", denied)
    monkeypatch.setattr(httpx.AsyncClient, "send", denied)


class Result:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value

    def scalars(self):
        return self

    def all(self):
        return self.value


class Database:
    def __init__(self, course, documents):
        self.results = iter([course, [], [], documents])
        self.queries = []

    async def execute(self, query):
        self.queries.append(query)
        return Result(next(self.results))


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["valid", "foreign", "unlisted", "missing", "legacy"])
async def test_preview_span_name_is_scoped_and_response_only(case):
    tenant, course_id, document_id, lesson_id = (uuid4() for _ in range(4))
    reference = {"kind": "working_text_span_v1", "doc_id": str(document_id),
                 "source_revision": "rev", "source_text_sha256": "a" * 64,
                 "start": 0, "end": 2, "span_sha256": "b" * 64,
                 "doc_name": "untrusted"}
    original = copy.deepcopy(reference)
    lesson = SimpleNamespace(id=lesson_id, title="Lesson", content_type="text", content="Body",
                             duration_seconds=0, order_index=0,
                             source_document_ids=[] if case == "unlisted" else [str(document_id)],
                             source_references=[reference], source_validation_status="needs_review")
    module = SimpleNamespace(id=uuid4(), title="Module", description="", order_index=0, lessons=[lesson])
    analysis = {KEY: DIRECT_POLICY, "generation_engine": "evidence_v3"} if case != "legacy" else {}
    course = SimpleNamespace(id=course_id, title="Course", description="", status="draft", modules=[module],
                             source_document_ids=[str(document_id)], source_analysis=analysis,
                             source_strategy="single_topic", source_combination_goal=None)
    document = SimpleNamespace(id=document_id, filename="owned.txt", title="Owned")
    db = Database(course, [] if case in {"foreign", "missing"} else [document])
    response = await get_course_preview(course_id, max_chars=240, db=db, user=SimpleNamespace(tenant_id=tenant))
    projected = response.modules[0].lessons[0].source_references[0].model_dump()
    assert projected["doc_name"] == ("owned.txt" if case == "valid" else "untrusted" if case == "legacy" else "")
    assert reference == original
    assert not {"kind", "source_revision", "source_text_sha256", "start", "end", "span_sha256"} & projected.keys()
    assert "tenant_id" in str(db.queries[3])
