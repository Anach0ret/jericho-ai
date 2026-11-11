"""Слой «уведомления»: вопрос после сводки — о ней; reply выбирает своё; чужое и забытое не подставляется."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import ValidationError

from jericho.core.agent.entities import AgentReply, ReplyStatus
from jericho.core.agent.task import Outcome, Task
from jericho.core.services.foreign import ForeignText
from jericho.core.services.sent import SentLog, SentNotice
from jericho.modules.notices.settings import NoticesSettings
from jericho.modules.notices.task_layer import NoticeContext

NOW = datetime.now(UTC)
MORNING_FACTS = {"logs": {"since": "2026-11-07T08:00:00+03:00", "until": "2026-11-08T08:00:00+03:00", "level": "WARNING"}}


@pytest.fixture
def log(tmp_path: Path) -> SentLog:
    log = SentLog.at(tmp_path)
    log.record(SentNotice("old", "owner", NOW - timedelta(hours=2), "утренняя сводка", "done", "Одна WARNING", "бот /api/.env", MORNING_FACTS, ("example.com",)))
    log.confirm("old", True, ["501"])
    log.record(SentNotice("new", "owner", NOW - timedelta(minutes=5), "watch", "failed", "Сайт не отвечает", "shop.example"))
    log.confirm("new", True, ["777"])
    return log


def asked(layer: NoticeContext, text: str = "какая именно ошибка?", reply_to: str = "", attended: bool = True) -> str:
    seen: list[str] = []

    def model(task: Task) -> Outcome:
        seen.append(task.message)
        return Outcome(AgentReply(ReplyStatus.DONE, "ok"))

    layer.handle(Task(text, text, attended, reply_to), model)
    return seen[0]


def layer(log: SentLog, mine: tuple[str, ...] = ("owner",), foreign: ForeignText | None = None) -> NoticeContext:
    return NoticeContext(log, mine, foreign or ForeignText(), shown=5, chars=800)


class TestNoticeContext:
    def test_reply_to_the_old_summary_shows_only_it_even_after_a_newer(self, log: SentLog) -> None:
        message = asked(layer(log), reply_to="501")

        assert "Одна WARNING" in message and "2026-11-07T08:00:00+03:00" in message and "Сайт не отвечает" not in message

    def test_reply_to_an_unknown_message_substitutes_no_other_notice(self, log: SentLog) -> None:
        """Ревью плана 11.11.2026: потерянный reply не должен превращаться в «вопрос о последней сводке»."""
        message = asked(layer(log), reply_to="999")

        assert "нет среди твоих уведомлений" in message and "Одна WARNING" not in message and "Сайт не отвечает" not in message

    def test_without_reply_recent_notices_newest_first(self, log: SentLog) -> None:
        message = asked(layer(log))

        assert message.index("Сайт не отвечает") < message.index("Одна WARNING") and "спроси, о каком" in message

    def test_someone_else_sees_no_notices_of_the_owner(self, log: SentLog) -> None:
        assert asked(layer(log, mine=())) == "какая именно ошибка?"

    def test_scheduled_run_gets_no_notices(self, log: SentLog) -> None:
        assert asked(layer(log), attended=False) == "какая именно ошибка?"

    def test_foreign_text_of_a_shown_notice_is_counted_again(self, log: SentLog) -> None:
        foreign = ForeignText()

        asked(layer(log, foreign=foreign), reply_to="501")

        assert foreign.sources == {"example.com"}

    def test_nothing_sent_nothing_added(self, tmp_path: Path) -> None:
        assert asked(layer(SentLog.at(tmp_path))) == "какая именно ошибка?"


class TestSettings:
    def test_recipient_names_fit_a_file_name(self) -> None:
        with pytest.raises(ValidationError):
            NoticesSettings(recipients={"../owner": "1001"})


class TestWholePath:
    def test_summary_receipt_reply_brings_back_its_window(self, tmp_path: Path) -> None:
        """Сводка 08:00 → в ящик с окном → квитанция транспорта → через час reply на неё → к фразе — её окно, хотя
        после неё ушла тревога (рекомендация ревью 11.11.2026: проверить цепочку целиком)."""
        from jericho.core.conf.settings import OutputSettings
        from jericho.core.journal.run_trail import Trail
        from jericho.core.services.mailbox import Mailbox
        from jericho.core.services.output import output_for
        from jericho.modules.inbox.reception import Reception

        log, inbox, outbox = SentLog.at(tmp_path / "state"), Mailbox(tmp_path / "inbox"), Mailbox(tmp_path / "outbox")
        settings = OutputSettings(kind="mailbox", mailbox=outbox.root)
        window = {"project": "shop", "since": "2026-11-07T08:00:00+03:00", "until": "2026-11-08T08:00:00+03:00"}
        output_for(settings, "server", log, lambda: Trail({"logs": [window]})).deliver("утренняя сводка", AgentReply(ReplyStatus.DONE, "Одна WARNING"))
        output_for(settings, "server", log).deliver("watch", AgentReply(ReplyStatus.FAILED, "Сайт не отвечает"))
        summary, alert = (Mailbox.read(path)["notice"] for path in outbox.waiting())
        inbox.post({"receipt": summary, "delivered": True, "messages": [501]})
        inbox.post({"receipt": alert, "delivered": True, "messages": [502]})
        Reception(inbox, outbox, cast(Any, None), {}, 4000, log).tick()

        message = asked(layer(log), reply_to="501")

        assert "Одна WARNING" in message and "2026-11-07T08:00:00+03:00" in message and "Сайт не отвечает" not in message
