import logging
from datetime import datetime

import pytest

from jericho.core.journal.entities import JournalEntry, PhraseRecord


class TestPhraseRecord:
    def test_what_is_written_is_read_back(self) -> None:
        """Пишет вход поручения, читают окно, журнал и проверки — через одну запись, а не по своим ключам."""
        record = PhraseRecord("что пишет Саша", "clarify", "Какой Саша?", options=("Петров", "Смирнов"), backend="claude_cli", ms=1200)
        details = record.details({"num_turns": 3, "total_cost_usd": 0.02, "backend": "claude_cli"})

        read = PhraseRecord.of(JournalEntry(datetime(2026, 10, 24, 9, 0), PhraseRecord.EVENT, details=details))

        assert read == PhraseRecord(
            "что пишет Саша", "clarify", "Какой Саша?", options=("Петров", "Смирнов"), backend="claude_cli", turns=3, ms=1200, cost_usd=0.02
        )

    def test_empty_fields_are_not_written(self) -> None:
        assert set(PhraseRecord("открой ютуб", "done", "Открыл").details()) == {"phrase", "status", "message", "ms"}

    def test_not_a_phrase_is_none(self) -> None:
        assert PhraseRecord.of(JournalEntry(datetime(2026, 10, 24), "tool", details={"tool": "open_url"})) is None

    def test_odd_values_do_not_break_reading(self) -> None:
        """Журнал пишут разные версии: чужой тип поля — пустое значение, а не падение окна."""
        entry = JournalEntry(datetime(2026, 10, 24), PhraseRecord.EVENT, details={"phrase": 5, "status": "done", "ms": "долго", "options": "А"})

        assert PhraseRecord.of(entry) == PhraseRecord("", "done")


class TestPhraseReceived:
    def test_phrase_is_journaled_before_the_model_answers(self, caplog: pytest.LogCaptureFixture) -> None:
        """Ручки этой же фразы (память предпочтений) должны видеть, что сказал пользователь, — до ответа модели."""
        from jericho.core.agent.handle_phrase import HandlePhrase
        from jericho.core.testing import FakeBackend, builder

        with caplog.at_level(logging.INFO, logger="jericho"):
            HandlePhrase(builder(), FakeBackend({"status": "done", "message": "Ок"})).execute("пиши ей тепло")

        events = [(record.getMessage(), getattr(record, "data", {}).get("phrase")) for record in caplog.records]
        assert events.index(("phrase_received", "пиши ей тепло")) < events.index(("phrase", "пиши ей тепло"))
