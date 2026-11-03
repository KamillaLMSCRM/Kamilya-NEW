"""One field contract for authorized raw edits and negative-aspect custody."""

from app.modules.ai.source_frame_patch import _FRAME_FIELDS

APPLICATION_REPAIR_FIELDS = {
    "governing_bindings": {"bindings"}, "context": {"context"}, "fixed_source_context": {"context"},
    "source_refs": {"ref"}, "construction_mode": set(_FRAME_FIELDS) | {"__delete__"},
    "source_quote_proposition": set(_FRAME_FIELDS) - {"handle", "ref", "bindings"} | {"__delete__"},
    "answer_components": {"answer", "leaves", "action", "purposes", "branches", "fork", "dimension"},
    "assessed_focus": {"answer", "leaves", "action", "purposes", "branches", "fork", "dimension"},
    "question_format": {"kind", "dimension", "answer", "owner", "leaves", "fork", "action", "purposes", "branches"},
}
