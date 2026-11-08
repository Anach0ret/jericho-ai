"""Команда «что Jericho выучил»: заметки модели."""

from __future__ import annotations

import argparse

from jericho.modules.notes.notebook import Notebook


class NotesCommand:
    name = "notes"
    help = "заметки, которые модель записала о повторяющихся просьбах; --forget убирает одну"

    def __init__(self, notebook: Notebook) -> None:
        self._notebook = notebook

    def configure(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--forget", nargs=2, metavar=("НАВЫК", "ИМЯ"), help="убрать заметку: навык и её имя")

    def run(self, args: argparse.Namespace) -> None:
        if args.forget:
            self._forget(*args.forget)
        else:
            self._show()

    def _forget(self, skill: str, name: str) -> None:
        gone = self._notebook.forget(skill, name)
        print(f"Убрал: «{gone.name}» → {gone.value}" if gone else f"У навыка {skill} нет заметки «{name}».")

    def _show(self) -> None:
        notes = self._notebook.all()
        if not notes:
            print("Заметок нет.")
        for note in sorted(notes, key=lambda note: (note.skill, note.name)):
            print(f"{note.added:%d.%m %H:%M}  {note.skill:<9} {note.kind:<8} «{note.name}» → {note.value}")
