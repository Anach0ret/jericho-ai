"""Модуль ядра «заметки»: модель записывает, как пользователь что-то называет, и пользуется этим дальше."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from jericho.core.agent.task import TaskLayer
from jericho.core.management.base import Command
from jericho.core.modules.config import ModuleConfig, ModuleServices
from jericho.core.prompting.protocols import PromptContext
from jericho.core.services.paths import Paths
from jericho.core.tools.tool import Tool
from jericho.modules.notes.adapters.json_file import JsonFileNoteStore
from jericho.modules.notes.command import NotesCommand
from jericho.modules.notes.context import NoteNames
from jericho.modules.notes.evidence import JournalEvidence, declared_proofs
from jericho.modules.notes.guide import learned_section
from jericho.modules.notes.kinds import DEFAULT_KINDS
from jericho.modules.notes.notebook import Notebook
from jericho.modules.notes.task_layer import NewNotes
from jericho.modules.notes.tools import Forget, Remember

if TYPE_CHECKING:
    from jericho.core.agent.handle_phrase import HandlePhrase


class NotesModule(ModuleConfig):
    name = "notes"
    requires = ("journal_reader",)      # раздел модуля советует искать повторяющееся в журнале — нужна ручка

    FILE = "notes.json"      # рядом с журналом: заметки живут дольше поручения и сеанса

    def ready(self, services: ModuleServices) -> None:
        self._services = services
        self._file = services.core.paths.state_dir / self.FILE
        self._notebook = Notebook(JsonFileNoteStore(self._file), services.skills.names, DEFAULT_KINDS)

    def tools(self) -> Sequence[Tool[Any]]:
        services = self._services
        evidence = JournalEvidence(services.journal, declared_proofs(services.skills.tools()))
        return (
            Remember(self._notebook, services.session, evidence, services.core.confirmation, services.core.foreign),
            Forget(self._notebook),
        )

    def task_layer(self) -> TaskLayer:
        return NewNotes(self._notebook)

    def contexts(self) -> Sequence[PromptContext]:
        return (NoteNames(self._notebook),)

    def guide_notes(self, skill: str) -> str:
        return learned_section(self._notebook, skill)

    def commands(self, handle_phrase: HandlePhrase) -> Sequence[Command]:
        return (NotesCommand(self._notebook),)

    def status(self) -> Mapping[str, object]:
        """Что модель запомнила — для окна на панели: там лишнее можно убрать (`notes --forget`)."""
        notes = sorted(self._notebook.all(), key=lambda note: (note.skill, note.name))
        return {"notes": [{"skill": note.skill, "kind": note.kind, "name": note.name, "value": note.value} for note in notes]}

    def eval_files(self, paths: Paths) -> Sequence[Path]:
        return (paths.state_dir / self.FILE,)
