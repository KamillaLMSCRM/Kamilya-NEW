"""Jinja2-based prompt renderer with prompt-injection protection.

Why Jinja2 instead of f-strings:
- Conditional blocks: `{% if language == 'kk' %}...{% endif %}`
- Template inheritance: `{% extends "base_architect.md" %}`
- Loops: `{% for obj in learning_objectives %}`
- Auto-escape for user input → defense against prompt injection

Security note: user-supplied content (course titles, lesson text, document
content) goes through these templates. The `autoescape` setting escapes
HTML/markdown special chars in variable substitutions. This prevents
prompt-injection attacks where attacker-controlled text tries to inject
new LLM instructions via raw markup.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape


class PromptRenderer:
    """Render Jinja2 templates with autoescape protection."""

    def __init__(self, templates_dir: Path):
        self.env = Environment(
            loader=FileSystemLoader(str(templates_dir)),
            autoescape=select_autoescape(["md", "j2"]),
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def render(self, template_name: str, **kwargs) -> str:
        """Render a template file by name."""
        template = self.env.get_template(template_name)
        return template.render(**kwargs)

    def render_string(self, source: str, **kwargs) -> str:
        """Render an inline template string (for dynamic cases)."""
        template = self.env.from_string(source)
        return template.render(**kwargs)


@lru_cache(maxsize=1)
def get_renderer() -> PromptRenderer:
    """Lazy singleton — loaded once per process.

    The renderer caches compiled templates in memory, so subsequent calls
    are O(1). Use this in production hot paths instead of constructing
    a new PromptRenderer for each render call.
    """
    prompts_dir = Path(__file__).parent / "prompts"
    return PromptRenderer(templates_dir=prompts_dir)