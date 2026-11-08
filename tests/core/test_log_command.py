import argparse
from datetime import UTC, datetime

import pytest

from jericho.core.interfaces.cli.journal_commands import LogCommand
from jericho.core.journal.entities import JournalEntry

NOON = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)


class Journal:
    def __init__(self, *entries: JournalEntry) -> None:
        self._entries = list(entries)

    def tail(self, limit: int) -> list[JournalEntry]:
        return self._entries[-limit:]


class TestLogCommand:
    def test_whose_phrase_it_was_is_shown(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Ассистент нескольких пользователей: по журналу видно, кто что просил."""
        journal = Journal(
            JournalEntry(NOON, "phrase", details={"phrase": "что с сервером?"}, user="123456789"),
            JournalEntry(NOON, "phrase", details={"phrase": "привет"}),
        )

        LogCommand(journal).run(argparse.Namespace(limit=5))

        owner, single = capsys.readouterr().out.splitlines()
        assert 'user=123456789  phrase="что с сервером?"' in owner
        assert "user=" not in single
