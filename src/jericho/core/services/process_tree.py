"""Остановить синхронный запуск со всем деревом потомков: TERM → пауза → KILL."""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import time
from pathlib import Path


class ProcessTree:
    """Программа и все её потомки — даже ушедшие в свою группу: ответ inbox → `claude` → сервер ручек → программа ручки.

    `subprocess.run` при сроке или исключении убивал только прямого потомка (ревью 02.11.2026, сводка №10); остановка
    одной группы не доставала вложенные запуски со своей группой (ревью 07.11.2026, №2). Поэтому дерево собирается
    **до** первого сигнала — пока вожак жив, его потомков ещё видно (`/proc/<pid>/task/*/children`, интерфейс ядра
    Linux; `psutil` в зависимостях нет). TERM — всем сразу, после паузы KILL — тем, кто остался, и тем, кто появился.
    KILL — в `finally`: прерывание посреди паузы (срок ручки, Ctrl+C) сначала добивает дерево (ревью 07.11.2026, №3).
    Своя группа процесса-родителя не трогается никогда. Не трогается и отделённое: процесс **другого сеанса**, чем
    останавливаемый, — вместе с поддеревом. `runner.launch` (браузер, приложение, фоновый план) даёт программе свой
    сеанс, `runner.run` — свою группу в том же сеансе. Сеанс держит ядро: метку в окружении программа теряла при
    `env -i` и прятала, закрыв `/proc/<pid>/environ` (ревью 07.11.2026, повтор прохода 6, №13, и повтор 0.64.3).
    """

    GRACE = 2.0      # секунд после TERM: успеть закрыть файлы; кто не вышел — KILL

    @classmethod
    def stop(cls, process: subprocess.Popen[str]) -> None:
        tree = cls._tree(process.pid)
        try:
            cls._send(tree, signal.SIGTERM)
            until = time.monotonic() + cls.GRACE
            while time.monotonic() < until and (process.poll() is None or any(map(cls._alive, tree))):
                time.sleep(0.02)
        finally:
            cls._send(tree | cls._tree(*(pid for pid in tree if cls._alive(pid))), signal.SIGKILL)
            process.wait()

    @classmethod
    def _tree(cls, *roots: int) -> set[int]:
        """Корни и их потомки в сеансе своего корня: в чужой сеанс — отделённое — обход не заходит."""
        found, queue = set(roots), [(root, cls._session(root)) for root in roots]
        while queue:
            pid, session = queue.pop()
            children = {child for child in cls._children(pid) - found if cls._session(child) == session}
            queue += [(child, session) for child in children]
            found |= children
        return found

    @staticmethod
    def _session(pid: int) -> int | None:
        try:
            return os.getsid(pid)
        except OSError:
            return None       # процесс уже вышел

    @staticmethod
    def _children(pid: int) -> set[int]:
        try:
            return {int(child) for task in Path(f"/proc/{pid}/task").iterdir() for child in (task / "children").read_text().split()}
        except OSError:
            return set()      # процесс уже вышел

    @classmethod
    def _send(cls, pids: set[int], signum: signal.Signals) -> None:
        own = os.getpgrp()
        for pid in pids:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                group = os.getpgid(pid)
                if group != own:
                    os.killpg(group, signum)      # и тех в его группе, кого уже не видно по дереву
                os.kill(pid, signum)

    @staticmethod
    def _alive(pid: int) -> bool:
        """Жив и не зомби: зомби уже ничего не делает."""
        try:
            return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0] != "Z"
        except (OSError, IndexError):
            return False
