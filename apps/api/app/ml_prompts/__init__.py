"""Jinja2 prompt templates for Kamilya LMS AI agents.

This module was originally at packages/ml_pipeline/ but Render's rootDir
is apps/api/, so the packages/ directory was not deployed. Moved here
as an internal app subpackage. Render-deployable.
"""
from app.ml_prompts.renderer import PromptRenderer, get_renderer

__all__ = ["PromptRenderer", "get_renderer"]