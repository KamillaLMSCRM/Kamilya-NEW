import json
from importlib import util
from pathlib import Path
from types import SimpleNamespace

SCRIPT = Path(__file__).resolve().parents[4] / "scripts" / "ops" / "course_quality_dev_acceptance.py"
SPEC = util.spec_from_file_location("course_quality_dev_acceptance", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


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
