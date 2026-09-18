from __future__ import annotations

from .domain import JsonObject, Rubric

_YES_NO = {
    "true": "The condition is directly satisfied by the supplied state.",
    "false": "The condition is not satisfied, is contradicted, or cannot be established from the supplied state.",
}

LESSON_QUESTIONS: dict[str, JsonObject] = {
    "claims_supported": {
        "type": "noul",
        "instructions": "Are the learner-visible factual claims supported by the supplied source excerpt?",
        "criteria": _YES_NO,
    },
    "objective_alignment": {
        "type": "noul",
        "instructions": "Does the lesson content teach the stated learning objectives?",
        "criteria": _YES_NO,
    },
    "coherent_focus": {
        "type": "noul",
        "instructions": "Does this lesson have one coherent teachable focus rather than unrelated fragments?",
        "criteria": _YES_NO,
    },
    "mostly_source_repetition": {
        "type": "noul",
        "instructions": "Is the lesson mostly a near-verbatim repetition or table dump with little instructional transformation?",
        "criteria": _YES_NO,
    },
    "practical_value": {
        "type": "score",
        "instructions": "How useful is this lesson for a learner who must apply the source material?",
        "criteria": [
            "No usable learning value",
            "Limited value; facts are present but poorly teachable",
            "Useful and understandable",
            "Strongly useful, focused, and actionable",
        ],
    },
}

QUESTION_QUESTIONS: dict[str, JsonObject] = {
    "source_support": {
        "type": "noul",
        "instructions": "Is the keyed correct answer directly supported by the supplied source excerpt?",
        "criteria": _YES_NO,
    },
    "exactly_one_correct": {
        "type": "noul",
        "instructions": "Considering the source and the meaning of every option, is exactly one option correct?",
        "criteria": _YES_NO,
    },
    "distractors_distinct": {
        "type": "noul",
        "instructions": "Are all incorrect options semantically distinct from the correct answer and from one another?",
        "criteria": _YES_NO,
    },
    "distractors_plausible": {
        "type": "noul",
        "instructions": "Are the incorrect options plausible enough to test knowledge without becoming additional correct answers?",
        "criteria": _YES_NO,
    },
    "atomic": {
        "type": "noul",
        "instructions": "Does the question test one clear fact or decision without combining unrelated judgments?",
        "criteria": _YES_NO,
    },
    "explanation_grounded": {
        "type": "noul",
        "instructions": "Does the explanation correctly justify the keyed answer using the supplied source?",
        "criteria": _YES_NO,
    },
    "educational_value": {
        "type": "score",
        "instructions": "How well does this question test meaningful understanding of the source?",
        "criteria": [
            "No educational value or generic/meta wording",
            "Weak recall with little discrimination",
            "Useful knowledge check",
            "Strong, specific, and discriminating knowledge check",
        ],
    },
}

DEFAULT_RUBRIC = Rubric(
    version="typesafe-course-quality-v1",
    model="jev-1.13.0",
    enforcement="report_only",
    lesson_questions=LESSON_QUESTIONS,
    question_questions=QUESTION_QUESTIONS,
)
