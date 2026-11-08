from collections.abc import Sequence
from typing import Any

from jericho.core import CoreServices, Risk, SkillConfig, Tool, ToolDescription, ToolRequest, ToolResult
from tests.core.sample_settings import NotesSettings


class AddNoteRequest(ToolRequest):
    text: str


class AddNote(Tool[AddNoteRequest]):
    name = "add_note"
    risk = Risk.CHANGE
    description = ToolDescription(when="Просят записать мысль.", does="Сохраняет заметку.", returns="Ничего.", refusals="Нет.")
    request_type = AddNoteRequest

    def _run(self, request: AddNoteRequest) -> ToolResult:
        return ToolResult.success()


class NotesSkill(SkillConfig[NotesSettings]):
    name = "notes"
    description = "Заметки — записать мысль."
    settings_class = NotesSettings

    def ready(self, settings: NotesSettings, core: CoreServices) -> None:
        self.settings, self.core = settings, core

    def tools(self) -> Sequence[Tool[Any]]:
        return [AddNote()]
