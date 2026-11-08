"""Переключатели голоса, которые человек меняет на ходу (окно на панели, `<проект> voice`), а не в настройках."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from jericho.core.services.adapters.json_file import JsonStateFile
from jericho.core.services.notifications import Answer, AskingNotifier, Notification, Urgency


@dataclass(frozen=True, slots=True)
class VoicePrefs:
    quiet: bool = False       # «не беспокоить»: уведомлений об ответах нет; вопросы и сбои — как обычно
    buttons: bool = True      # «Да / Нет» кнопками; выключено — вопрос только голосом (действует, если voice.buttons)


class VoicePrefsFile:
    """`{"quiet": bool, "buttons": bool}` в папке состояния: держится, пока не переключат обратно."""

    def __init__(self, path: Path) -> None:
        self._file = JsonStateFile(path)

    def read(self) -> VoicePrefs:
        raw = self._file.read(lambda content: content if isinstance(content, dict) else {}, {})
        return VoicePrefs(quiet=raw.get("quiet") is True, buttons=raw.get("buttons") is not False)

    def write(self, prefs: VoicePrefs) -> None:
        self._file.write({"quiet": prefs.quiet, "buttons": prefs.buttons})


class QuietNotifier:
    """«Не беспокоить»: обычные уведомления не показываются, сбой (CRITICAL) и вопрос с кнопками — показываются."""

    def __init__(self, notifier: AskingNotifier) -> None:
        self._notifier = notifier

    def show(self, notification: Notification, replaces: int | None = None) -> int | None:
        if notification.urgency is not Urgency.CRITICAL:
            return replaces          # не показали: следующее «на месте» встанет туда же, куда встало бы
        return self._notifier.show(notification, replaces)

    def ask(self, notification: Notification, wait: float, replaces: int | None = None) -> Answer:
        return self._notifier.ask(notification, wait, replaces)


class VoicePrefsCommand:
    name = "voice"
    help = "переключатели голоса: quiet on|off — «не беспокоить», buttons on|off — «Да / Нет» кнопками; без аргументов — как сейчас"

    def __init__(self, prefs: VoicePrefsFile) -> None:
        self._prefs = prefs

    def configure(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("switch", nargs="?", choices=("quiet", "buttons"))
        parser.add_argument("state", nargs="?", choices=("on", "off"))

    def run(self, args: argparse.Namespace) -> None:
        prefs = self._prefs.read()
        if args.switch:
            if args.state is None:
                raise SystemExit("скажи, включить или выключить: on или off")
            on = args.state == "on"
            prefs = VoicePrefs(quiet=on, buttons=prefs.buttons) if args.switch == "quiet" else VoicePrefs(quiet=prefs.quiet, buttons=on)
            self._prefs.write(prefs)
        print(f"не беспокоить: {'вкл' if prefs.quiet else 'выкл'}; кнопки «Да / Нет»: {'вкл' if prefs.buttons else 'выкл'}")
