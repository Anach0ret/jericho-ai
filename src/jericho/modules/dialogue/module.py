"""Модуль ядра «диалог»: следующая фраза может быть ответом на вопрос ассистента."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta
from pathlib import Path
from typing import Any

from jericho.core.agent.task import TaskLayer
from jericho.core.journal.private_run import PrivateRun
from jericho.core.journal.reply_vault import ReplyVault
from jericho.core.modules.config import ModuleConfig, ModuleServices
from jericho.core.prompting.protocols import PromptContext
from jericho.core.services.adapters.json_file import JsonStateFile
from jericho.core.services.paths import Paths
from jericho.core.tools.tool import Tool
from jericho.modules.dialogue.adapters.conversation_file import JsonFileConversationMemory
from jericho.modules.dialogue.context import RecentExchanges
from jericho.modules.dialogue.foreign import ForeignReadInRun
from jericho.modules.dialogue.settings import DialogueSettings
from jericho.modules.dialogue.task_layer import Conversation
from jericho.modules.dialogue.tools import LastReply


class DialogueModule(ModuleConfig):
    name = "dialogue"

    FILE = "conversation.json"      # в папке сеанса: после выхода из системы разговор не сохраняется

    def ready(self, services: ModuleServices) -> None:
        settings = services.settings.section(self.name, DialogueSettings)
        self._file = services.core.paths.runtime_dir / self.FILE
        self._memory = JsonFileConversationMemory(self._file, timedelta(minutes=settings.minutes))
        self._foreign_read = ForeignReadInRun(services.journal, services.run_id, services.core.foreign)
        self._private = PrivateRun(services.journal, services.run_id)
        self._vault = ReplyVault(JsonStateFile(services.core.paths.runtime_dir / ReplyVault.FILE))
        # Модель снова увидит прошлые ответы — а в них мог быть чужой текст: учёт начинается с него (ревью R06).
        for exchange in self._memory.recent():
            for source in exchange.foreign:
                services.core.foreign.restore(source)

    def tools(self) -> Sequence[Tool[Any]]:
        return (LastReply(self._vault),)

    def task_layer(self) -> TaskLayer:
        return Conversation(self._memory, self._foreign_read, self._private)

    def contexts(self) -> Sequence[PromptContext]:
        return (RecentExchanges(self._memory),)

    def eval_files(self, paths: Paths) -> Sequence[Path]:
        return (paths.runtime_dir / self.FILE,)
