"""Модуль ядра «памятки»: как делается повторяющееся дело — по шагам, чтобы не выяснять это каждый раз заново.

Заметка — пара «как называют → что это»; памятка — порядок действий: «тест в Moodle: „Пройти тест“ → ответы →
„Закончить попытку…“ → окно „Вы уверены?“». Пишет её пользователь словами (`playbook_write`); модель читает
нужную по списку в промпте (`{{playbooks}}`, `playbook_show`) и предлагает дополнения (`playbook_suggest`) —
в памятку они попадают после «Принять» в окне (команда `playbooks --accept`). Так ассистент учится на деле,
а чужой текст со страниц не становится долгой подсказкой без человека.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from jericho.core.management.base import Command
from jericho.core.modules.config import ModuleConfig, ModuleServices
from jericho.core.prompting.protocols import PromptContext
from jericho.core.services.adapters.file_lock import FileLock
from jericho.core.services.adapters.memory_list import MemoryList
from jericho.core.services.lock import Unlocked
from jericho.core.services.paths import Paths
from jericho.core.tools.dispatcher import ToolMiddleware
from jericho.core.tools.tool import Tool
from jericho.modules.playbooks.adapters.json_file import JsonPlaybookStore
from jericho.modules.playbooks.command import PlaybooksCommand
from jericho.modules.playbooks.context import PlaybookList
from jericho.modules.playbooks.entities import Playbook
from jericho.modules.playbooks.hint import PlaybookHint
from jericho.modules.playbooks.protocols import PlaybookStore
from jericho.modules.playbooks.shelf import PlaybookShelf
from jericho.modules.playbooks.tools import RemovePlaybook, ShowPlaybook, SuggestPlaybook, WritePlaybook, described

if TYPE_CHECKING:
    from jericho.core.agent.handle_phrase import HandlePhrase


class PlaybooksModule(ModuleConfig):
    name = "playbooks"
    FILE = "playbooks.json"
    LOCK = "playbooks.lock"          # изменения полки — по одному: окно на панели и фраза
    LOCK_WAIT = 5.0                  # секунд: запись списка — доли секунды

    def ready(self, services: ModuleServices) -> None:
        self._services = services
        core = services.core
        store: PlaybookStore = MemoryList[Playbook]() if core.dry_run else JsonPlaybookStore(core.paths.state_dir / self.FILE)
        lock = Unlocked() if core.dry_run else FileLock(core.paths.state_dir / self.LOCK, self.LOCK_WAIT)
        self._shelf = PlaybookShelf(store, core.clock.now, lock=lock)

    def tools(self) -> Sequence[Tool[Any]]:
        shelf, core = self._shelf, self._services.core
        return ShowPlaybook(shelf), WritePlaybook(shelf, core.confirmation, core.foreign), SuggestPlaybook(shelf), RemovePlaybook(shelf)

    def tool_layers(self) -> Sequence[ToolMiddleware]:
        return (PlaybookHint(self._shelf),)

    def contexts(self) -> Sequence[PromptContext]:
        return (PlaybookList(self._shelf),)

    def commands(self, handle_phrase: HandlePhrase) -> Sequence[Command]:
        return (PlaybooksCommand(self._shelf),)

    def status(self) -> Mapping[str, object]:
        """Для окна: памятки с текстом и предложения модели — принять, отклонить, убрать — командой `playbooks`."""
        playbooks = self._shelf.all()
        return {"playbooks": [described(playbook) for playbook in playbooks]} if playbooks else {}

    def eval_files(self, paths: Paths) -> Sequence[Path]:
        return (paths.state_dir / self.FILE,)
