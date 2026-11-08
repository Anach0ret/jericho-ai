"""Ответ на запрос — отдельным процессом `<проект> answer`, собранным заранее: он ждёт запрос на stdin.

Сборка ассистента — импорты, настройки, навыки — идёт секунды, на слабом сервере до трёх. Поэтому на каждого
пользователя держится один уже собранный процесс: запрос уходит ему сразу, а следующий собирается про запас.
У каждого поручения по-прежнему свой процесс — свой запуск, своё «да», своя запись в журнале.
"""

from __future__ import annotations

import logging
import subprocess
from collections.abc import Collection, Mapping, Sequence
from pathlib import Path

from jericho.core.services.process_tree import ProcessTree

logger = logging.getLogger(__name__)


class ProcessAnswerer:
    """Пользователь передаётся переменной `JERICHO_USER`: по ней процесс собирается со своей папкой сеанса."""

    STOP_WAIT = 5.0      # секунд ждать, пока ненужный уже процесс закончится сам

    def __init__(self, launch: Sequence[str], environment: Mapping[str, str], user_variable: str, timeout: float) -> None:
        self._launch = tuple(launch)
        self._environment = dict(environment)
        self._user_variable = user_variable
        self._timeout = timeout
        self._ready: dict[str, subprocess.Popen[str]] = {}

    def prepare(self, users: Collection[str]) -> None:
        """Собрать заранее по процессу на пользователя — тот, что умер, заменяется новым."""
        for user in users:
            process = self._ready.get(user)
            if process is None or process.poll() is not None:
                self._ready[user] = self._spawn(user)

    def answer(self, user: str, request: Path) -> bool:
        """True — процесс ответил и вышел с 0. Готовый процесс берётся сразу; нет его — запускается сейчас."""
        process = self._ready.pop(user, None)
        if process is None or process.poll() is not None:
            process = self._spawn(user)
        try:
            return self._run(process, request)
        finally:
            self.prepare([user])        # следующий собирается, пока пользователь читает ответ

    def close(self) -> None:
        """Ненужные больше процессы: закрытый stdin — «запросов не будет», они выходят сами."""
        for process in self._ready.values():
            if process.stdin is not None:
                process.stdin.close()
            try:
                process.wait(timeout=self.STOP_WAIT)
            except subprocess.TimeoutExpired:
                ProcessTree.stop(process)
        self._ready.clear()

    def _run(self, process: subprocess.Popen[str], request: Path) -> bool:
        try:
            if process.stdin is not None:
                process.stdin.write(f"{request}\n")
                process.stdin.close()
            code = process.wait(timeout=self._timeout)
        except subprocess.TimeoutExpired:
            ProcessTree.stop(process)      # с сервером ручек и программами внутри ручек (ревью 02.11.2026, №10)
            logger.error("inbox_timeout", extra={"data": {"request": request.name, "seconds": self._timeout}})
            return False
        except OSError as error:        # процесс умер, не дождавшись запроса: сломана сборка
            logger.error("inbox_answer_failed", extra={"data": {"request": request.name, "error": str(error)}})
            return False
        except BaseException:           # приём остановили посреди ответа: ответ не должен доделываться без него
            ProcessTree.stop(process)
            raise
        return code == 0

    def _spawn(self, user: str) -> subprocess.Popen[str]:
        environment = {**self._environment, self._user_variable: user}
        return subprocess.Popen(
            [*self._launch, "answer", "--wait"], env=environment, stdin=subprocess.PIPE, text=True, encoding="utf-8", start_new_session=True
        )
