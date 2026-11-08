"""Что модуль дописывает в руководство навыка: записи памяти с тегом этого навыка."""

from __future__ import annotations

from jericho.modules.memory.book import MemoryBook


def memory_section(book: MemoryBook, skill: str) -> str:
    memories = book.of_skill(skill)
    if not memories:
        return ""
    lines = (f"- {m.text}" for m in memories)
    return "\n".join(("# ПАМЯТЬ", "Что пользователь говорил об этом — его слова, следуй им:", *lines))
