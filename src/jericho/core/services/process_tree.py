"""Остановить синхронный запуск со всем деревом потомков: TERM → пауза → KILL.

Алгоритм — `ProcessTree`, что умеет ОС — `Processes`: на Linux и macOS (`PosixProcesses`) — сеанс как признак
отделённого и группы процессов, на Windows (`WindowsProcesses`) — только дерево. Потомков и «жив ли» на любой ОС
даёт `psutil`. Что где обещано — `docs/security.md`, «Платформы».
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import time
from typing import ClassVar, Protocol

import psutil


class Processes(Protocol):
    """Что ОС умеет о процессах для остановки дерева."""

    def session(self, pid: int) -> int | None:
        """Признак, общий для синхронного дерева и отличный у отделённого; None — процесса нет."""
        ...

    def stop(self, pid: int, *, force: bool) -> None:
        """Попросить выйти (`force=False`) или остановить сразу; процесса уже нет — не ошибка."""
        ...


class PosixProcesses:
    """Linux, macOS: отделённое — другой **сеанс** (`runner.launch` даёт программе свой); сигнал — и всей группе
    процесса, кроме своей: так достаётся и тот в группе, кого уже не видно по дереву."""

    def session(self, pid: int) -> int | None:
        try:
            return os.getsid(pid)
        except OSError:
            return None       # процесс уже вышел

    def stop(self, pid: int, *, force: bool) -> None:
        signum = signal.SIGKILL if force else signal.SIGTERM
        with contextlib.suppress(ProcessLookupError, PermissionError):
            group = os.getpgid(pid)
            if group != os.getpgrp():
                os.killpg(group, signum)
            os.kill(pid, signum)


class WindowsProcesses:
    """Windows: сеансов и групп POSIX нет — дерево целиком, включая отделённое, и выход без просьбы: TERM там —
    сразу TerminateProcess. Для разработки этого хватает; полные гарантии — Linux (решение владельца 08.11.2026)."""

    def session(self, pid: int) -> int | None:
        return 0 if psutil.pid_exists(pid) else None

    def stop(self, pid: int, *, force: bool) -> None:
        with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied):
            process = psutil.Process(pid)
            process.kill() if force else process.terminate()


def system_processes() -> Processes:
    return PosixProcesses() if hasattr(os, "getsid") else WindowsProcesses()


class ProcessTree:
    """Программа и все её потомки — даже ушедшие в свою группу: ответ inbox → `claude` → сервер ручек → программа ручки.

    `subprocess.run` при сроке или исключении убивал только прямого потомка (ревью 02.11.2026, сводка №10); остановка
    одной группы не доставала вложенные запуски со своей группой (ревью 07.11.2026, №2). Поэтому дерево собирается
    **до** первого сигнала — пока вожак жив, его потомков ещё видно. TERM — всем сразу, после паузы KILL — тем, кто
    остался, и тем, кто появился. KILL — в `finally`: прерывание посреди паузы (срок ручки, Ctrl+C) сначала добивает
    дерево (ревью 07.11.2026, №3). Своя группа процесса-родителя не трогается никогда. Не трогается и отделённое:
    процесс **другого сеанса**, чем останавливаемый, — вместе с поддеревом. `runner.launch` (браузер, приложение,
    фоновый план) даёт программе свой сеанс, `runner.run` — свою группу в том же сеансе. Сеанс держит ядро: метку в
    окружении программа теряла при `env -i` (ревью 07.11.2026, повтор прохода 6, №13, и повтор 0.64.3).
    """

    GRACE = 2.0      # секунд после TERM: успеть закрыть файлы; кто не вышел — KILL
    system: ClassVar[Processes] = system_processes()

    @classmethod
    def stop(cls, process: subprocess.Popen[str]) -> None:
        tree = cls._tree(process.pid)
        try:
            cls._send(tree, force=False)
            until = time.monotonic() + cls.GRACE
            while time.monotonic() < until and (process.poll() is None or any(map(cls._alive, tree))):
                time.sleep(0.02)
        finally:
            cls._send(tree | cls._tree(*(pid for pid in tree if cls._alive(pid))), force=True)
            process.wait()

    @classmethod
    def _tree(cls, *roots: int) -> set[int]:
        """Корни и их потомки в сеансе своего корня: в чужой сеанс — отделённое — обход не заходит."""
        found, queue = set(roots), [(root, cls.system.session(root)) for root in roots]
        while queue:
            pid, session = queue.pop()
            children = {child for child in cls._children(pid) - found if cls.system.session(child) == session}
            queue += [(child, session) for child in children]
            found |= children
        return found

    @staticmethod
    def _children(pid: int) -> set[int]:
        try:
            return {child.pid for child in psutil.Process(pid).children()}
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return set()      # процесс уже вышел

    @classmethod
    def _send(cls, pids: set[int], *, force: bool) -> None:
        for pid in pids:
            cls.system.stop(pid, force=force)

    @staticmethod
    def _alive(pid: int) -> bool:
        """Жив и не зомби: зомби уже ничего не делает."""
        try:
            return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return False
