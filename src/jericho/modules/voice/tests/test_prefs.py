import argparse
from pathlib import Path

import pytest

from jericho.core.services.notifications import Answer, Notification, Urgency
from jericho.modules.voice.prefs import QuietNotifier, VoicePrefs, VoicePrefsCommand, VoicePrefsFile


class Screen:
    def __init__(self) -> None:
        self.shown: list[Notification] = []
        self.asked: list[Notification] = []

    def show(self, notification: Notification, replaces: int | None = None) -> int | None:
        self.shown.append(notification)
        return 5

    def ask(self, notification: Notification, wait: float, replaces: int | None = None) -> Answer:
        self.asked.append(notification)
        return Answer(5, "yes")


def run(prefs: VoicePrefsFile, *argv: str) -> None:
    command = VoicePrefsCommand(prefs)
    parser = argparse.ArgumentParser()
    command.configure(parser)
    command.run(parser.parse_args(list(argv)))


class TestVoicePrefs:
    def test_defaults_without_a_file(self, tmp_path: Path) -> None:
        assert VoicePrefsFile(tmp_path / "prefs.json").read() == VoicePrefs(quiet=False, buttons=True)

    def test_switches_hold_until_switched_back(self, tmp_path: Path) -> None:
        prefs = VoicePrefsFile(tmp_path / "prefs.json")

        run(prefs, "quiet", "on")
        run(prefs, "buttons", "off")
        assert prefs.read() == VoicePrefs(quiet=True, buttons=False)

        run(prefs, "quiet", "off")
        assert prefs.read() == VoicePrefs(quiet=False, buttons=False)

    def test_switch_without_state_is_an_error(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit):
            run(VoicePrefsFile(tmp_path / "prefs.json"), "quiet")


class TestQuietNotifier:
    def test_only_failures_and_questions_get_through(self) -> None:
        screen = Screen()
        quiet = QuietNotifier(screen)

        assert quiet.show(Notification("Jericho · думаю", "«открой ютуб»", Urgency.LOW), replaces=3) == 3
        quiet.show(Notification("Jericho", "Открыл YouTube"))
        quiet.show(Notification("Jericho · сбой", "Распознавание речи не ответило", Urgency.CRITICAL))
        quiet.ask(Notification("Jericho · вопрос", "Удалить?"), wait=1)

        assert [n.title for n in screen.shown] == ["Jericho · сбой"]
        assert [n.title for n in screen.asked] == ["Jericho · вопрос"]
