"""Loads and caches Jinja templates from app/prompts/templates/ by (name, version).

Usage:
    prompts = PromptRegistry(settings.prompts_dir)
    text = prompts.render("claim_extract", version="v1", slide_text=slide_text)
"""
from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape


class PromptRegistry:
    def __init__(self, templates_dir: Path) -> None:
        self._env = Environment(
            loader=FileSystemLoader(str(templates_dir)),
            autoescape=select_autoescape(disabled_extensions=("jinja",)),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self._names = [p.stem for p in templates_dir.glob("*.jinja")]

    def __len__(self) -> int:
        return len(self._names)

    def render(self, name: str, version: str = "v1", **context) -> str:
        return self._env.get_template(f"{name}.{version}.jinja").render(**context)