from importlib import util
from pathlib import Path

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
    assert MODULE.captured_source_chunks_for_lesson(
        evidence,
        module_index=0,
        lesson_index=1,
        title="Коллекция Альфа",
        content="Для Альфы указана МДФ.",
    ) is None
    assert MODULE.captured_source_chunks_for_lesson(
        evidence,
        module_index=0,
        lesson_index=2,
        title="Коллекция Альфа",
        content="Для Альфы указаны ЛДСП и модульная компоновка.",
    ) is None


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
