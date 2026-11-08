"""Имена заметок в общем промпте: по ним модель понимает, какой навык загрузить."""

from __future__ import annotations

from jericho.modules.notes.notebook import Notebook


class NoteNames:
    """Подстановка `{{note_names}}`: о каком навыке что записано — только имена, значения придут с руководством.

    Без неё заметка видна лишь после `load_skill`. Фраза, искажённая распознаванием («зарегистрируй на актуальную
    версию на стадии курс»), не подсказывала навык — и модель спрашивала адрес, хотя «сайт курса» был записан
    (журнал 21.10.2026).
    """

    def __init__(self, notebook: Notebook) -> None:
        self._notebook = notebook

    def values(self) -> dict[str, str]:
        listed = [(skill, self._notebook.of(skill)) for skill in self._notebook.skills]
        lines = [f"- **{skill}**: " + ", ".join(f"«{note.name}»" for note in notes) for skill, notes in listed if notes]
        if not lines:
            return {"note_names": "Заметок пока нет."}
        return {"note_names": "\n".join(lines)}
