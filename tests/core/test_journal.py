import logging
from collections.abc import Iterator
from pathlib import Path

import pytest

from jericho.core.journal.adapters.jsonl import JournalRotation, JsonLinesLogReader, LoggingConfigurator

LOGGER_NAME = "jericho_test_journal"


@pytest.fixture
def journal_file(tmp_path: Path) -> Iterator[Path]:
    yield tmp_path / "state" / "journal.jsonl"
    logger = logging.getLogger(LOGGER_NAME)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()


class TestJournalFile:
    def test_events_are_read_back_in_order(self, journal_file: Path) -> None:
        LoggingConfigurator(journal_file, "run-1", LOGGER_NAME).configure()
        logger = logging.getLogger(f"{LOGGER_NAME}.resolver")

        logger.info("resolve", extra={"data": {"query": "портфолио", "status": "found"}})
        logger.warning("slow")

        first, second = JsonLinesLogReader(journal_file).tail(10)
        assert (first.event, first.level, first.source) == ("resolve", "INFO", f"{LOGGER_NAME}.resolver")
        assert first.details == {"query": "портфолио", "status": "found"}
        assert first.time.tzinfo is not None
        assert (second.event, second.level) == ("slow", "WARNING")

    def test_every_record_carries_the_run_and_it_stays_out_of_the_details(self, journal_file: Path) -> None:
        LoggingConfigurator(journal_file, "run-7", LOGGER_NAME).configure()

        logging.getLogger(LOGGER_NAME).info("tool", extra={"data": {"tool": "open_app"}})

        (entry,) = JsonLinesLogReader(journal_file).tail(10)
        assert (entry.run, entry.details) == ("run-7", {"tool": "open_app"})

    def test_exception_is_written_with_traceback(self, journal_file: Path) -> None:
        LoggingConfigurator(journal_file, "run-1", LOGGER_NAME).configure()
        try:
            raise ValueError("boom")
        except ValueError:
            logging.getLogger(LOGGER_NAME).exception("error", extra={"data": {"command": "resolve"}})

        (entry,) = JsonLinesLogReader(journal_file).tail(10)
        assert entry.level == "ERROR"
        assert entry.details["command"] == "resolve"
        assert "ValueError: boom" in str(entry.details["traceback"])

    def test_tail_returns_only_the_latest(self, journal_file: Path) -> None:
        LoggingConfigurator(journal_file, "run-1", LOGGER_NAME).configure()
        for number in range(5):
            logging.getLogger(LOGGER_NAME).info("resolve", extra={"data": {"number": number}})

        assert [entry.details["number"] for entry in JsonLinesLogReader(journal_file).tail(2)] == [3, 4]

    def test_configuring_twice_does_not_duplicate_records(self, journal_file: Path) -> None:
        LoggingConfigurator(journal_file, "run-1", LOGGER_NAME).configure()
        LoggingConfigurator(journal_file, "run-1", LOGGER_NAME).configure()

        logging.getLogger(LOGGER_NAME).info("resolve")

        assert len(JsonLinesLogReader(journal_file).tail(10)) == 1

    def test_full_file_is_replaced_and_the_writer_follows(self, journal_file: Path) -> None:
        """Файл сменяет не пишущий, а тот, кто начал запуск; пишущий замечает смену и пишет уже в новый."""
        LoggingConfigurator(journal_file, "run-1", LOGGER_NAME).configure()
        logger = logging.getLogger(LOGGER_NAME)
        logger.info("resolve", extra={"data": {"query": "x" * 250}})

        JournalRotation(journal_file, max_bytes=300).rotate_if_full()
        logger.info("resolve", extra={"data": {"query": "после смены"}})

        assert [entry.details["query"] for entry in JsonLinesLogReader(journal_file).tail(10)] == ["после смены"]
        assert "x" * 250 in journal_file.with_name("journal.jsonl.1").read_text(encoding="utf-8")

    def test_file_that_is_not_full_stays(self, journal_file: Path) -> None:
        LoggingConfigurator(journal_file, "run-1", LOGGER_NAME).configure()
        logging.getLogger(LOGGER_NAME).info("resolve")

        JournalRotation(journal_file).rotate_if_full()
        JournalRotation(journal_file.with_name("absent.jsonl")).rotate_if_full()

        assert not journal_file.with_name("journal.jsonl.1").exists()
        assert len(JsonLinesLogReader(journal_file).tail(10)) == 1

    def test_only_the_latest_replaced_files_are_kept(self, journal_file: Path) -> None:
        LoggingConfigurator(journal_file, "run-1", LOGGER_NAME).configure()
        for _ in range(4):
            logging.getLogger(LOGGER_NAME).info("resolve")
            JournalRotation(journal_file, max_bytes=1, backups=2).rotate_if_full()

        assert sorted(path.name for path in journal_file.parent.iterdir()) == ["journal.jsonl.1", "journal.jsonl.2"]


class TestJsonLinesLogReader:
    def test_missing_file_is_an_empty_journal(self, tmp_path: Path) -> None:
        assert JsonLinesLogReader(tmp_path / "journal.jsonl").tail(10) == []

    def test_broken_line_is_skipped(self, tmp_path: Path) -> None:
        file = tmp_path / "journal.jsonl"
        file.write_text(
            '{"time": "2026-10-09T22:00:00+02:00", "event": "resolve", "query": "a"}\n{оборванная строка\n',
            encoding="utf-8",
        )

        assert [entry.details["query"] for entry in JsonLinesLogReader(file).tail(10)] == ["a"]
