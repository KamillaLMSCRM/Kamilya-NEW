"""Assessment Agent — Question schemas (matching SCORM agents patterns)."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field


@dataclass
class MCQOption:
    text: str
    is_correct: bool


@dataclass
class MCQQuestion:
    question: str
    options: list[MCQOption] = field(default_factory=list)
    explanation: str = ""
    quality_score: float = 3.0

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict):
            return None
        try:
            return cls(
                question=data["question"],
                options=[MCQOption(**o) for o in data.get("options", [])],
                explanation=data.get("explanation", ""),
                quality_score=data.get("quality_score", 3.0),
            )
        except (KeyError, TypeError):
            return None


@dataclass
class TrueFalseQuestion:
    statement: str
    is_true: bool
    explanation: str = ""
    quality_score: float = 3.0

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict):
            return None
        try:
            return cls(
                statement=data["statement"],
                is_true=data["is_true"],
                explanation=data.get("explanation", ""),
                quality_score=data.get("quality_score", 3.0),
            )
        except (KeyError, TypeError):
            return None


@dataclass
class MatchingPair:
    left: str
    right: str


@dataclass
class MatchingQuestion:
    instruction: str
    pairs: list[MatchingPair] = field(default_factory=list)
    quality_score: float = 3.0

    def to_dict(self):
        return {
            "instruction": self.instruction,
            "pairs": [asdict(p) for p in self.pairs],
            "quality_score": self.quality_score,
        }

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict):
            return None
        try:
            return cls(
                instruction=data["instruction"],
                pairs=[MatchingPair(**p) for p in data.get("pairs", [])],
                quality_score=data.get("quality_score", 3.0),
            )
        except (KeyError, TypeError):
            return None


@dataclass
class LessonAssessment:
    lesson_title: str
    mcq: list[MCQQuestion] = field(default_factory=list)
    true_false: list[TrueFalseQuestion] = field(default_factory=list)
    matching: list[MatchingQuestion] = field(default_factory=list)

    def to_dict(self):
        return {
            "lesson_title": self.lesson_title,
            "mcq": [q.to_dict() for q in self.mcq],
            "true_false": [q.to_dict() for q in self.true_false],
            "matching": [q.to_dict() for q in self.matching],
        }

    @classmethod
    def from_dict(cls, data):
        mcq = [q for q in (MCQQuestion.from_dict(q) for q in data.get("mcq", [])) if q]
        tf = [q for q in (TrueFalseQuestion.from_dict(q) for q in data.get("true_false", [])) if q]
        matching = [q for q in (MatchingQuestion.from_dict(q) for q in data.get("matching", [])) if q]
        return cls(
            lesson_title=data["lesson_title"],
            mcq=mcq,
            true_false=tf,
            matching=matching,
        )


@dataclass
class CourseAssessment:
    assessments: list[LessonAssessment] = field(default_factory=list)

    def to_dict(self):
        return {"assessments": [a.to_dict() for a in self.assessments]}

    def to_json(self):
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    @classmethod
    def from_dict(cls, data):
        return cls(
            assessments=[LessonAssessment.from_dict(a) for a in data.get("assessments", [])]
        )

    @classmethod
    def from_json(cls, data):
        return cls.from_dict(json.loads(data))


# JSON Schema for structured output
ASSESSMENT_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "mcq": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "options": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "text": {"type": "string"},
                                "is_correct": {"type": "boolean"},
                            },
                            "required": ["text", "is_correct"],
                        },
                        "minItems": 4,
                        "maxItems": 4,
                    },
                    "explanation": {"type": "string"},
                    "quality_score": {"type": "number", "minimum": 1, "maximum": 5},
                },
                "required": ["question", "options", "explanation"],
            },
            "minItems": 3,
            "maxItems": 5,
        },
        "true_false": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "statement": {"type": "string"},
                    "is_true": {"type": "boolean"},
                    "explanation": {"type": "string"},
                    "quality_score": {"type": "number", "minimum": 1, "maximum": 5},
                },
                "required": ["statement", "is_true", "explanation"],
            },
            "minItems": 2,
            "maxItems": 3,
        },
        "matching": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "instruction": {"type": "string"},
                    "pairs": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "left": {"type": "string"},
                                "right": {"type": "string"},
                            },
                            "required": ["left", "right"],
                        },
                        "minItems": 4,
                        "maxItems": 6,
                    },
                    "quality_score": {"type": "number", "minimum": 1, "maximum": 5},
                },
                "required": ["instruction", "pairs"],
            },
            "minItems": 1,
            "maxItems": 1,
        },
    },
    "required": ["mcq", "true_false", "matching"],
}
