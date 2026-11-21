"""Bilingual branching practice stored in the existing lesson release blocks."""

from collections.abc import Iterator
from hashlib import sha256
from typing import Annotated, Any, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError, model_validator

BLOCK_TYPE = "decision_practice"
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=180)]
BodyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2500)]


class PracticeModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PracticeLabel(PracticeModel):
    ru: ShortText
    kk: ShortText


class PracticeBody(PracticeModel):
    ru: BodyText
    kk: BodyText


class PracticeChoice(PracticeModel):
    label: PracticeLabel
    target: UUID


class PracticeStep(PracticeModel):
    id: UUID
    text: PracticeBody
    choices: list[PracticeChoice] = Field(max_length=4)


class DecisionPractice(PracticeModel):
    title: PracticeLabel
    steps: list[PracticeStep] = Field(min_length=3, max_length=12)

    @model_validator(mode="after")
    def check_paths(self) -> Self:
        steps = {step.id: step for step in self.steps}
        if len(steps) != len(self.steps):
            raise ValueError("duplicate_step")
        first = self.steps[0]
        if len({choice.target for choice in first.choices}) < 2:
            raise ValueError("first_step_requires_two_destinations")
        for step in self.steps:
            if any(choice.target not in steps for choice in step.choices):
                raise ValueError("unknown_destination")
            for lang in ("ru", "kk"):
                labels = {getattr(choice.label, lang).casefold() for choice in step.choices}
                if len(labels) != len(step.choices):
                    raise ValueError("duplicate_choice_label")

        visited: set[UUID] = set()
        active: set[UUID] = set()

        def visit(step_id: UUID) -> None:
            if step_id in active:
                raise ValueError("loop_in_practice")
            if step_id in visited:
                return
            active.add(step_id)
            for choice in steps[step_id].choices:
                visit(choice.target)
            active.remove(step_id)
            visited.add(step_id)

        visit(first.id)
        if visited != steps.keys():
            raise ValueError("unreachable_step")
        return self


class PracticeEdition(PracticeModel):
    revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    practice: DecisionPractice


def practice_edition(lesson: dict[str, Any]) -> PracticeEdition | None:
    blocks = [block for block in lesson.get("content_blocks", []) if block.get("block_type") == BLOCK_TYPE]
    if len(blocks) != 1:
        return None
    raw = blocks[0].get("content")
    if not isinstance(raw, str):
        return None
    try:
        practice = DecisionPractice.model_validate_json(raw)
    except ValidationError:
        return None
    return PracticeEdition(revision=sha256(raw.encode()).hexdigest(), practice=practice)


def published_practices(snapshot: dict[str, Any]) -> Iterator[tuple[str, PracticeEdition]]:
    for module in snapshot.get("modules", []):
        for lesson in module.get("lessons", []):
            if edition := practice_edition(lesson):
                yield str(lesson["id"]), edition
