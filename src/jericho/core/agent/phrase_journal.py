"""Запись фразы в журнал — и что из ответа туда можно положить."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace

from jericho.core.agent.entities import AgentReply, ReplyStatus
from jericho.core.journal.entities import PhraseRecord
from jericho.core.journal.reply_vault import ReplyVault

logger = logging.getLogger(__name__)


class PhraseJournal:
    """Пишет запись «фраза» (`PhraseRecord`) и решает, что из ответа в неё попадёт.

    Ответ о личной переписке человеку показывается целиком (помечен `private`), в журнал идут только memo личных
    ручек этой фразы («прочитал чат …»), а сам ответ — в папку сеанса (решение владельца 23.10.2026: пересказ
    переписки не оседает на диске).
    """

    def __init__(self, private: Callable[[], Sequence[str]] = tuple, vault: ReplyVault | None = None, run_id: str = "") -> None:
        self._private = private      # memo личных ручек этой фразы (PrivateRun): есть — ответ личный
        self._vault = vault
        self._run_id = run_id

    def record(self, phrase: str, reply: AgentReply, extra: Mapping[str, object], ms: int) -> AgentReply:
        """Записать фразу и вернуть ответ, каким его увидит человек."""
        shown, journaled = self._privacy(reply)
        backend = extra.get("backend")
        record = PhraseRecord(
            phrase=phrase, status=journaled.status.value, message=journaled.message, body=journaled.body,
            private=journaled.private, options=journaled.options, backend=backend if isinstance(backend, str) else None,
            without_model=extra.get("without_model") is True, ms=ms,
        )
        level = logging.ERROR if reply.status is ReplyStatus.FAILED else logging.INFO
        logger.log(level, PhraseRecord.EVENT, extra={"data": record.details(extra)})
        return shown

    @staticmethod
    def received(phrase: str, attended: bool) -> None:
        """Фраза пришла: запись до ответа модели — ручки этой же фразы видят, что сказал пользователь."""
        logger.info(PhraseRecord.RECEIVED, extra={"data": {"phrase": phrase, **({} if attended else {"unattended": True})}})

    @staticmethod
    def skipped(phrase: str, reason: str) -> None:
        """Фраза не взята (другая ещё идёт): запись, что её не было."""
        logger.warning(PhraseRecord.EVENT, extra={"data": {**PhraseRecord(phrase, ReplyStatus.FAILED.value).details(), "skipped": reason}})

    def _privacy(self, reply: AgentReply) -> tuple[AgentReply, AgentReply]:
        memos = self._private()
        if not memos:
            return reply, reply
        if self._vault is not None:
            self._vault.keep(self._run_id, reply)
        return replace(reply, private=True), replace(reply, message="; ".join(memos), body="", private=True)
