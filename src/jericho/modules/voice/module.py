"""Модуль ядра «голос»: поручение приходит речью, ответ уходит всплывающим уведомлением.

Модуль общий, адаптеры узкие: чем распознавать, выбирает настройка `voice.recognizer`. Проверено на Linux
с hyprwhspr; другой распознаватель — новый адаптер и строка в списке ниже.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import TYPE_CHECKING

from jericho.core.management.base import Command
from jericho.core.modules.config import ModuleConfig, ModuleServices
from jericho.core.modules.registry import ModuleError
from jericho.core.services.adapters.dbus_notify import DBusNotifier
from jericho.core.services.adapters.file_lock import FileLock
from jericho.core.services.runner import SubprocessRunner
from jericho.modules.voice.adapters.hyprwhspr import HyprwhsprRecognizer
from jericho.modules.voice.adapters.program_launcher import ProgramAnswerLauncher
from jericho.modules.voice.adapters.status_file import StatusFile
from jericho.modules.voice.command import ListenCommand
from jericho.modules.voice.prefs import QuietNotifier, VoicePrefsCommand, VoicePrefsFile
from jericho.modules.voice.protocols import SpeechRecognizer, VoiceState
from jericho.modules.voice.settings import VoiceSettings
from jericho.modules.voice.voice_command import Buttons, ReplyPresenter, VoiceCommand

if TYPE_CHECKING:
    from jericho.core.agent.handle_phrase import HandlePhrase

RECOGNIZERS: Mapping[str, Callable[[VoiceSettings], SpeechRecognizer]] = {
    "hyprwhspr": lambda settings: HyprwhsprRecognizer(SubprocessRunner(timeout=settings.listen_timeout), settings.hyprwhspr),
}


class VoiceModule(ModuleConfig):
    name = "voice"

    LOCK = "listen.lock"      # повторное нажатие клавиши, пока идёт запись или ответ, ничего не запускает
    STATUS = "voice.json"     # чем занят голос — читает виджет панели (например, плагин Noctalia)
    PREFS = "voice-prefs.json"   # переключатели на ходу: «не беспокоить», кнопки — в папке состояния, переживают выход

    def ready(self, services: ModuleServices) -> None:
        self._settings = services.settings.section(self.name, VoiceSettings)
        self._lock_file = services.core.paths.runtime_dir / self.LOCK
        self._status = StatusFile(services.core.paths.runtime_dir / self.STATUS, {
            VoiceState.LISTENING: self._settings.listen_timeout,
            VoiceState.THINKING: services.settings.agent.timeout,
            VoiceState.WAITING: self._settings.answer_wait,
        })
        self._title = self._settings.title or services.program.name
        self._gate = services.core.confirmation
        self._prefs = VoicePrefsFile(services.core.paths.state_dir / self.PREFS)
        self._program = services.program
        if self._settings.recognizer not in RECOGNIZERS:
            known = ", ".join(sorted(RECOGNIZERS))
            raise ModuleError(f"voice.recognizer: no recognizer '{self._settings.recognizer}', available: {known}")

    def commands(self, handle_phrase: HandlePhrase) -> Sequence[Command]:
        prefs = self._prefs.read()
        notifier = DBusNotifier(self._title, icon=self._settings.icon)
        buttons = self._settings.buttons and prefs.buttons
        voice_command = VoiceCommand(
            recognizer=RECOGNIZERS[self._settings.recognizer](self._settings),
            handle_phrase=handle_phrase,
            notifier=QuietNotifier(notifier) if prefs.quiet else notifier,
            presenter=ReplyPresenter(self._title),
            lock=FileLock(self._lock_file),
            gate=self._gate,
            board=self._status,
            buttons=Buttons(ProgramAnswerLauncher(self._program), self._settings.answer_wait, self._settings.reply_field) if buttons else None,
        )
        return (ListenCommand(voice_command), VoicePrefsCommand(self._prefs))

    def status(self) -> Mapping[str, object]:
        """Чем занят голос сейчас и переключатели: для шапки и настроек окна на панели."""
        prefs = self._prefs.read()
        return {**self._status.current(), "quiet": prefs.quiet, "buttons": prefs.buttons}
