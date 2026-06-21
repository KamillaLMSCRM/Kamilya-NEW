"""Writer Agent — Content output schemas (matching SCORM agents patterns)."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field


@dataclass
class LessonContent:
    """Generated content for a single lesson with source citations."""
    title: str
    objectives: list[str] = field(default_factory=list)
    content: str = ""
    source_chunks: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> LessonContent:
        return cls(**data)


@dataclass
class ModuleContent:
    """Generated content for a module — aggregates lessons."""
    title: str
    lessons: list[LessonContent] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"title": self.title, "lessons": [l.to_dict() for l in self.lessons]}

    @classmethod
    def from_dict(cls, data: dict) -> ModuleContent:
        return cls(
            title=data["title"],
            lessons=[LessonContent.from_dict(l) for l in data.get("lessons", [])],
        )


@dataclass
class CourseContent:
    """Full generated course content — modules -> lessons -> markdown + citations."""
    title: str
    description: str = ""
    modules: list[ModuleContent] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "description": self.description,
            "modules": [m.to_dict() for m in self.modules],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    @classmethod
    def from_dict(cls, data: dict) -> CourseContent:
        return cls(
            title=data["title"],
            description=data.get("description", ""),
            modules=[ModuleContent.from_dict(m) for m in data.get("modules", [])],
        )

    @classmethod
    def from_json(cls, data: str) -> CourseContent:
        return cls.from_dict(json.loads(data))
