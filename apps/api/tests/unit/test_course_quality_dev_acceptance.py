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
