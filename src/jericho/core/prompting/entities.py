"""Тексты промпта: навык, как он записан в SKILL.md."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Skill:
    """Навык: описание для списка навыков, его инструменты и текст инструкций."""

    name: str
    description: str
    tools: tuple[str, ...]
    body: str
