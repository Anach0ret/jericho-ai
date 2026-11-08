"""Что модуль дописывает в руководство навыка: выученное о нём."""

from __future__ import annotations

from jericho.modules.notes.notebook import Notebook


def learned_section(notebook: Notebook, skill: str) -> str:
    """Заметки о навыке. Нет заметок — нет и раздела: как их писать, сказано в разделе модуля в общем промпте."""
    notes = notebook.of(skill)
    if not notes:
        return ""
    learned =(f"- «{note.name}» → {note.value}" for note in notes)
    return "\n".join(("# ЗАМЕТКИ", "Выучено из прошлых фраз — пользуйся, не выясняя заново:", *learned))
