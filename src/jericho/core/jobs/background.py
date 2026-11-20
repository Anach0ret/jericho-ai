"""Фоновые работы ассистента одним узлом: модуль получает его в `ModuleServices.jobs` и не собирает части сам."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from jericho.core.jobs.adapters.json_file import JsonContinuationStore
from jericho.core.jobs.book import ContinuationBook
from jericho.core.jobs.carried import CarriedContext
from jericho.core.jobs.continuation import Continuation
from jericho.core.jobs.desk import ContinuationDesk
from jericho.core.jobs.history import JobHistory
from jericho.core.jobs.journal import JobJournal
from jericho.core.jobs.launch import JobLauncher
from jericho.core.jobs.run import ContinuationRun
from jericho.core.jobs.settings import JobsSettings
from jericho.core.journal.protocols import JournalReader
from jericho.core.services.adapters.file_lock import FileLock
from jericho.core.services.adapters.memory_list import MemoryList
from jericho.core.services.core_services import CoreServices
from jericho.core.services.lock import ExclusiveLock, Unlocked
from jericho.core.services.locked_list import ListStore, LockedList
from jericho.core.services.output import Output
from jericho.core.services.program import Program
from jericho.core.tools.session import CallSession

if TYPE_CHECKING:
    from jericho.core.agent.handle_phrase import HandlePhrase


class BackgroundJobs:
    """Запуск работы из ручки (`launcher`, с `then`), журнал работы с продолжением (`journal`), история (`history`),
    отложенные продолжения (`book`). Контекст безопасности переносится в этот процесс при сборке (`restore`)."""

    FILE = "continuations.json"
    LOCK = "continuations.lock"
    LOCK_WAIT = 5.0

    def __init__(
        self, settings: JobsSettings, core: CoreServices, session: CallSession, journal: JournalReader, program: Program,
        carried: CarriedContext | None = None,
    ) -> None:
        self.settings = settings
        self._core = core
        self.carried = carried or CarriedContext(session, core.foreign)     # сборка даёт общий с ручкой confirm
        store: ListStore[Continuation] = MemoryList[Continuation]() if core.dry_run else JsonContinuationStore(core.paths.state_dir / self.FILE)
        lock: ExclusiveLock = Unlocked() if core.dry_run else FileLock(core.paths.state_dir / self.LOCK, self.LOCK_WAIT)
        self.book = ContinuationBook(LockedList(store, lock), core.clock.now, timedelta(hours=settings.continuation_keep_hours))
        self.history = JobHistory(journal)
        desk = ContinuationDesk(
            self.book, self.carried, session, core.foreign, core.confirmation, core.user, core.clock.now,
            timedelta(hours=settings.continuation_auto_hours), settings.chain_depth, settings.chain_links,
        )
        self.launcher = JobLauncher(core.runner, program, desk)

    def journal(self, output: Output, handle_phrase: HandlePhrase) -> JobJournal:
        """Журнал работы, после которой может идти продолжение — фразой через `handle_phrase`, итог — в `output`."""
        return JobJournal(output, self.continuations(output, handle_phrase))

    def continuations(self, output: Output, handle_phrase: HandlePhrase) -> ContinuationRun:
        core, settings = self._core, self.settings
        return ContinuationRun(
            self.book, self.carried, handle_phrase, output, core.user, core.confirmation.attended, core.clock.now,
            settings.busy_retries, settings.busy_wait_seconds, settings.chain_depth, settings.chain_links,
        )
