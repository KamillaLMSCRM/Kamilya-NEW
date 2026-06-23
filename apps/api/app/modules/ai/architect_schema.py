"""Architect Agent — Course structure schemas (matching SCORM agents patterns)."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field


@dataclass
class LearningObjective:
    """A single learning objective for a lesson."""
    text: str


@dataclass
class Lesson:
    """A lesson within a module."""
    title: str
    objectives: list[LearningObjective] = field(default_factory=list)
    description: str = ""
    source_doc_ids: list[str] = field(default_factory=list)
    relevant_headings: list[str] = field(default_factory=list)


@dataclass
class Module:
    """A module containing multiple lessons."""
    title: str
    description: str = ""
    lessons: list[Lesson] = field(default_factory=list)


@dataclass
class CourseStructure:
    """Complete course structure — modules → lessons → learning objectives."""
    title: str
    description: str = ""
    modules: list[Module] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, data: str) -> CourseStructure:
        raw = json.loads(data)
        return cls._from_dict(raw)

    @classmethod
    def _from_dict(cls, raw: dict) -> CourseStructure:
        modules = []
        for m in raw.get("modules", []):
            lessons = []
            for l in m.get("lessons", []):
                objs = [
                    LearningObjective(text=o) if isinstance(o, str)
                    else LearningObjective(**o)
                    for o in l.get("objectives", [])
                ]
                lessons.append(
                    Lesson(
                        title=l.get("title", ""),
                        objectives=objs,
                        description=l.get("description", ""),
                        source_doc_ids=l.get("source_doc_ids", []),
                        relevant_headings=l.get("relevant_headings", []),
                    )
                )
            modules.append(Module(title=m.get("title", ""), description=m.get("description", ""), lessons=lessons))
        return cls(
            title=raw.get("title", ""),
            description=raw.get("description", ""),
            modules=modules,
        )
