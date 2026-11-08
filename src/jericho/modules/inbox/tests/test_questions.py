from datetime import UTC, datetime, timedelta
from pathlib import Path

from jericho.core.services.adapters.confirmation_file import JsonFileConfirmationStore
from jericho.core.services.mailbox import Mailbox
from jericho.core.services.paths import Paths
from jericho.modules.inbox.questions import QuestionWatch

ASKED = datetime(2026, 10, 28, 14, 0, tzinfo=UTC)


class Setup:
    def __init__(self, tmp_path: Path, remind: int | None = 30) -> None:
        self.now = ASKED
        self.paths = Paths(tmp_path / "state", tmp_path / "run")
        self.outbox = Mailbox(tmp_path / "exchange" / "outbox")
        ttl = timedelta(minutes=120)
        self.watch = QuestionWatch(["42"], self.paths, ttl, timedelta(minutes=remind) if remind else None, self.outbox, clock=lambda: self.now)
        self.store = JsonFileConfirmationStore(self.paths.for_user("42").confirmation, ttl, clock=lambda: self.now)

    def sent(self) -> list[dict[str, object]]:
        return [Mailbox.read(path) for path in self.outbox.waiting()]


class TestQuestionWatch:
    """В чате вопрос «да?» ждёт долго — напомнить и сказать «истёк», а не молчать."""

    def test_reminds_once_with_buttons_then_says_expired_once(self, tmp_path: Path) -> None:
        setup = Setup(tmp_path)
        setup.store.ask("restart_container", {"container": "shop"}, "перезапустить shop", "run-1")

        setup.now = ASKED + timedelta(minutes=10)
        setup.watch.tick()
        setup.now = ASKED + timedelta(minutes=31)
        setup.watch.tick()
        setup.watch.tick()
        setup.now = ASKED + timedelta(minutes=121)
        setup.watch.tick()
        setup.watch.tick()

        reminder, expired = setup.sent()
        assert (reminder["chat"], reminder["status"], reminder["confirm"]) == ("42", "clarify", "перезапустить shop")
        assert reminder["text"] == "Вопрос в силе до 16:00. Нет ответа — ничего не сделаю."
        assert (expired["status"], expired["title"]) == ("stopped", "Вопрос истёк: перезапустить shop")
        assert setup.store.take_expired() is None

    def test_no_reminder_once_yes_was_heard_or_when_switched_off(self, tmp_path: Path) -> None:
        heard = Setup(tmp_path / "a")
        heard.store.ask("restart_container", {}, "перезапустить", "run-1")
        heard.store.approve("run-2")
        quiet = Setup(tmp_path / "b", remind=None)
        quiet.store.ask("restart_container", {}, "перезапустить", "run-1")

        for setup in (heard, quiet):
            setup.now = ASKED + timedelta(minutes=60)
            setup.watch.tick()

        assert heard.sent() == [] and quiet.sent() == []

    def test_user_without_a_question_gets_nothing(self, tmp_path: Path) -> None:
        setup = Setup(tmp_path)

        setup.watch.tick()

        assert setup.sent() == []
