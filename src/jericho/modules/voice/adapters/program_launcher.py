"""Кнопка в уведомлении → `<проект> listen --answer yes`: новый запуск ассистента с тем же окружением проекта.

Набранный ответ идёт через стандартный ввод, а не в строке команды: строку команды видит любой процесс машины.
"""

from __future__ import annotations

import logging
import os
import subprocess

from jericho.core.services.program import Program

logger = logging.getLogger(__name__)


class ProgramAnswerLauncher:
    """Запускает ответ и ждёт его: ожидающий процесс к этому времени уже отпустил замок фразы."""

    def __init__(self, program: Program, command: str = "listen") -> None:
        self._program = program
        self._command = command

    def answer(self, action: str, replaces: int, text: str = "", question: str = "") -> None:
        arguments = [*self._program.command, self._command, "--answer", action, "--replaces", str(replaces)]
        if question:
            arguments += ["--question", question]
        environment = {**os.environ, **self._program.environment}
        code = subprocess.run(arguments, input=text, text=True, encoding="utf-8", env=environment, check=False).returncode
        if code:
            logger.warning("voice", extra={"data": {"answer": action, "exit_code": code}})
