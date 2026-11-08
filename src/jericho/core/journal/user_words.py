"""Сказал ли это пользователь сам: доказательство для того, что Jericho запоминает с его слов."""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime, timedelta

from jericho.core.journal.entities import PhraseRecord
from jericho.core.journal.protocols import JournalReader
from jericho.core.services.clock import local_now


class UserWords:
    """Эти слова есть в фразе пользователя за последние минуты, когда он был рядом.

    Только его фразы (запись `phrase_received` пишется до ответа модели — видна и текущая фраза): прочитанная
    переписка и страницы приходят ответами ручек, поэтому «запомни: пиши ей грубо» из чужого сообщения его
    словами не станет. Фразы по расписанию не в счёт. Сравнение — без регистра и знаков препинания.
    """

    def __init__(self, journal: JournalReader, now: Callable[[], datetime] = local_now,
                 window: timedelta = timedelta(minutes=15), scan: int = 2000) -> None:
        self._journal = journal
        self._now = now
        self._window = window
        self._scan = scan

    def said(self, text: str) -> bool:
        wanted = plain(text)
        if not wanted:
            return False
        since = (self._now() - self._window).timestamp()
        for entry in reversed(self._journal.tail(self._scan)):
            if entry.time.timestamp() < since:
                return False
            phrase = entry.details.get("phrase")
            if entry.event not in (PhraseRecord.RECEIVED, PhraseRecord.EVENT) or entry.details.get("unattended"):
                continue
            if isinstance(phrase, str) and wanted in plain(phrase):
                return True
        return False


def plain(text: str) -> str:
    """Без регистра, знаков препинания и лишних пробелов; «ё» — как «е»."""
    return " ".join(re.sub(r"[^\w\s]", " ", text.casefold().replace("ё", "е")).split())
