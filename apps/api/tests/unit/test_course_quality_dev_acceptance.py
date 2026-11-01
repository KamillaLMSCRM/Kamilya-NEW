import json
from importlib import util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest

SCRIPT = Path(__file__).resolve().parents[4] / "scripts" / "ops" / "course_quality_dev_acceptance.py"
SPEC = util.spec_from_file_location("course_quality_dev_acceptance", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_dev_worker_keepalive_wakes_once_then_only_after_interval() -> None:
    clock = Mock(side_effect=[100.0, 120.0, 341.0, 341.0])
    response = httpx.Response(
        200,
        text="ok\n",
        request=httpx.Request("GET", "https://worker.example/"),
    )
    request = Mock(return_value=response)
    keepalive = MODULE.WorkerKeepalive(
        "https://worker.example/",
        interval_seconds=240,
        request_get=request,
        clock=clock,
    )

    keepalive.wake()
    keepalive.maintain()
    keepalive.maintain()

    assert request.call_count == 2
    assert all(call.args == ("https://worker.example/",) for call in request.call_args_list)
    assert all(call.kwargs["follow_redirects"] is False for call in request.call_args_list)


@pytest.mark.parametrize(
    "url",
    [
        "http://worker.example/",
        "https://user:password@worker.example/",
        "https://worker.example/?token=secret",
    ],
)
def test_dev_worker_keepalive_rejects_unsafe_health_urls(url: str) -> None:
    with pytest.raises(MODULE.AcceptanceError, match="^worker_health_url_unsafe$"):
        MODULE.WorkerKeepalive(url)


def test_dev_worker_keepalive_requires_exact_small_ok_response() -> None:
    response = httpx.Response(
        200,
        text="unexpected",
        request=httpx.Request("GET", "https://worker.example/"),
    )
    keepalive = MODULE.WorkerKeepalive(
        "https://worker.example/",
        request_get=Mock(return_value=response),
    )

    with pytest.raises(MODULE.AcceptanceError, match="^worker_health_invalid_response$"):
        keepalive.wake()


def test_acceptance_reports_current_api_error_code() -> None:
    response = httpx.Response(
        403,
        json={
            "error": "forbidden",
            "message": "Demo generation limit reached",
            "details": {"code": "demo_limit_exceeded"},
        },
        request=httpx.Request("POST", "https://dev.example/api/v1/ai/generate-course"),
    )

    with pytest.raises(
        MODULE.AcceptanceError,
        match=r"^generation_submit_http_403_demo_limit_exceeded$",
    ):
        MODULE.DevClient._expect(response, {202}, "generation_submit")


def test_acceptance_rejects_options_that_change_only_the_final_word() -> None:
    assert MODULE.choices_share_only_one_word_suffix(
        [
            "в коллекцию входят вешалки гарнитуры и зеркала",
            "в коллекцию входят вешалки гарнитуры и полки",
            "в коллекцию входят вешалки гарнитуры и столы",
            "в коллекцию входят вешалки гарнитуры и шкафы",
        ]
    )


def test_acceptance_allows_distinct_actions_with_same_grammatical_opening() -> None:
    assert not MODULE.choices_share_only_one_word_suffix(
        [
            "показать механизм открывания",
            "показать скрытые ручки",
            "показать минимализм",
            "показать материал МДФ",
        ]
    )


def test_acceptance_flags_contextless_comparison_and_positional_module_title() -> None:
    assert MODULE.has_meta_question("Чем отличается от двух других?")
    assert MODULE.has_meta_question("Как в источнике описана эта коллекция?")
    assert MODULE.has_meta_question("As in the source material, how is this collection described?")
    assert MODULE.has_generic_module_title("Коллекции — раздел 2")
    assert not MODULE.has_generic_module_title("Коллекции: Комоды — Резюме")


def test_acceptance_rejects_question_that_contains_the_correct_answer() -> None:
    choices = [
        {"text": "гостиная и шкафы", "is_correct": True},
        {"text": "спальня и кровать", "is_correct": False},
        {"text": "прихожая и зеркало", "is_correct": False},
    ]

    assert MODULE.question_contains_correct_answer(
        "Что предложить покупателю, которому нужны гостиная и шкафы?",
        choices,
    )
    assert not MODULE.question_contains_correct_answer(
        "Что предложить покупателю для обустройства двух комнат?",
        choices,
    )
    assert not MODULE.question_contains_correct_answer(
        "С какими коллекциями совместима Чикаго Стрит?",
        [
            {
                "text": "Совместима с коллекциями Чикаго и Чикаго Нео",
                "is_correct": True,
            },
            {"text": "Только с коллекцией Феникс", "is_correct": False},
            {"text": "Только с коллекцией Imperial", "is_correct": False},
        ],
    )


def test_acceptance_uses_only_exact_captured_lesson_corpus() -> None:
    evidence = [
        {
            "module_index": 0,
            "lesson_index": 1,
            "title": "Коллекция Альфа",
            "content": "Для Альфы указаны ЛДСП и модульная компоновка.",
            "source_chunks": ["Коллекция Альфа; материал ЛДСП."],
        }
    ]

    assert MODULE.captured_source_chunks_for_lesson(
        evidence,
        module_index=0,
        lesson_index=1,
        title="Коллекция Альфа",
        content="Для Альфы указаны ЛДСП и модульная компоновка.",
    ) == ["Коллекция Альфа; материал ЛДСП."]
    assert (
        MODULE.captured_source_chunks_for_lesson(
            evidence,
            module_index=0,
            lesson_index=1,
            title="Коллекция Альфа",
            content="Для Альфы указана МДФ.",
        )
        is None
    )
    assert (
        MODULE.captured_source_chunks_for_lesson(
            evidence,
            module_index=0,
            lesson_index=2,
            title="Коллекция Альфа",
            content="Для Альфы указаны ЛДСП и модульная компоновка.",
        )
        is None
    )


def test_output_inspection_matches_each_lesson_by_stable_coordinates() -> None:
    first_content = "Для Альфы указаны ЛДСП и модульная компоновка."
    second_content = "Для Беты указаны МДФ и светлые фасады."
    preview = {
        "modules": [
            {
                "lessons": [
                    {
                        "title": "Коллекция",
                        "content_preview": first_content,
                        "source_validation_status": "verified",
                        "source_document_ids": ["doc"],
                        "source_references": [{"chunk_id": "one"}],
                    },
                    {
                        "title": "Коллекция",
                        "content_preview": second_content,
                        "source_validation_status": "verified",
                        "source_document_ids": ["doc"],
                        "source_references": [{"chunk_id": "two"}],
                    },
                ]
            }
        ]
    }
    evidence = [
        {
            "module_index": 0,
            "lesson_index": 0,
            "title": "Коллекция",
            "content": first_content,
            "source_chunks": ["Альфа: ЛДСП, модульная компоновка."],
        },
        {
            "module_index": 0,
            "lesson_index": 1,
            "title": "Коллекция",
            "content": second_content,
            "source_chunks": ["Бета: МДФ, светлые фасады."],
        },
    ]

    failures, facts = MODULE.inspect_output(
        preview,
        quizzes=[],
        recommendation={"recommended_total_lessons": 2},
        focus_terms=set(),
        accepted_lesson_evidence=evidence,
        require_captured_evidence=True,
    )

    assert "lesson_acceptance_source_evidence_missing" not in failures
    assert "lesson_quality_readback_mismatch" not in failures
    assert facts["captured_lesson_evidence_matches"] == 2


def test_output_inspection_rejects_blind_fixed_position_and_longest_strategies() -> None:
    lesson_content = "Для коллекции Альфа указана единая платформа для всей квартиры."
    preview = {
        "modules": [
            {
                "title": "Коллекция Альфа",
                "lessons": [
                    {
                        "title": "Преимущества коллекции Альфа",
                        "content_preview": lesson_content,
                        "source_validation_status": "verified",
                        "source_document_ids": ["doc"],
                        "source_references": [{"chunk_id": "one"}],
                        "quiz_id": "quiz-1",
                    }
                ],
            }
        ],
    }
    questions = [
        {
            "id": f"question-{index}",
            "text": f"Какое преимущество указано для коллекции Альфа, вариант {index}?",
            "explanation": lesson_content,
            "choices": [
                {"text": "единая платформа для всей квартиры", "is_correct": True},
                {"text": "светлые фасады", "is_correct": False},
                {"text": "открытые секции", "is_correct": False},
                {"text": "скрытые ручки", "is_correct": False},
            ],
        }
        for index in range(5)
    ]

    failures, facts = MODULE.inspect_output(
        preview,
        quizzes=[
            {
                "id": "quiz-1",
                "pass_score": 80,
                "review_status": "needs_review",
                "questions": questions,
            }
        ],
        recommendation={"recommended_total_lessons": 1},
        focus_terms=set(),
        accepted_lesson_evidence=[
            {
                "module_index": 0,
                "lesson_index": 0,
                "title": "Преимущества коллекции Альфа",
                "content": lesson_content,
                "source_chunks": [lesson_content],
            }
        ],
        require_captured_evidence=True,
    )

    assert "blind_fixed_position_can_pass" in failures
    assert "blind_longest_answer_can_pass" in failures
    assert facts["blind_fixed_position_quizzes"] == 1
    assert facts["blind_longest_answer_quizzes"] == 1


def test_output_inspection_does_not_apply_position_strategy_to_single_question_quiz() -> None:
    lesson_content = "Для коллекции Альфа указана единая платформа для всей квартиры."
    preview = {
        "modules": [
            {
                "title": "Коллекция Альфа",
                "lessons": [
                    {
                        "title": "Преимущества коллекции Альфа",
                        "content_preview": lesson_content,
                        "source_validation_status": "verified",
                        "source_document_ids": ["doc"],
                        "source_references": [{"chunk_id": "one"}],
                        "quiz_id": "quiz-1",
                    }
                ],
            }
        ],
    }
    question = {
        "id": "question-1",
        "text": "Какое преимущество указано для коллекции Альфа?",
        "explanation": lesson_content,
        "choices": [
            {"text": "единая платформа для всей квартиры", "is_correct": True},
            {"text": "светлые фасады", "is_correct": False},
            {"text": "открытые секции", "is_correct": False},
        ],
    }

    failures, facts = MODULE.inspect_output(
        preview,
        quizzes=[
            {
                "id": "quiz-1",
                "pass_score": 80,
                "review_status": "needs_review",
                "questions": [question],
            }
        ],
        recommendation={"recommended_total_lessons": 1},
        focus_terms=set(),
        accepted_lesson_evidence=[],
        require_captured_evidence=False,
    )

    assert "blind_fixed_position_can_pass" not in failures
    assert facts["blind_fixed_position_quizzes"] == 0


def test_v2_state_exposes_exact_lesson_evidence_for_readback() -> None:
    state = SimpleNamespace(
        content=SimpleNamespace(
            modules=[
                SimpleNamespace(
                    lessons=[
                        SimpleNamespace(
                            title="Коллекция Альфа",
                            content="Подтверждённые сведения об Альфе.",
                            source_chunks=["Альфа: подтверждённое свойство."],
                        )
                    ]
                )
            ]
        ),
        source_analysis={
            "generation_engine": "evidence_v2",
            "evidence_v2": {
                "assessment_review": {
                    "coverage": {"requires_review": False},
                }
            },
        },
    )

    evidence, diagnostics = MODULE.capture_v2_generation_state(state)

    assert evidence == [
        {
            "module_index": 0,
            "lesson_index": 0,
            "title": "Коллекция Альфа",
            "content": "Подтверждённые сведения об Альфе.",
            "source_chunks": ["Альфа: подтверждённое свойство."],
        }
    ]
    assert diagnostics["assessment_review"]["coverage"]["requires_review"] is False


def test_v2_diagnostics_replace_retired_assessment_path_counters() -> None:
    diagnostics = {
        "engine": "evidence_v2",
        "lesson_count": 2,
        "question_count": 4,
        "assessment_review": {
            "coverage": {"requires_review": False},
        },
    }

    assert MODULE.inspect_v2_diagnostics(
        diagnostics,
        expected_lesson_count=2,
        expected_question_count=4,
    ) == []
    assert "v2_assessment_coverage_requires_review" in MODULE.inspect_v2_diagnostics(
        {
            **diagnostics,
            "assessment_review": {"coverage": {"requires_review": True}},
        },
        expected_lesson_count=2,
        expected_question_count=4,
    )


def test_output_inspection_rejects_more_than_three_questions_per_lesson() -> None:
    lesson_content = "Для коллекции Альфа указаны проверяемые характеристики."
    preview = {
        "modules": [
            {
                "title": "Коллекция Альфа",
                "lessons": [
                    {
                        "title": "Характеристики коллекции Альфа",
                        "content_preview": lesson_content,
                        "source_validation_status": "verified",
                        "source_document_ids": ["doc"],
                        "source_references": [{"chunk_id": "one"}],
                        "quiz_id": "quiz-1",
                    }
                ],
            }
        ],
    }
    questions = [
        {
            "id": f"question-{index}",
            "text": f"Какое правило {index} применяется к коллекции Альфа?",
            "explanation": lesson_content,
            "choices": [
                {"text": f"Правило {index}", "is_correct": True},
                {"text": f"Исключение {index}", "is_correct": False},
                {"text": f"Запрет {index}", "is_correct": False},
            ],
        }
        for index in range(4)
    ]

    failures, facts = MODULE.inspect_output(
        preview,
        quizzes=[
            {
                "id": "quiz-1",
                "pass_score": 80,
                "review_status": "needs_review",
                "questions": questions,
            }
        ],
        recommendation={},
        focus_terms=set(),
        accepted_lesson_evidence=[],
        require_captured_evidence=False,
    )

    assert "lesson_question_density_exceeded" in failures
    assert facts["quizzes_over_question_limit"] == 1


def test_output_inspection_does_not_enforce_lightweight_admission_proxy() -> None:
    preview = {
        "modules": [
            {
                "title": "Материалы",
                "lessons": [
                    {
                        "title": f"Урок {index}",
                        "content_preview": "Подтверждённые сведения источника.",
                        "source_validation_status": "verified",
                        "source_document_ids": ["doc"],
                        "source_references": [{"chunk_id": str(index)}],
                    }
                    for index in range(9)
                ],
            }
        ],
    }

    failures, facts = MODULE.inspect_output(
        preview,
        quizzes=[],
        recommendation={
            "recommended_total_lessons": 5,
            "hard_max_total_lessons": 6,
        },
        focus_terms=set(),
        accepted_lesson_evidence=[],
        require_captured_evidence=False,
        enforce_structure_limits=False,
    )

    assert "lesson_count_exceeds_hard_max" not in failures
    assert "lesson_count_exceeds_recommendation" not in failures
    assert facts["lessons"] == 9


def test_operational_metadata_does_not_serialize_review_text(tmp_path: Path) -> None:
    marker = "CUSTOMER-SOURCE-MARKER-DO-NOT-PERSIST"
    review_sample = {
        "modules": [{"lessons": [{"content": marker}]}],
        "questions": [{"text": "Synthetic question", "explanation": marker}],
    }
    review_path = tmp_path / "synthetic-review.json"

    metadata = MODULE.write_synthetic_review_artifact(review_sample, review_path)

    assert marker in review_path.read_text(encoding="utf-8")
    assert marker not in json.dumps(metadata)
    assert set(metadata) == {"created", "sha256", "bytes", "lessons", "questions"}


def test_failed_review_text_stays_only_in_temp_artifact(tmp_path: Path, monkeypatch) -> None:
    marker = "SYNTHETIC-REJECTED-LESSON-MARKER"
    monkeypatch.setattr(MODULE.tempfile, "gettempdir", lambda: str(tmp_path))
    review_path = tmp_path / "failed-review.json"

    metadata = MODULE.write_synthetic_review_artifact(
        {
            "failed_lesson_attempts": [
                {
                    "content": marker,
                    "source_chunks": ["Synthetic source"],
                    "reason_codes": ["unsupported_relationship_claim"],
                }
            ]
        },
        review_path,
    )

    assert marker in review_path.read_text(encoding="utf-8")
    assert marker not in json.dumps(metadata)


def test_approved_fixture_bytes_are_stable_after_source_path_changes(tmp_path: Path, monkeypatch) -> None:
    fixture = tmp_path / "fixture.xlsx"
    approved = b"approved synthetic bytes"
    fixture.write_bytes(approved)
    monkeypatch.setattr(
        MODULE,
        "SYNTHETIC_FIXTURE_SHA256",
        MODULE.hashlib.sha256(approved).hexdigest(),
    )

    captured = MODULE.approved_fixture_bytes(fixture)
    fixture.write_bytes(b"replacement customer bytes")

    assert captured == approved


def test_committed_expanded_workbook_is_the_approved_dev_fixture() -> None:
    fixture = (
        Path(__file__).resolve().parents[1]
        / "fixtures"
        / "course_generation_backward"
        / "expanded_collections.xlsx"
    )

    content = MODULE.approved_fixture_bytes(fixture)

    assert MODULE.fixture_focus_terms(content) == {"север", "берег", "риф"}


def test_local_dev_worker_uses_the_same_evidence_engine_as_new_api_jobs() -> None:
    original = {"documents": ["synthetic-document"]}

    resolved = MODULE.candidate_source_analysis(original)

    assert resolved == {
        "documents": ["synthetic-document"],
        "generation_engine": "evidence_v2",
    }
    assert original == {"documents": ["synthetic-document"]}

@pytest.mark.parametrize("changes", [
    {"tenant_id": "foreign"}, {"user_id": "foreign"}, {"role": "student"},
])
def test_exact_synthetic_identity_rejected_before_upload(changes):
    identity = {"tenant_id": MODULE.QA_TENANT_ID, "user_id": MODULE.QA_METHODOLOGIST_ID, "role": "methodologist"}
    MODULE.verify_synthetic_identity(identity)
    identity.update(changes)
    with pytest.raises(MODULE.AcceptanceError, match="synthetic_user_identity_mismatch"):
        MODULE.verify_synthetic_identity(identity)


@pytest.mark.parametrize("status", ["running", "pending", "interrupted", "reconciliation_required", "unknown"])
def test_cleanup_retains_sources_for_unresolved_job(status):
    client = SimpleNamespace(request=Mock(return_value=SimpleNamespace(status_code=200, json=lambda: {"id": "job", "status": status})))
    safe, reason = MODULE.cleanup_is_safe(client, "job", True)
    assert not safe and reason == "generation_not_terminal"
    client.request.assert_called_once_with("GET", "v1/ai/jobs/job")


@pytest.mark.parametrize("status", ["completed", "failed", "cancelled"])
def test_cleanup_allows_only_confirmed_terminal_status(status):
    client = SimpleNamespace(request=Mock(return_value=SimpleNamespace(status_code=200, json=lambda: {"id": "job", "status": status, "course_id": "course"})))
    assert MODULE.cleanup_is_safe(client, "job", True) == (True, "course")


def test_cleanup_retains_source_on_lost_submit_ack_or_unreadable_status():
    client = SimpleNamespace(request=Mock(side_effect=RuntimeError("unavailable")))
    assert MODULE.cleanup_is_safe(client, "", True) == (False, "generation_submission_unknown")
    client.request.assert_not_called()
    assert MODULE.cleanup_is_safe(client, "job", True) == (False, "generation_status_unknown")
    assert MODULE.cleanup_is_safe(client, "", False) == (True, "")

@pytest.mark.parametrize("document_id", ["", "not-a-uuid", "00000000000000000000000000000001"])
def test_lost_or_malformed_upload_ack_is_not_clean(document_id):
    assert not MODULE.upload_acknowledged(document_id, True)
    assert MODULE.upload_acknowledged(document_id, False)


def test_only_canonical_upload_id_is_acknowledged():
    assert MODULE.upload_acknowledged("00000000-0000-0000-0000-000000000001", True)


def test_exclusive_custody_receipt_keeps_owned_ids_and_intents(tmp_path, monkeypatch):
    root = tmp_path / ".release-evidence"
    root.mkdir()
    monkeypatch.setattr(MODULE, "ROOT", tmp_path)
    path = root / "receipt.jsonl"
    receipt = MODULE.CustodyReceipt(path)
    receipt.record("upload_intent")
    receipt.record("upload_acknowledged", document_id="00000000-0000-0000-0000-000000000001")
    receipt.record("generation_intent", document_id="00000000-0000-0000-0000-000000000001")
    receipt.record("retained", document_id="00000000-0000-0000-0000-000000000001")
    receipt.close()
    events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [event["state"] for event in events] == ["upload_intent", "upload_acknowledged", "generation_intent", "retained"]
    assert events[-1]["document_id"] == "00000000-0000-0000-0000-000000000001"
    assert all(set(event) == {"state", "tenant_id", "user_id", "document_id", "job_id", "course_id"} for event in events)
    with pytest.raises(FileExistsError):
        MODULE.CustodyReceipt(path)


def test_cleanup_refuses_foreign_job_readback():
    client = SimpleNamespace(request=Mock(return_value=SimpleNamespace(status_code=200, json=lambda: {"id": "foreign", "status": "completed"})))
    assert MODULE.cleanup_is_safe(client, "job", True) == (False, "generation_status_unknown")


def test_runner_retains_unknown_upload_and_persists_intent(tmp_path, monkeypatch):
    evidence = tmp_path / ".release-evidence"
    evidence.mkdir()
    xlsx = tmp_path / "synthetic.xlsx"
    xlsx.write_bytes(b"synthetic")
    monkeypatch.setattr(MODULE, "ROOT", tmp_path)
    monkeypatch.setattr(MODULE, "dotenv_values", lambda _path: {"DEV_QA_METHODOLOGIST_EMAIL": "test", "DEV_QA_METHODOLOGIST_PASSWORD": "test"})
    monkeypatch.setattr(MODULE, "approved_fixture_bytes", lambda _path: b"synthetic")
    monkeypatch.setattr(MODULE, "fixture_focus_terms", lambda _content: set())
    monkeypatch.setattr(MODULE, "health_url", lambda _base: "https://synthetic.invalid/health")
    calls = []
    class Client:
        def __init__(self, *args):
            self.http = SimpleNamespace(get=lambda _url: SimpleNamespace(status_code=200, json=lambda: {"release_sha": "sha"}))
        def _expect(self, response, statuses, _label):
            assert response.status_code in statuses
        def login(self):
            return {"user": {"role": "methodologist", "tenant_id": MODULE.QA_TENANT_ID, "user_id": MODULE.QA_METHODOLOGIST_ID}}
        def request(self, method, path, **kwargs):
            calls.append((method, path))
            raise TimeoutError("lost upload ack")
        def close(self): pass
    monkeypatch.setattr(MODULE, "DevClient", Client)
    args = SimpleNamespace(env_file=tmp_path / "env", xlsx=xlsx, custody=evidence / "receipt.jsonl",
        api_base="synthetic", browser_origin="synthetic", expected_release_sha="sha", worker_health_url=None)
    report = MODULE.run(args)
    events = [json.loads(line) for line in args.custody.read_text(encoding="utf-8").splitlines()]
    assert calls == [("POST", "v1/documents/upload")]
    assert [item["state"] for item in events] == ["upload_intent", "retained", "retained"]
    assert report["cleanup"] == {"course": False, "document": False}
    assert "document_upload_outcome_unknown" in report["cleanup_failures"]


@pytest.mark.parametrize("delete_failure", ["error", "lost_ack"])
def test_runner_retains_source_when_course_delete_unconfirmed(tmp_path, monkeypatch, delete_failure):
    evidence = tmp_path / ".release-evidence"
    evidence.mkdir()
    xlsx = tmp_path / "synthetic.xlsx"
    xlsx.write_bytes(b"synthetic")
    monkeypatch.setattr(MODULE, "ROOT", tmp_path)
    monkeypatch.setattr(MODULE, "dotenv_values", lambda _path: {"DEV_QA_METHODOLOGIST_EMAIL": "test", "DEV_QA_METHODOLOGIST_PASSWORD": "test"})
    monkeypatch.setattr(MODULE, "approved_fixture_bytes", lambda _path: b"synthetic")
    monkeypatch.setattr(MODULE, "fixture_focus_terms", lambda _content: set())
    monkeypatch.setattr(MODULE, "health_url", lambda _base: "https://synthetic.invalid/health")
    monkeypatch.setattr(MODULE, "poll_document", lambda *_a, **_kw: {"index": {"chunks_total": 1, "chunks_indexed": 1, "status": "ready"}})
    doc, job, course = ("00000000-0000-0000-0000-000000000001", "00000000-0000-0000-0000-000000000002", "00000000-0000-0000-0000-000000000003")
    monkeypatch.setattr(MODULE, "poll_job", lambda *_a, **_kw: {"status": "completed", "course_id": course})
    calls = []
    def response(code, value): return SimpleNamespace(status_code=code, json=lambda: value)
    class Client:
        def __init__(self, *args):
            self.http = SimpleNamespace(get=lambda _url: response(200, {"release_sha": "sha"}))
        def _expect(self, value, statuses, _label):
            if value.status_code not in statuses:
                raise MODULE.AcceptanceError("synthetic_http_error")
        def login(self): return {"user": {"role": "methodologist", "tenant_id": MODULE.QA_TENANT_ID, "user_id": MODULE.QA_METHODOLOGIST_ID}}
        def request(self, method, path, **kwargs):
            calls.append((method, path))
            if path == "v1/documents/upload":
                return response(201, {"id": doc})
            if path == "v1/ai/document-compatibility":
                return response(200, {})
            if path == "v1/ai/generate-course":
                return response(202, {"id": job})
            if path == f"v1/ai/jobs/{job}":
                return response(200, {"id": job, "status": "completed", "course_id": course})
            if method == "DELETE" and path == f"v1/courses/{course}":
                if delete_failure == "lost_ack":
                    raise TimeoutError("lost delete ack")
                return response(503, {})
            return response(503, {})
        def close(self): pass
    monkeypatch.setattr(MODULE, "DevClient", Client)
    args = SimpleNamespace(env_file=tmp_path / "env", xlsx=xlsx, custody=evidence / "receipt.jsonl",
        api_base="synthetic", browser_origin="synthetic", expected_release_sha="sha", worker_health_url=None,
        index_timeout=1, execute_local_worker=False, generation_timeout=1, review_output=None)
    report = MODULE.run(args)
    assert ("DELETE", f"v1/courses/{course}") in calls
    assert ("DELETE", f"v1/documents/{doc}") not in calls
    assert not report["cleanup"]["course"] and not report["cleanup"]["document"]
    assert "document_retained_course_cleanup_unconfirmed" in report["cleanup_failures"]



@pytest.mark.parametrize("status", ["interrupted", "reconciliation_required"])
def test_runner_held_job_stops_polling_and_retains_receipt_and_sources(tmp_path, monkeypatch, status):
    evidence = tmp_path / ".release-evidence"
    evidence.mkdir()
    xlsx = tmp_path / "synthetic.xlsx"
    xlsx.write_bytes(b"synthetic")
    monkeypatch.setattr(MODULE, "ROOT", tmp_path)
    monkeypatch.setattr(MODULE, "dotenv_values", lambda _path: {"DEV_QA_METHODOLOGIST_EMAIL": "test", "DEV_QA_METHODOLOGIST_PASSWORD": "test"})
    monkeypatch.setattr(MODULE, "approved_fixture_bytes", lambda _path: b"synthetic")
    monkeypatch.setattr(MODULE, "fixture_focus_terms", lambda _content: set())
    monkeypatch.setattr(MODULE, "health_url", lambda _base: "https://synthetic.invalid/health")
    monkeypatch.setattr(MODULE, "poll_document", lambda *_a, **_kw: {"index": {"chunks_total": 1, "chunks_indexed": 1, "status": "ready"}})
    sleep = Mock(side_effect=AssertionError("held job must not poll again"))
    monkeypatch.setattr(MODULE.time, "sleep", sleep)
    doc, job = "00000000-0000-0000-0000-000000000001", "00000000-0000-0000-0000-000000000002"
    calls = []
    def response(code, value): return SimpleNamespace(status_code=code, json=lambda: value)
    class Client:
        def __init__(self, *args):
            self.http = SimpleNamespace(get=lambda _url: response(200, {"release_sha": "sha"}))
        def _expect(self, value, statuses, _label):
            if value.status_code not in statuses:
                raise MODULE.AcceptanceError("synthetic_http_error")
        def login(self): return {"user": {"role": "methodologist", "tenant_id": MODULE.QA_TENANT_ID, "user_id": MODULE.QA_METHODOLOGIST_ID}}
        def request(self, method, path, **kwargs):
            calls.append((method, path))
            if path == "v1/documents/upload":
                return response(201, {"id": doc})
            if path == "v1/ai/document-compatibility":
                return response(200, {})
            if path == "v1/ai/generate-course":
                return response(202, {"id": job})
            if path == f"v1/ai/jobs/{job}":
                return response(200, {"id": job, "status": status, "stage": "interrupted", "progress": 34})
            raise AssertionError("unexpected request")
        def close(self): pass
    monkeypatch.setattr(MODULE, "DevClient", Client)
    args = SimpleNamespace(env_file=tmp_path / "env", xlsx=xlsx, custody=evidence / "receipt.jsonl",
        api_base="synthetic", browser_origin="synthetic", expected_release_sha="sha", worker_health_url=None,
        index_timeout=1, execute_local_worker=False, generation_timeout=60, review_output=None)
    report = MODULE.run(args)
    events = [json.loads(line) for line in args.custody.read_text(encoding="utf-8").splitlines()]
    assert report["generation"]["status"] == status
    assert report["cleanup"] == {"course": False, "document": False}
    assert events[-1]["state"] == "retained" and events[-1]["document_id"] == doc and events[-1]["job_id"] == job
    assert not any(method == "DELETE" or path.endswith("/cancel") for method, path in calls)
    assert sum(path == f"v1/ai/jobs/{job}" for _, path in calls) == 2
    sleep.assert_not_called()
