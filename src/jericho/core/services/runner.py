"""Запуск внешних программ."""

from __future__ import annotations

import logging
import subprocess
from collections.abc import Sequence
from typing import Protocol

from jericho.core.services.phrase_deadline import PhraseDeadline
from jericho.core.services.process_tree import ProcessTree

logger = logging.getLogger(__name__)


class CommandError(Exception):
    """Программа не запустилась, не уложилась во время или завершилась с ошибкой."""

    def __init__(self, message: str, output: str = "") -> None:
        super().__init__(message)
        self.output = output    # всё, что программа вывела перед ошибкой: причина бывает дальше обрезки в сообщении


class CommandTimeout(CommandError):
    """Программа не уложилась во время."""


class CommandRunner(Protocol):
    """Выполняет команду и возвращает её вывод. Любая неудача — CommandError.

    Команда по умолчанию считается меняющей что-то снаружи: в режиме «вхолостую» она не выполняется,
    а вызывающий получает `dry_answer` — то, что программа ответила бы при успехе. Команду, которая
    только читает, вызывающий помечает `reads=True` — она выполняется всегда.
    """

    def run(
        self, command: Sequence[str], stdin: str | None = None, *, reads: bool = False, dry_answer: str = ""
    ) -> str: ...

    def launch(self, command: Sequence[str]) -> None:
        """Запускает программу и не ждёт её конца — для того, что остаётся работать: браузер, приложение.

        Вывода нет. Ошибка — только если программа не запустилась или сразу завершилась неудачей.
        Запуск всегда что-то меняет: в режиме «вхолостую» он не выполняется.
        """
        ...


class SubprocessRunner:
    """Запускает программу напрямую, без shell: аргументы не склеиваются в строку.

    `run` — в своей группе процессов: срок, срок ручки (`ToolTimeout`), Ctrl+C или любое другое прерывание
    останавливают программу вместе с её потомками, а исходное исключение идёт дальше как было (ревью 02.11.2026,
    сводка №10; критика плана 07.11.2026).
    """

    # Вывод программ — UTF-8 на любой ОС (`git`, `claude`, JSON), а не кодировка системы (на Windows — cp1252);
    # битый байт заменяется, а не роняет вызов.
    ENCODING = "utf-8"

    def __init__(self, timeout: float = 5.0, settle: float = 1.0, deadline: PhraseDeadline | None = None) -> None:
        self._timeout = timeout
        self._settle = settle      # сколько ждать после запуска, чтобы заметить мгновенный отказ программы
        self._deadline = deadline or PhraseDeadline()   # у программы модели (`claude`, `codex`) — срок фразы: не дольше остатка

    def run(
        self, command: Sequence[str], stdin: str | None = None, *, reads: bool = False, dry_answer: str = ""
    ) -> str:
        left = self._deadline.left()
        timeout = self._timeout if left is None else min(self._timeout, left)
        if timeout <= 0:
            raise CommandTimeout("the phrase is out of time — not started")
        try:
            process = subprocess.Popen(
                list(command), stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
                # Своя группа в том же сеансе: остановка достаёт программу с потомками, а свой сеанс — у `launch` —
                # и есть «отделено» (ревью 07.11.2026, повтор 0.64.3). Ввода нет — DEVNULL, а не терминал родителя:
                # из фоновой группы чтение терминала остановило бы программу (SIGTTIN) до срока (повтор 0.64.4, №14).
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding=self.ENCODING, errors="replace", process_group=0,
            )
        except OSError as error:
            raise CommandError(str(error)) from error
        with process:
            try:
                stdout, stderr = process.communicate(stdin, timeout=timeout)
            except BaseException as error:      # один обработчик: прерывание внутри `except TimeoutExpired` не проскочит
                ProcessTree.stop(process)
                if isinstance(error, subprocess.TimeoutExpired):
                    raise CommandTimeout(f"no answer in {timeout:g} s") from error
                raise
        if process.returncode:
            raise CommandError(f"exit code {process.returncode}: {(stderr or stdout).strip()[:300]}", output=stdout.strip())
        return stdout.strip()

    def launch(self, command: Sequence[str]) -> None:
        # Отдельный сеанс и никаких каналов вывода: программа переживёт Jericho и не заставит его ждать.
        # (`gio open` при закрытом браузере остаётся висеть, пока браузер открыт, — журнал 12.10.2026.)
        try:
            process = subprocess.Popen(
                list(command),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,     # свой сеанс — признак отделённого: `ProcessTree` в него не заходит
            )
        except OSError as error:
            raise CommandError(str(error)) from error
        try:
            code = process.wait(timeout=self._settle)
        except subprocess.TimeoutExpired:
            return      # работает — этого и ждали
        if code != 0:
            raise CommandError(f"exit code {code}")


class DryRunRunner:
    """Режим «вхолостую»: читающие команды выполняет, меняющие — только записывает в журнал."""

    def __init__(self, runner: CommandRunner) -> None:
        self._runner = runner

    def run(
        self, command: Sequence[str], stdin: str | None = None, *, reads: bool = False, dry_answer: str = ""
    ) -> str:
        if reads:
            return self._runner.run(command, stdin, reads=True)
        logger.info("dry_run", extra={"data": {"command": list(command)}})
        return dry_answer

    def launch(self, command: Sequence[str]) -> None:
        logger.info("dry_run", extra={"data": {"command": list(command)}})
