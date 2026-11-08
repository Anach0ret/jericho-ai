"""Повторный запуск ассистента без человека рядом."""

from __future__ import annotations

import subprocess
from collections.abc import Mapping, Sequence
from typing import Protocol


class Relaunch(Protocol):
    """Запускает ту же команду ассистента ещё раз, с отметкой «рядом никого нет», и ждёт её.

    Отметка должна быть в окружении с самого начала: по ней собираются подтверждение и сервер ручек.
    Поэтому команда, которой нужен запуск без человека, не переключает себя на ходу, а запускается заново.
    """

    @property
    def attended(self) -> bool:
        """Есть ли рядом человек у этого запуска. Нет — значит, это уже повторный запуск."""
        ...

    def unattended(self, *arguments: str) -> int:
        """Код завершения дочернего запуска."""
        ...


class ProcessRelaunch:
    """Дочерний процесс; его вывод идёт прямо в терминал или в журнал таймера — как у самой команды."""

    def __init__(self, launch: Sequence[str], environment: Mapping[str, str], attended: bool) -> None:
        self._launch = tuple(launch)
        self._environment = dict(environment)
        self._attended = attended

    @property
    def attended(self) -> bool:
        return self._attended

    def unattended(self, *arguments: str) -> int:
        return subprocess.run([*self._launch, *arguments], env=self._environment, check=False).returncode


def relaunched(relaunch: Relaunch, *arguments: str) -> bool:
    """Шаг команды, которая работает только без человека рядом.

    Человек рядом — команда запущена заново с отметкой «никого нет», и её дело сделано: True. Неудача
    дочернего запуска — `SystemExit` с его кодом, чтобы таймер её увидел. Рядом никого — False: делать самой.
    """
    if not relaunch.attended:
        return False
    code = relaunch.unattended(*arguments)
    if code:
        raise SystemExit(code)
    return True
