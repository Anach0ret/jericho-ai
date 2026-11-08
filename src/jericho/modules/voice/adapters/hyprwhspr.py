"""Распознавание речи через hyprwhspr (локальная модель, офлайн)."""

from __future__ import annotations

from contextlib import suppress
from pathlib import Path

from jericho.core.services.runner import CommandError, CommandRunner
from jericho.modules.voice.protocols import SpeechRecognizerError


class HyprwhsprRecognizer:
    """`hyprwhspr record capture`: начинает запись, ждёт её остановки и печатает текст в stdout.

    В этом режиме hyprwhspr не вставляет текст в активное окно. Запись останавливает отдельная
    команда `hyprwhspr record stop` — её вызывает отпускание клавиши.
    """

    def __init__(self, runner: CommandRunner, executable: Path) -> None:
        self._runner = runner
        self._executable = str(executable)

    def listen(self) -> str:
        try:
            return self._runner.run([self._executable, "record", "capture"])
        except CommandError as error:
            self._cancel()   # не оставляем микрофон включённым, если capture не дождался остановки
            raise SpeechRecognizerError(str(error)) from error

    def stop(self) -> None:
        with suppress(CommandError):      # записи нет — останавливать нечего
            self._runner.run([self._executable, "record", "stop"])

    def _cancel(self) -> None:
        with suppress(CommandError):      # не отменилось — главное уже сказано ошибкой записи
            self._runner.run([self._executable, "record", "cancel"])
