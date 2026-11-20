"""Перенос контекста безопасности в фразу продолжения — в процесс работы и в сервер ручек этой фразы."""

from __future__ import annotations

import logging
from datetime import datetime

from jericho.core.jobs.continuation import Carried, Chain
from jericho.core.journal.protocols import JournalReader
from jericho.core.services.foreign import ForeignText
from jericho.core.tools.session import CallSession

logger = logging.getLogger(__name__)


class CarriedContext:
    """Сеанс вызовов и учёт чужого текста живут в памяти процесса. У CLI-бэкенда ручки фразы работают в другом
    процессе — сервере ручек, который собирается заново. Поэтому перенос пишется событием `context_carried` в журнал
    своего запуска, а сервер ручек того же запуска при сборке читает его (`restore`): поведение API- и CLI-бэкендов
    одинаково (ревью 110, №1). Несколько переносов в одном запуске складываются — строже, а не мягче.
    """

    EVENT = "context_carried"
    _TAIL = 500

    def __init__(self, session: CallSession, foreign: ForeignText) -> None:
        self._session = session
        self._foreign = foreign
        self._chain: Chain | None = None

    @property
    def chain(self) -> Chain | None:
        """Цепочка, звеном которой идёт эта фраза; None — фраза пользователя, а не продолжение."""
        return self._chain

    def carry(self, carried: Carried) -> None:
        """Перед фразой продолжения: записать для сервера ручек и применить здесь."""
        logger.info(self.EVENT, extra={"data": self._details(carried)})
        self._apply(carried)

    def restore(self, journal: JournalReader, run_id: str) -> None:
        """При сборке процесса, унаследовавшего запуск: применить всё, что перенесли в этот запуск."""
        for entry in journal.tail(self._TAIL):
            if entry.run == run_id and entry.event == self.EVENT:
                self._apply(self._parsed(entry.details))

    def _apply(self, carried: Carried) -> None:
        if carried.private_read:
            self._session.read_private()
        if carried.local_read:
            self._session.read_local()
        for source in carried.foreign:
            self._foreign.restore(source)
        if carried.chain is not None:
            self._chain = carried.chain

    @staticmethod
    def _details(carried: Carried) -> dict[str, object]:
        chain = carried.chain
        own: dict[str, object] = {"private_read": carried.private_read, "local_read": carried.local_read, "foreign": list(carried.foreign)}
        if chain is None:
            return own
        return {**own, "chain": {"root": chain.root, "depth": chain.depth, "deadline": chain.deadline.isoformat()}}

    @staticmethod
    def _parsed(details: object) -> Carried:
        data = details if isinstance(details, dict) else {}
        foreign = data.get("foreign")
        chain = data.get("chain")
        parsed = None
        if isinstance(chain, dict) and isinstance(chain.get("root"), str) and isinstance(chain.get("depth"), int):
            parsed = Chain(chain["root"], chain["depth"], datetime.fromisoformat(str(chain.get("deadline"))))
        return Carried(
            data.get("private_read") is True, data.get("local_read") is True,
            tuple(str(source) for source in foreign) if isinstance(foreign, list) else (), parsed,
        )
