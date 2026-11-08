"""Модуль ядра «память»: что пользователь сказал о себе, людях и делах — его словами, с тегами для поиска."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from jericho.core.journal.user_words import UserWords
from jericho.core.management.base import Command
from jericho.core.modules.config import ModuleConfig, ModuleServices
from jericho.core.prompting.protocols import PromptContext
from jericho.core.services.paths import Paths
from jericho.core.tools.tool import Tool
from jericho.modules.memory.adapters.json_file import JsonFileMemoryStore
from jericho.modules.memory.book import MemoryBook
from jericho.modules.memory.command import MemoryCommand
from jericho.modules.memory.context import MemoryTags
from jericho.modules.memory.guide import memory_section
from jericho.modules.memory.tools import ForgetMemory, Memorize, Recall

if TYPE_CHECKING:
    from jericho.core.agent.handle_phrase import HandlePhrase


class MemoryModule(ModuleConfig):
    """Заметки (`notes`) — проверенное действием «как называют → адрес/надпись»; память — слова пользователя.

    В промпте всегда только облако тегов; записи приходят по `recall` или с руководством навыка (тег = имя навыка).
    """

    name = "memory"
    FILE = "memory.json"

    def ready(self, services: ModuleServices) -> None:
        self._services = services
        self._file = services.core.paths.state_dir / self.FILE
        self._book = MemoryBook(JsonFileMemoryStore(self._file))

    def tools(self) -> Sequence[Tool[Any]]:
        core = self._services.core
        return (
            Memorize(self._book, UserWords(self._services.journal), core.confirmation, core.foreign),
            Recall(self._book),
            ForgetMemory(self._book),
        )

    def contexts(self) -> Sequence[PromptContext]:
        return (MemoryTags(self._book),)

    def guide_notes(self, skill: str) -> str:
        return memory_section(self._book, skill)

    def commands(self, handle_phrase: HandlePhrase) -> Sequence[Command]:
        return (MemoryCommand(self._book),)

    def status(self) -> Mapping[str, object]:
        """Для окна на панели: вкладка «Память» показывает и записи памяти — лишнее можно забыть."""
        return {"memories": [{"id": m.id, "text": m.text, "tags": list(m.tags), "used": m.used} for m in self._book.all()]}

    def eval_files(self, paths: Paths) -> Sequence[Path]:
        return (paths.state_dir / self.FILE,)
