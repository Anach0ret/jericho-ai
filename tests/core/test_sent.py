"""Журнал отправленного: что ушло через ящик, дошло ли и что из этого можно модели (задача 102 серверного ассистента)."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest

from jericho.core.agent.entities import AgentReply, ReplyStatus
from jericho.core.conf.settings import OutputSettings
from jericho.core.journal.entities import JournalEntry
from jericho.core.journal.run_trail import RunTrail, Trail
from jericho.core.services.mailbox import Mailbox
from jericho.core.services.output import MailboxOutput, output_for
from jericho.core.services.sent import SentLog, SentNotice

MORNING = datetime(2026, 11, 8, 8, 0, tzinfo=UTC)


class Clock:
    def __init__(self, now: datetime = MORNING) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def notice(id_: str, at: datetime = MORNING, title: str = "Сводка", **extra: object) -> SentNotice:
    return SentNotice.of(id_, "owner", at, "утренняя сводка", AgentReply(ReplyStatus.DONE, title, "одна WARNING", **extra), {}, ())  # pyright: ignore[reportArgumentType]


class TestSentLog:
    def test_newest_first_and_survives_a_new_reader(self, tmp_path: Path) -> None:
        """Новый процесс (перезапуск) читает то же: журнал в папке состояния, а не в памяти процесса."""
        clock = Clock()
        SentLog.at(tmp_path, clock).record(notice("a"))
        SentLog.at(tmp_path, clock).record(notice("b", MORNING + timedelta(hours=1)))

        assert [found.id for found in SentLog.at(tmp_path, clock).recent("owner")] == ["b", "a"]

    def test_older_than_a_day_is_forgotten(self, tmp_path: Path) -> None:
        clock = Clock()
        SentLog.at(tmp_path, clock).record(notice("a"))
        clock.now = MORNING + SentLog.KEEP + timedelta(minutes=1)

        assert SentLog.at(tmp_path, clock).recent("owner") == ()

    def test_private_reply_is_kept_without_its_text(self, tmp_path: Path) -> None:
        """Записи «как есть» уходят человеку мимо модели — модели их не вернуть через память уведомлений."""
        SentLog.at(tmp_path, Clock()).record(notice("a", title="10 записей — как есть", private=True))

        [kept] = SentLog.at(tmp_path, Clock()).recent("owner")
        assert kept.title == "10 записей — как есть" and kept.text == ""

    def test_receipt_marks_delivery_and_finds_the_notice_by_transport_message(self, tmp_path: Path) -> None:
        log = SentLog.at(tmp_path, Clock())
        log.record(notice("a"))

        assert log.confirm("a", True, ["501", "502"]) and not log.confirm("ghost", True)
        found = log.by_message("owner", "502")
        assert found is not None and found.id == "a" and found.delivered is True and log.by_message("owner", "999") is None

    def test_undelivered_is_not_shown_as_seen(self, tmp_path: Path) -> None:
        log = SentLog.at(tmp_path, Clock())
        log.record(notice("a"))
        log.confirm("a", False)

        assert log.recent("owner") == ()

    def test_each_recipient_has_its_own_file(self, tmp_path: Path) -> None:
        log = SentLog.at(tmp_path, Clock())
        log.record(notice("a"))

        assert log.recent("someone_else") == ()


class TestMailboxOutputRecords:
    def test_what_went_out_is_recorded_with_the_trail_of_its_run(self, tmp_path: Path) -> None:
        box, log = Mailbox(tmp_path / "outbox"), SentLog.at(tmp_path / "state", Clock(datetime.now(UTC)))
        trail = Trail({"logs": [{"since": "2026-11-07T08:00:00+00:00"}]}, ("example.com",))

        output = output_for(OutputSettings(kind="mailbox", mailbox=box.root), "server", log, lambda: trail)
        output.deliver("утренняя сводка", AgentReply(ReplyStatus.DONE, "Одна WARNING", "бот /api/.env"))

        [message] = [Mailbox.read(path) for path in box.waiting()]
        [kept] = log.recent("owner")
        assert kept.id == message["notice"] and kept.text == "бот /api/.env"
        assert kept.facts == {"logs": [{"since": "2026-11-07T08:00:00+00:00"}]} and kept.foreign == ("example.com",)

    def test_private_tools_of_the_run_leave_a_memo_not_the_title_or_text(self, tmp_path: Path) -> None:
        """Ревью 11.11.2026: пересказ переписки бывает и в заголовке — хранится только пометка."""
        box, log = Mailbox(tmp_path / "outbox"), SentLog.at(tmp_path / "state", Clock(datetime.now(UTC)))

        output_for(OutputSettings(kind="mailbox", mailbox=box.root), "x", log, lambda: Trail(memos=("прочитал чат: 3 сообщения",))).deliver(
            "сводка чатов", AgentReply(ReplyStatus.DONE, "Марина просит перевести деньги", "Марина пишет: …")
        )

        [kept] = log.recent("owner")
        assert (kept.title, kept.text) == ("прочитал чат: 3 сообщения", "")

    def test_recorded_before_the_mailbox_so_an_early_receipt_finds_it(self, tmp_path: Path) -> None:
        """Ревью 11.11.2026: транспорт может прислать квитанцию раньше, чем запись в журнал отправленного."""
        log = SentLog.at(tmp_path / "state", Clock(datetime.now(UTC)))

        class Box:
            def post(self, message: dict[str, object]) -> None:
                assert log.confirm(str(message["notice"]), True, ["501"])      # квитанция «в ту же секунду»

        MailboxOutput(cast(Mailbox, Box()), "owner", log).deliver("сводка", AgentReply(ReplyStatus.DONE, "ok"))

        assert log.by_message("owner", "501") is not None

    def test_not_posted_is_not_shown_as_seen(self, tmp_path: Path) -> None:
        log = SentLog.at(tmp_path / "state", Clock(datetime.now(UTC)))

        class Broken:
            def post(self, message: dict[str, object]) -> None:
                raise OSError("disk full")

        with pytest.raises(OSError):
            MailboxOutput(cast(Mailbox, Broken()), "owner", log).deliver("сводка", AgentReply(ReplyStatus.DONE, "ok"))

        assert log.recent("owner") == ()

    def test_without_a_sent_log_nothing_is_recorded(self, tmp_path: Path) -> None:
        box = Mailbox(tmp_path / "outbox")

        output_for(OutputSettings(kind="mailbox", mailbox=box.root), "x").deliver("t", AgentReply(ReplyStatus.DONE, "ok"))

        assert not (tmp_path / "state").exists()


class Journal:
    def __init__(self, entries: list[JournalEntry]) -> None:
        self._entries = entries

    def tail(self, limit: int) -> list[JournalEntry]:
        return self._entries[-limit:]


class TestRunTrail:
    def test_facts_and_foreign_of_its_own_run_only(self) -> None:
        at = datetime(2026, 11, 8, 8, 0)
        journal = Journal([
            JournalEntry(at, "fact", details={"fact": "logs", "value": {"hours": 24}}, run="r1"),
            JournalEntry(at, "foreign", details={"source": "example.com"}, run="r1"),
            JournalEntry(at, "fact", details={"fact": "logs", "value": {"hours": 1}}, run="other"),
        ])

        assert RunTrail(journal, "r1")() == Trail({"logs": [{"hours": 24}]}, ("example.com",), ())

    def test_every_selection_of_one_name_is_kept(self) -> None:
        """Ревью 11.11.2026: сводка по двум проектам — две выборки `logs`; вторая не вытесняет первую."""
        at = datetime(2026, 11, 8, 8, 0)
        journal = Journal([
            JournalEntry(at, "fact", details={"fact": "logs", "value": {"project": "a"}}, run="r1"),
            JournalEntry(at, "fact", details={"fact": "logs", "value": {"project": "b"}}, run="r1"),
        ])

        assert RunTrail(journal, "r1")().facts == {"logs": [{"project": "a"}, {"project": "b"}]}

    def test_next_notice_of_the_same_process_does_not_inherit_the_trail(self) -> None:
        """Ревью 11.11.2026: `due` выполняет поручения подряд с одним номером запуска — напоминание после проверки
        проекта A не получает её факты; новое событие с той же меткой времени не теряется (граница — место в журнале)."""
        at = datetime(2026, 11, 8, 8, 0)
        entries = [JournalEntry(at, "fact", details={"fact": "logs", "value": {"project": "a"}}, run="r1")]
        trail = RunTrail(Journal(entries), "r1", mark=lambda: entries.append(JournalEntry(at, RunTrail.BOUNDARY, run="r1")))

        first = trail()
        entries.append(JournalEntry(at, "fact", details={"fact": "logs", "value": {"project": "b"}}, run="r1"))

        assert first.facts == {"logs": [{"project": "a"}]} and trail().facts == {"logs": [{"project": "b"}]}
        assert trail() == Trail()
