"""Tests for the Jinja2 PromptRenderer and its integration with architect.py.

These tests cover the spike's three goals:
1. Static system prompt loads cleanly from prompts/architect/system.md
2. Variable substitution works for future dynamic prompts
3. Autoescape protects against prompt injection through user-supplied content
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.ml_prompts import PromptRenderer, get_renderer
from app.ml_prompts.renderer import PromptRenderer as _PromptRenderer

_PROMPTS_DIR = get_renderer().env.loader.searchpath[0] if hasattr(get_renderer(), "env") else None


def _make_renderer() -> PromptRenderer:
    """Construct a renderer pointing at the package's prompts/ dir."""
    from pathlib import Path
    prompts_dir = Path(__file__).resolve().parents[3] / "packages" / "ml_pipeline" / "prompts"
    return PromptRenderer(templates_dir=prompts_dir)


def test_render_static_system_prompt():
    """The architect system prompt template loads and contains its key sections."""
    output = get_renderer().render("architect/system.md")

    # Substantive content checks — these would break loudly if anyone trimmed
    # the template by accident.
    assert "Course Architect" in output
    assert "## Output" in output
    assert "JSON" in output
    assert "list_documents()" in output
    assert "get_chapter_text" in output
    # Length sanity — the prompt should be substantive, not an empty stub.
    assert len(output) > 1000


def test_render_with_variables():
    """Variable substitution via {{ var }} works as expected."""
    r = _make_renderer()

    # Use render_string for a synthetic test template — avoids filesystem dependencies.
    template = "Hello {{ name }}, your course is in {{ language }}."
    out = r.render_string(template, name="Askar", language="Kazakh")
    assert out == "Hello Askar, your course is in Kazakh."


def test_autoescape_blocks_injection():
    """User input with HTML/markdown special chars is auto-escaped.

    This is the prompt-injection defense: an attacker controlling course title
    or document content cannot inject new LLM instructions via raw markup.
    """
    r = _make_renderer()

    # 1) HTML/markdown special chars MUST be escaped to entities.
    html_payload = "<script>alert('xss')</script>"
    out = r.render_string("Title: {{ title }}", title=html_payload)
    assert "<script>" not in out, f"<script> tag leaked: {out!r}"
    assert "&lt;script&gt;" in out, f"< not escaped to entity: {out!r}"

    # 2) Jinja2 directives passed as VARIABLES are NOT re-interpreted.
    #    {{ x }} passed as a value stays as literal text in output, not as
    #    a new template directive. This is the prompt-injection defense.
    directive_payload = "{{ evil_template_directive }}"
    out = r.render_string("Title: {{ title }}", title=directive_payload)
    assert out == "Title: {{ evil_template_directive }}", (
        f"Variable was re-interpreted as directive: {out!r}"
    )

    # 3) {% include %} passed as a value: still not re-interpreted as a
    #    template directive (autoescape may entity-escape its quotes, but
    #    the directive is never executed). Confirm it appears in output
    #    with the literal `{% include` prefix.
    include_payload = "{% include '/etc/passwd' %}"
    out = r.render_string("Title: {{ title }}", title=include_payload)
    assert "{% include" in out, f"Include directive did not appear: {out!r}"
    assert "/etc/passwd" in out, f"Path disappeared: {out!r}"

    # 4) SQL-shaped injection — quotes are entity-escaped, so the rendered
    #    prompt cannot break out of a hypothetical SQL context downstream.
    sql_payload = '"; DROP TABLE users; --'
    out = r.render_string("Title: {{ title }}", title=sql_payload)
    assert '"' not in out or "&#34;" in out, f"Quote leaked raw: {out!r}"


def test_get_renderer_is_singleton():
    """get_renderer() returns the same instance — prompt cache is shared."""
    r1 = get_renderer()
    r2 = get_renderer()
    assert r1 is r2


def test_architect_uses_renderer():
    """architect.SYSTEM_PROMPT is loaded through the renderer.

    This is the integration check: a regression in the import or
    template content would break architect.py startup, which is exactly
    the spike's proof-of-concept.
    """
    from app.modules.ai.architect import SYSTEM_PROMPT  # noqa: F401

    # Same content checks as the static test — duplicate intentionally so a
    # broken refactor fails both tests rather than only the integration one.
    assert "Course Architect" in SYSTEM_PROMPT
    assert "## Output" in SYSTEM_PROMPT


# ── writer.py ─────────────────────────────────────────────────────────────


def test_writer_system_prompt_template():
    """writer/system.md template renders correctly."""
    output = get_renderer().render("writer/system.md")

    assert "Course Content Writer" in output
    assert "Markdown" in output
    assert "TARGET LANGUAGE" in output
    assert "anti-repetition" in output
    assert len(output) > 500


def test_writer_uses_renderer():
    """writer.GENERATION_PROMPT is loaded through the renderer."""
    from app.modules.ai.writer import GENERATION_PROMPT  # noqa: F401

    assert "Course Content Writer" in GENERATION_PROMPT
    assert "Markdown" in GENERATION_PROMPT
    assert "anti-repetition" in GENERATION_PROMPT


# ── reviewer.py ───────────────────────────────────────────────────────────


def test_reviewer_system_prompt_template():
    """reviewer/system.md template renders correctly."""
    output = get_renderer().render("reviewer/system.md")

    assert "course content quality reviewer" in output
    assert "quality_score" in output
    assert "language_match" in output
    assert "Return ONLY valid JSON" in output
    assert len(output) > 400


def test_reviewer_uses_renderer():
    """reviewer.REVIEW_PROMPT is loaded through the renderer."""
    from app.modules.ai.reviewer import REVIEW_PROMPT  # noqa: F401

    assert "course content quality reviewer" in REVIEW_PROMPT
    assert "Return ONLY valid JSON" in REVIEW_PROMPT


# ── assessment.py ─────────────────────────────────────────────────────────


def test_assessment_system_prompt_template():
    """assessment/system.md template renders correctly."""
    output = get_renderer().render("assessment/system.md")

    assert "assessment designer" in output
    assert "valid JSON" in output
    assert len(output) > 30


def test_assessment_uses_renderer():
    """assessment imports get_renderer (system_prompt is built at runtime)."""
    import app.modules.ai.assessment as assessment_module  # noqa: F401

    src = Path(assessment_module.__file__).read_text(encoding="utf-8")
    assert "get_renderer().render(\"assessment/system.md\")" in src


# ── router.py ─────────────────────────────────────────────────────────────


def test_router_methodology_review_template():
    """router/system_methodology_review.md template renders correctly."""
    output = get_renderer().render("router/system_methodology_review.md")

    assert "ассистент методолога LMS Kamilya" in output
    assert "APPLY_LESSON" in output
    assert "UUID" in output
    assert "В материалах курса этого нет" in output
    assert "размеры штрафов" in output
    assert len(output) > 300


def test_router_architect_module_regen_template():
    """router/system_architect_module_regen.md template renders correctly."""
    output = get_renderer().render("router/system_architect_module_regen.md")

    assert "архитектор курсов" in output
    assert "валидным JSON" in output
    assert "markdown" in output


def test_router_writer_lesson_regen_template():
    """router/system_writer_lesson_regen.md template renders correctly."""
    output = get_renderer().render("router/system_writer_lesson_regen.md")

    assert "автор LMS-уроков на русском" in output
    assert "текстом урока" in output


def test_router_writer_lesson_regen_module_template():
    """router/system_writer_lesson_regen_module.md template renders correctly.

    Note: this is the same content as system_writer_lesson_regen.md except
    it says 'без markdown' (without markdown) at the end — the module-regen
    variant is stricter about not including markdown.
    """
    output = get_renderer().render("router/system_writer_lesson_regen_module.md")

    assert "автор LMS-уроков на русском" in output
    assert "без markdown" in output


def test_router_quiz_regen_template():
    """router/system_quiz_regen.md template renders correctly."""
    output = get_renderer().render("router/system_quiz_regen.md")

    assert "автор тестов" in output
    assert "валидным JSON" in output


def test_router_quiz_regen_module_template():
    """router/system_quiz_regen_module.md template renders correctly."""
    output = get_renderer().render("router/system_quiz_regen_module.md")

    assert "автор тестов" in output
    assert "валидным JSON" in output


def test_router_uses_renderer():
    """router.py keeps templates for chat, planning, and quiz generation.

    Integration check: a regression in any of the 5 prompt calls (or missing
    import) would break router.py imports — exactly what we want to catch.
    """
    import app.modules.ai.router as router_module  # noqa: F401

    src = Path(router_module.__file__).read_text(encoding="utf-8")
    assert "from app.ml_prompts import get_renderer" in src
    # Lesson rewriting moved to the grounded Writer pipeline; four router
    # templates remain for chat, module planning, and quiz generation.
    assert src.count('get_renderer().render("router/') >= 4


# ── cross-cutting ─────────────────────────────────────────────────────────


def test_all_prompt_templates_listed_in_prompts_dir():
    """Every prompt template under prompts/ (except README.md) is renderable.

    Catches typos in template names or missing files.
    """
    from pathlib import Path
    prompts_root = Path(__file__).resolve().parents[3] / "packages" / "ml_pipeline" / "prompts"
    md_files = sorted(
        md for md in prompts_root.rglob("*.md") if md.name.lower() != "readme.md"
    )

    assert len(md_files) >= 10, f"Expected ≥10 prompt .md templates (1 architect + 9 new), got {len(md_files)}: {md_files}"

    renderer = get_renderer()
    for md in md_files:
        rel = md.relative_to(prompts_root).as_posix()
        # Render — must not raise
        out = renderer.render(rel)
        assert isinstance(out, str)
        assert len(out) > 0, f"{rel} rendered empty"
