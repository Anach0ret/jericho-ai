"""Откуда сборщик промпта берёт тексты и живые данные."""

from __future__ import annotations

from typing import Protocol

from jericho.core.prompting.entities import Skill


class PromptSource(Protocol):
    """Откуда берутся тексты промпта: ядро и навыки."""

    def core(self) -> str: ...

    def skill(self, name: str) -> Skill: ...


class PromptContext(Protocol):
    """Источник подстановок: имя → текст."""

    def values(self) -> dict[str, str]: ...
