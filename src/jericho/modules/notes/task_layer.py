"""Слой «заметки»: о новой заметке пользователь узнаёт из ответа."""

from __future__ import annotations

from dataclasses import replace

from jericho.core.agent.task import Outcome, Task, TaskHandler
from jericho.modules.notes.notebook import Notebook


class NewNotes:
    """Сравнивает заметки до и после поручения и дописывает в ответ, что запомнено.

    Заметку пишет модель в другом процессе; сказать о ней пользователю — дело кода, а не её доброй воли.
    """

    def __init__(self, notebook: Notebook) -> None:
        self._notebook = notebook

    def handle(self, task: Task, proceed: TaskHandler) -> Outcome:
        known = self._notes()
        outcome = proceed(task)
        learned = sorted(self._notes() - known)
        if not learned:
            return outcome
        reply = replace(outcome.reply, message=f"{outcome.reply.message} · запомнил: {'; '.join(learned)}")   # body отчёта — как был
        return Outcome(reply, {**outcome.details, "remembered": learned})

    def _notes(self) -> set[str]:
        """Заметки вместе со значением: замена значения — тоже новость."""
        return {f"{note.name} → {note.value}" for note in self._notebook.all()}
