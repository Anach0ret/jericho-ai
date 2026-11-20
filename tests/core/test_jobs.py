"""Фоновые работы: запуск и итог — в журнал, итог — уведомлением; история — по журналу (план 110, этап 1)."""

import argparse
import logging
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from jericho.core.agent.entities import AgentReply, ReplyStatus
from jericho.core.jobs.arguments import add_job_argument, job_id
from jericho.core.jobs.entities import JobOutcome, JobRecord, JobStatus, JobTicket
from jericho.core.jobs.history import JobHistory, process_alive
from jericho.core.jobs.journal import JobJournal
from jericho.core.jobs.launch import JobLauncher
from jericho.core.journal.entities import JournalEntry
from jericho.core.services.program import Program
from jericho.core.services.runner import CommandError
from jericho.core.tools.result import ToolRefusal

NOON = datetime(2026, 11, 16, 12, 0).astimezone()
VIDEO = JobTicket("j1", "videos", "видео https://youtu.be/x", {"url": "https://youtu.be/x", "height": 1080, "audio_only": False})


class Delivered:
    def __init__(self) -> None:
        self.sent: list[tuple[str, AgentReply]] = []

    def deliver(self, task: str, reply: AgentReply) -> None:
        self.sent.append((task, reply))


class Entries:
    """Журнал из записей, которые написал `JobJournal`: как их прочтёт `JsonLinesLogReader`."""

    def __init__(self, caplog: pytest.LogCaptureFixture | None = None, entries: list[JournalEntry] | None = None) -> None:
        self._caplog = caplog
        self._entries = entries or []

    def tail(self, limit: int) -> list[JournalEntry]:
        written = [
            JournalEntry(NOON, record.getMessage(), record.levelname, record.name, getattr(record, "data", {}))
            for record in (self._caplog.records if self._caplog else [])
        ]
        return (self._entries + written)[-limit:]


def entry(record: JobRecord, minutes: int = 0) -> JournalEntry:
    return JournalEntry(NOON + timedelta(minutes=minutes), record.event, details=record.details())


class TestJournal:
    def test_start_and_outcome_are_written_with_one_id_and_the_outcome_is_delivered(self, caplog: pytest.LogCaptureFixture) -> None:
        caplog.set_level(logging.INFO, "jericho")
        delivered = Delivered()

        outcome = JobJournal(delivered, pid=lambda: 42).run(VIDEO, lambda: JobOutcome.succeeded("Скачано: «Ролик»", "/home/me/Ролик.mp4"))

        started, finished = (JobRecord.of(item) for item in Entries(caplog).tail(10))
        assert started is not None and finished is not None
        assert (started.event, started.ticket, started.pid) == (JobRecord.STARTED, VIDEO, 42)
        assert (finished.event, finished.ticket.job, finished.outcome) == (JobRecord.FINISHED, "j1", outcome)
        assert delivered.sent == [(VIDEO.title, AgentReply(ReplyStatus.DONE, "Скачано: «Ролик»", "/home/me/Ролик.mp4"))]

    @pytest.mark.parametrize(("status", "reply"), [
        (JobStatus.FAILED, ReplyStatus.FAILED), (JobStatus.WAITING_USER, ReplyStatus.CLARIFY), (JobStatus.STOPPED, ReplyStatus.STOPPED),
    ])
    def test_a_finished_process_is_not_a_success(self, status: JobStatus, reply: ReplyStatus) -> None:
        """Ревью плана 110, №7: прогон плана слал «готово» и тогда, когда его остановили."""
        delivered = Delivered()

        JobJournal(delivered).run(VIDEO, lambda: JobOutcome(status, "итог"))

        assert delivered.sent[0][1].status is reply

    def test_a_crash_midway_is_an_unknown_outcome_and_still_raises(self, caplog: pytest.LogCaptureFixture) -> None:
        caplog.set_level(logging.INFO, "jericho")
        delivered = Delivered()

        def broken() -> JobOutcome:
            raise RuntimeError("диск отвалился")

        with pytest.raises(RuntimeError):
            JobJournal(delivered).run(VIDEO, broken)

        finished = JobRecord.of(Entries(caplog).tail(10)[-1])
        assert finished is not None and finished.outcome is not None
        assert finished.outcome.status is JobStatus.OUTCOME_UNKNOWN and caplog.records[-1].levelname == "WARNING"
        assert delivered.sent[0][1].status is ReplyStatus.FAILED


class TestRecord:
    def test_record_survives_the_journal(self) -> None:
        record = JobRecord(JobRecord.FINISHED, VIDEO, outcome=JobOutcome.succeeded("ok", "/f.mp4"))

        assert JobRecord.of(entry(record)) == record

    @pytest.mark.parametrize("details", [{"job": "j1"}, {"job": "j1", "kind": "videos", "params": {}, "status": "почти"}])
    def test_broken_record_is_skipped(self, details: dict[str, object]) -> None:
        assert JobRecord.of(JournalEntry(NOON, JobRecord.FINISHED, details=details)) is None

    def test_other_events_are_not_jobs(self) -> None:
        assert JobRecord.of(JournalEntry(NOON, "tool", details={"tool": "x"})) is None


class TestHistory:
    def test_running_finished_and_vanished_jobs(self) -> None:
        other = JobTicket("j2", "sendfile", "файл", {"chat": 5, "path": "/f"})
        gone = JobTicket("j3", "recordings", "запись", {"url": "u"})
        entries = [
            entry(JobRecord(JobRecord.STARTED, VIDEO, pid=10)),
            entry(JobRecord(JobRecord.STARTED, other, pid=11), 1),
            entry(JobRecord(JobRecord.STARTED, gone, pid=12), 2),
            entry(JobRecord(JobRecord.FINISHED, VIDEO, outcome=JobOutcome.succeeded("ok")), 3),
        ]

        states = JobHistory(Entries(entries=entries), alive=lambda pid: pid == 11).since(NOON - timedelta(hours=1))

        assert [(state.ticket.job, state.status) for state in states] == [
            ("j1", JobStatus.SUCCEEDED), ("j2", None), ("j3", JobStatus.OUTCOME_UNKNOWN),
        ]

    def test_jobs_started_before_the_window_are_not_shown(self) -> None:
        entries = [entry(JobRecord(JobRecord.STARTED, VIDEO, pid=10), -120)]

        assert JobHistory(Entries(entries=entries), alive=lambda pid: True).since(NOON - timedelta(hours=1)) == []

    def test_same_deed_is_found_only_with_the_same_parameters(self) -> None:
        """Журнал 11.11.2026: ролик скачан второй раз. Тот же адрес в 720 — уже другое дело."""
        done = JobOutcome.succeeded("ok", "/Ролик.mp4")
        entries = [entry(JobRecord(JobRecord.FINISHED, VIDEO, outcome=done))]
        history = JobHistory(Entries(entries=entries))

        assert history.succeeded("videos", dict(VIDEO.params)) == done
        assert history.succeeded("videos", {**VIDEO.params, "height": 720}) is None
        assert history.succeeded("recordings", dict(VIDEO.params)) is None

    def test_failed_attempt_does_not_count(self) -> None:
        entries = [entry(JobRecord(JobRecord.FINISHED, VIDEO, outcome=JobOutcome.failed("нет сети")))]

        assert JobHistory(Entries(entries=entries)).succeeded("videos", dict(VIDEO.params)) is None


class Launched:
    def __init__(self, error: CommandError | None = None) -> None:
        self.commands: list[list[str]] = []
        self._error = error

    def launch(self, command: list[str] | tuple[str, ...]) -> None:
        if self._error:
            raise self._error
        self.commands.append(list(command))


PROGRAM = Program("home", ("/venv/python", "-m", "jericho"), {}, Path("/c"), Path("/c"))


class TestProcessAlive:
    """Только вопрос системе: `os.kill(pid, 0)` на Windows послал бы Ctrl+C (ревью 111, №2)."""

    def test_own_process_is_alive(self) -> None:
        assert process_alive(os.getpid())

    def test_finished_process_is_not(self) -> None:
        child = subprocess.Popen([sys.executable, "-c", "pass"])
        child.wait()

        assert not process_alive(child.pid)


class TestLaunch:
    def test_work_is_launched_as_its_own_run_with_an_id(self) -> None:
        launched = Launched()

        started = JobLauncher(launched, PROGRAM).start("videos", "--download", "https://youtu.be/x")  # pyright: ignore[reportArgumentType]

        assert launched.commands == [[*PROGRAM.detached("videos", "--download", "https://youtu.be/x"), "--job", started.job]]
        assert len(started.job) == 12 and started.fields() == {"job": started.job}

    def test_failed_launch_is_a_refusal(self) -> None:
        with pytest.raises(ToolRefusal) as refusal:
            JobLauncher(Launched(CommandError("нет env")), PROGRAM).start("videos")  # pyright: ignore[reportArgumentType]

        assert refusal.value.code == JobLauncher.NOT_STARTED

    def test_command_takes_the_id_or_makes_its_own(self) -> None:
        parser = argparse.ArgumentParser()
        add_job_argument(parser)

        assert job_id(parser.parse_args(["--job", "abc"])) == "abc"
        assert len(job_id(parser.parse_args([]))) == 12
