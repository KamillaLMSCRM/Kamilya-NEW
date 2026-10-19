"""The deterministic source diagnostic must not retain a hidden fixed-three quota."""
import pytest

from app.modules.ai.evidence_engine.engine import EvidenceCourseEngine
from app.modules.ai.evidence_engine.models import LessonEvidence, SourceFact


@pytest.mark.parametrize("kind", ["narrative", "spreadsheet"])
def test_source_diagnostic_retains_five_independent_assessable_facts(kind: str) -> None:
    facts = [SourceFact(
        f"fact-{i}", f"Проверка заявки типа {i}", "Срок проверки",
        f"Проверка заявки типа {i} проводится в течение {i} рабочих дней.",
        f"section=checks;part={i}",
    ) for i in range(1, 6)]
    lesson = LessonEvidence("lesson", "Правила", "Проверки", "Соблюдать сроки",
                            tuple(f.fact_id for f in facts), (), ())
    assessment = EvidenceCourseEngine._build_assessment(kind, [lesson], facts)
    assert len(assessment.questions) == 5
    assert {q.fact_id for q in assessment.questions} == {f.fact_id for f in facts}
