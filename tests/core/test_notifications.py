from collections.abc import Sequence
from pathlib import Path

from jericho.core.agent.entities import AgentReply, ReplyStatus
from jericho.core.services.adapters.notify_send import NotifySendNotifier
from jericho.core.services.notifications import Notification, Urgency
from jericho.core.services.output import NotifyOutput
from jericho.core.services.runner import CommandError


class Runner:
    def __init__(self, answer: str = "", fails: bool = False) -> None:
        self.commands: list[list[str]] = []
        self._answer = answer
        self._fails = fails

    def run(self, command: Sequence[str], stdin: str | None = None, *, reads: bool = False, dry_answer: str = "") -> str:
        self.commands.append(list(command))
        if self._fails:
            raise CommandError("no notification daemon")
        return self._answer

    def launch(self, command: Sequence[str]) -> None:
        pass


class Screen:
    def __init__(self) -> None:
        self.shown: list[Notification] = []

    def show(self, notification: Notification, replaces: int | None = None) -> int | None:
        self.shown.append(notification)
        return None


class TestNotifySendNotifier:
    def test_builds_the_command_and_returns_the_id(self) -> None:
        runner = Runner("42")
        notification = Notification("Jericho · вопрос", "-какой проект?", Urgency.NORMAL, timeout_ms=12000)

        assert NotifySendNotifier(runner).show(notification, replaces=7) == 42
        assert runner.commands == [[
            str(Path("/usr/bin/notify-send")), "--app-name", "Jericho", "--urgency", "normal", "--print-id",
            "--replace-id", "7", "--expire-time", "12000", "--", "Jericho · вопрос", "-какой проект?",
        ]]

    def test_icon_goes_before_the_text(self) -> None:
        runner = Runner("1")

        NotifySendNotifier(runner, icon="jericho").show(Notification("Jericho"))

        assert runner.commands[0][:7] == [
            str(Path("/usr/bin/notify-send")), "--app-name", "Jericho", "--urgency", "normal", "--print-id", "--icon",
        ]
        assert runner.commands[0][7] == "jericho"

    def test_failure_to_show_does_not_raise(self) -> None:
        assert NotifySendNotifier(Runner(fails=True)).show(Notification("Jericho")) is None


class TestNotifyOutput:
    def test_reply_becomes_a_notification_titled_by_its_status(self) -> None:
        screen = Screen()
        output = NotifyOutput(screen, "home")

        output.deliver("напомни", AgentReply(ReplyStatus.DONE, "Напоминание: духовка"))
        output.deliver("сводка", AgentReply(ReplyStatus.FAILED, "модель недоступна"))

        assert [(shown.title, shown.body, shown.urgency) for shown in screen.shown] == [
            ("home", "Напоминание: духовка", Urgency.NORMAL),
            ("home · сбой", "модель недоступна", Urgency.CRITICAL),
        ]
