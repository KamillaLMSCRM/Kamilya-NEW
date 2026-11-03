"""Offline synthetic bijection checks; not database isolation evidence."""
import hashlib
import socket
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from app.modules.ai.architect_schema import CourseStructure, Lesson, Module
from app.modules.ai.assessment_schema import CourseAssessment, LessonAssessment, MCQOption, MCQQuestion
from app.modules.ai.direct_source import DirectSourceCorpus, DirectSourceDocument
from app.modules.ai.pipeline import GenerationState, _estimate_lesson_duration_seconds
from app.modules.ai.v3.final_save_contract import install_intent, make_intent, output_digest, resolve_intent
from app.modules.ai.v3.final_save_readback import verify_snapshot
from app.modules.ai.writer_schema import CourseContent, LessonContent, ModuleContent
from app.modules.courses.source_uncertainty import preserve_generated_source_uncertainty


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    def deny(*_args, **_kwargs):
        raise AssertionError("network forbidden")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket.socket, "connect_ex", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(httpx, "AsyncClient", deny)
    monkeypatch.setattr(httpx, "Client", deny)


def fixture():
    from app.modules.ai.qa_luna_dev_route import QA_TENANT

    tenant = QA_TENANT
    user, job_id, doc_id, course_id, module_id, lesson_id, quiz_id, question_id, choice_id = [uuid4() for _ in range(9)]
    t, u, j, d = map(str, (tenant, user, job_id, doc_id))
    analysis = {"generation_engine": "evidence_v3", "analysis_mode": "direct_source",
                "qa_luna_pending_journal_policy": "qa-direct-luna-diversity-v3"}
    state = GenerationState(job_id=j, structure=CourseStructure(title="course", modules=[Module(title="module", lessons=[Lesson(title="lesson")])]),
        content=CourseContent(title="course", modules=[ModuleContent(title="module", lessons=[LessonContent(
            title="lesson", content="body", source_references=[{"doc_id": d}], source_validation_status="needs_review")])]),
        assessment=CourseAssessment(assessments=[LessonAssessment(lesson_title="lesson", mcq=[MCQQuestion(
            question="question", options=[MCQOption("answer", True)], explanation="explanation", source_quote="source")])]),
        source_document_ids=[d], source_analysis=analysis, server_source_review_required=True)
    digest = output_digest(structure=state.structure, content=state.content, assessment=state.assessment,
        source_document_ids=state.source_document_ids, source_strategy=state.source_strategy,
        source_combination_goal=state.source_combination_goal, source_analysis=state.source_analysis,
        source_review_required=state.server_source_review_required, reuse_reason=state.reuse_reason)
    intent = make_intent(tenant_id=t, user_id=u, job_id=j, delivery_id="delivery", route_policy=analysis["qa_luna_pending_journal_policy"],
        route_fingerprint="a" * 64, documents=[{"doc_id": d, "revision": "document:" + "b" * 64,
        "text_sha256": hashlib.sha256(b"source").hexdigest()}], output_digest=digest)
    result = resolve_intent(install_intent({"delivery_task_id": "delivery"}, intent), intent, course_id=str(course_id), output_digest=digest)
    completed_at = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
    job = SimpleNamespace(id=j, tenant_id=tenant, user_id=user, status="completed", stage="completed", progress=100,
        message="Курс успешно сгенерирован!", completed_at=completed_at, updated_at=completed_at, errors=None,
        course_id=course_id, result=result, params={"documents": [d], "source_analysis": analysis,
        "progress_detail": {"current": 1, "total": 1, "estimated_remaining_seconds": 0}})
    course = SimpleNamespace(id=course_id, tenant_id=tenant, created_by=user, title="course", description="", status="draft", delivery_type="native", review_status="pending", reviewed_by=None,
        reviewed_at=None, review_comment=None, ai_generated=True, source_document_ids=[d], source_strategy="single_topic", source_combination_goal=None,
        source_analysis=preserve_generated_source_uncertainty({}, analysis, source_review_required=True))
    module = SimpleNamespace(id=module_id, tenant_id=tenant, course_id=course_id, title="module", description="", order_index=0, ai_generated=True)
    lesson = SimpleNamespace(id=lesson_id, tenant_id=tenant, module_id=module_id, title="lesson", content_type="text", content="body",
        duration_seconds=_estimate_lesson_duration_seconds("body", 1), order_index=0, ai_generated=True, published_at=None,
        source_document_ids=[d], source_references=[{"doc_id": d}], source_validation_status="needs_review")
    quiz = SimpleNamespace(id=quiz_id, tenant_id=tenant, lesson_id=lesson_id, title="lesson", pass_score=80, attempt_limit=3,
                           time_limit=None, deferral_days=7, review_status="needs_review", reviewed_by=None, reviewed_at=None)
    question = SimpleNamespace(id=question_id, quiz_id=quiz_id, text="question", type="MCQ", points=1,
                               explanation="explanation", source_quote="source", order_index=0, pool_group=None)
    choice = SimpleNamespace(id=choice_id, question_id=question_id, text="answer", is_correct=True, order_index=0)
    document = SimpleNamespace(id=doc_id, tenant_id=tenant, lifecycle_status="active", content_sha256="b" * 64)
    source = DirectSourceDocument(doc_id=d, title="doc", filename="doc", category="general",
                                  source_revision="document:" + "b" * 64, chunks=(), source_text="source")
    corpus = DirectSourceCorpus(tenant_id=t, documents=(source,), total_chars=6, total_chunks=0)
    return dict(state=state, intent=intent, job=job, course=course, source_corpus=corpus, documents=[document],
                modules=[module], lessons=[lesson], quizzes=[quiz], questions=[question], choices=[choice])


def test_complete_snapshot_matches():
    assert verify_snapshot(**fixture())


@pytest.mark.parametrize("mutation", ["missing", "extra", "question", "choice", "lesson", "module", "quiz", "course", "source", "revision", "owner", "delivery", "receipt", "pending", "wrong_parent", "duplicate"])
def test_tamper_missing_extra_or_foreign_holds(mutation):
    data = fixture()
    if mutation == "missing":
        data["questions"] = []
    if mutation == "extra":
        data["choices"].append(replace_choice(data["choices"][0]))
    if mutation == "question":
        data["questions"][0].text = "changed"
    if mutation == "choice":
        data["choices"][0].is_correct = False
    if mutation == "lesson":
        data["lessons"][0].source_references = []
    if mutation == "module":
        data["modules"][0].order_index = 9
    if mutation == "quiz":
        data["quizzes"][0].review_status = "approved"
    if mutation == "course":
        data["course"].title = "changed"
    if mutation == "source":
        data["documents"][0].lifecycle_status = "deleted"
    if mutation == "revision":
        data["documents"][0].content_sha256 = "f" * 64
    if mutation == "owner":
        data["job"].user_id = uuid4()
    if mutation == "delivery":
        data["job"].result["delivery_task_id"] = "foreign"
    if mutation == "receipt":
        data["job"].result["v3_final_save_receipt"]["output_digest"] = "f" * 64
    if mutation == "pending":
        data["job"].result["v3_pending_stages"] = None
    if mutation == "wrong_parent":
        data["lessons"][0].module_id = uuid4()
    if mutation == "duplicate":
        data["questions"].append(data["questions"][0])
    assert not verify_snapshot(**data)


def replace_choice(choice):
    duplicate = deepcopy(choice)
    duplicate.id = uuid4()
    return duplicate


def test_multiple_modules_with_shuffled_rows_preserve_bijection():
    data = fixture()
    state = data["state"]
    state.structure.modules.append(deepcopy(state.structure.modules[0]))
    state.content.modules.append(deepcopy(state.content.modules[0]))
    state.assessment.assessments.append(deepcopy(state.assessment.assessments[0]))
    module = deepcopy(data["modules"][0])
    module.id = uuid4()
    module.order_index = 1
    lesson = deepcopy(data["lessons"][0])
    lesson.id = uuid4()
    lesson.module_id = module.id
    quiz = deepcopy(data["quizzes"][0])
    quiz.id = uuid4()
    quiz.lesson_id = lesson.id
    question = deepcopy(data["questions"][0])
    question.id = uuid4()
    question.quiz_id = quiz.id
    choice = deepcopy(data["choices"][0])
    choice.id = uuid4()
    choice.question_id = question.id
    data["modules"].insert(0, module)
    data["lessons"].insert(0, lesson)
    data["quizzes"].insert(0, quiz)
    data["questions"].insert(0, question)
    data["choices"].insert(0, choice)
    previous = data["intent"]
    digest = output_digest(structure=state.structure, content=state.content, assessment=state.assessment,
        source_document_ids=state.source_document_ids, source_strategy=state.source_strategy,
        source_combination_goal=state.source_combination_goal, source_analysis=state.source_analysis,
        source_review_required=state.server_source_review_required, reuse_reason=state.reuse_reason)
    new = make_intent(tenant_id=previous["tenant_id"], user_id=previous["user_id"], job_id=previous["job_id"],
        delivery_id=previous["delivery_id"], route_policy=previous["route_policy"],
        route_fingerprint=previous["route_fingerprint"], documents=previous["documents"], output_digest=digest)
    data["intent"] = new
    data["job"].result = resolve_intent(install_intent({"delivery_task_id": "delivery"}, new), new,
                                        course_id=str(data["course"].id), output_digest=digest)
    data["job"].params["progress_detail"] = {"current": 2, "total": 2, "estimated_remaining_seconds": 0}
    assert verify_snapshot(**data)
    data["choices"][0].question_id = uuid4()
    assert not verify_snapshot(**data)


@pytest.mark.parametrize("source_position", range(4))
@pytest.mark.parametrize("question_index", range(4))
def test_saved_choice_rotation_matches_native_projection_without_mutation(source_position, question_index):
    data = fixture()
    state = data["state"]
    original = [MCQOption("wrong-a", False), MCQOption("wrong-b", False), MCQOption("wrong-c", False)]
    original.insert(source_position, MCQOption("correct", True))
    state.assessment.assessments[0].mcq = [MCQQuestion(question=f"question-{i}", options=deepcopy(original),
        explanation="explanation", source_quote="source") for i in range(question_index + 1)]
    untouched = deepcopy(state.assessment)
    quiz_id = data["quizzes"][0].id
    data["questions"], data["choices"] = [], []
    # Independent explicit expected order for each native question index.
    orders = [
        ["correct", "wrong-a", "wrong-b", "wrong-c"],
        ["wrong-a", "correct", "wrong-b", "wrong-c"],
        ["wrong-a", "wrong-b", "correct", "wrong-c"],
        ["wrong-a", "wrong-b", "wrong-c", "correct"],
    ]
    for i in range(question_index + 1):
        qid = uuid4()
        data["questions"].append(SimpleNamespace(id=qid, quiz_id=quiz_id, text=f"question-{i}", type="MCQ",
            points=1, explanation="explanation", source_quote="source", order_index=i, pool_group=None))
        for index, text in enumerate(orders[i]):
            data["choices"].append(SimpleNamespace(id=uuid4(), question_id=qid, text=text,
                                                  is_correct=text == "correct", order_index=index))
    data["lessons"][0].duration_seconds = _estimate_lesson_duration_seconds("body", question_index + 1)
    prior = data["intent"]
    digest = output_digest(structure=state.structure, content=state.content, assessment=state.assessment,
        source_document_ids=state.source_document_ids, source_strategy=state.source_strategy,
        source_combination_goal=state.source_combination_goal, source_analysis=state.source_analysis,
        source_review_required=state.server_source_review_required, reuse_reason=state.reuse_reason)
    new = make_intent(tenant_id=prior["tenant_id"], user_id=prior["user_id"], job_id=prior["job_id"],
        delivery_id=prior["delivery_id"], route_policy=prior["route_policy"], route_fingerprint=prior["route_fingerprint"],
        documents=prior["documents"], output_digest=digest)
    data["intent"] = new
    data["job"].result = resolve_intent(install_intent({"delivery_task_id": "delivery"}, new), new,
                                        course_id=str(data["course"].id), output_digest=digest)
    assert verify_snapshot(**data)
    assert state.assessment == untouched
    data["choices"][-1].text = "tampered"
    assert not verify_snapshot(**data)
    assert state.assessment == untouched


@pytest.mark.parametrize("field,value", [("stage", "saving"), ("progress", 98), ("message", "wrong"),
                                          ("completed_at", None), ("updated_at", None), ("errors", ["old_error"])])
def test_contradictory_completed_job_projection_holds(field, value):
    data = fixture()
    setattr(data["job"], field, value)
    assert not verify_snapshot(**data)


def test_wrong_progress_detail_or_v2_completion_holds():
    data = fixture()
    data["job"].params["progress_detail"] = {"current": 0}
    assert not verify_snapshot(**data)
    data = fixture()
    data["job"].params["completion"] = {"outcome": "completed"}
    assert not verify_snapshot(**data)
