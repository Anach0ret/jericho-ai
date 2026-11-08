"""Сборка системного промпта: текст ядра, список навыков и то, что ядро знает о разговоре."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from jericho.core.prompting.protocols import PromptContext, PromptSource
from jericho.core.prompting.template import render, values_of


class PromptBuilder:
    """Собирает то, что модель получает на каждую фразу.

    Текста навыков здесь нет — только их имена и описания. Руководство навыка модель запрашивает сама,
    ручкой `load_skill`, когда фраза к нему относится (`core/skills/guide.py`).
    """

    PRELOADED = "руководство — ниже, `load_skill` не нужен"

    def __init__(
        self,
        source: PromptSource,
        contexts: Sequence[PromptContext],
        skills: Sequence[str],
        guide: Callable[[str], str] | None = None,
        preloaded: Sequence[str] = (),
        language_note: str = "",
    ) -> None:
        self._source = source
        self._contexts = tuple(contexts)
        self._skill_names = tuple(skills)
        self._guide = guide              # руководство навыка без описаний ручек — для `PRELOADED_SKILLS`
        self._preloaded = tuple(preloaded) if guide is not None else ()
        self._language_note = language_note     # на каком языке отвечать, если не на языке промпта (`Settings.language`)

    def build(self) -> str:
        core = render(self._source.core(), {"skills_index": self._index(), **values_of(self._contexts)}).strip()
        guides = [f"# РУКОВОДСТВО НАВЫКА {name}\n{self._guide(name)}" for name in self._preloaded if self._guide is not None]
        return "\n\n".join(part for part in (core, *guides, self._language_note) if part)

    def _index(self) -> str:
        if not self._skill_names:
            return "Навыков пока нет: действовать нечем. На просьбу что-то сделать отвечай `refused` и скажи об этом."
        skills = (self._source.skill(name) for name in self._skill_names)
        return "\n".join(
            f"- **{skill.name}** — {skill.description}" + (f" ({self.PRELOADED})" if skill.name in self._preloaded else "")
            for skill in skills
        )
