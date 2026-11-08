"""Замок между процессами на файле: занят, пока жив процесс, который его взял. На любой ОС — пакет `filelock`.

Номер процесса-держателя лежит рядом, в `<замок>.pid`: по нему команда `stop` знает, кого останавливать. Не в самом
файле замка — на Windows занятый замок другим процессам не прочитать. Номер читают, только убедившись, что замок
занят: после упавшего держателя файл с номером остаётся, но свободный замок его не показывает.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from pathlib import Path

import filelock


class FileLock:
    """Занятый замок ждёт не дольше `wait` секунд; по умолчанию не ждёт вовсе. Упавший процесс замок не держит."""

    POLL = 0.1
    PRIVATE_FILE = 0o600      # как все файлы ассистента (E015)
    PRIVATE_DIR = 0o700

    def __init__(self, path: Path, wait: float = 0.0, sleep: Callable[[float], None] = time.sleep) -> None:
        self._path = path
        self._wait = wait
        self._sleep = sleep
        self._holder_file = path.with_name(f"{path.name}.pid")
        self._lock = self._file_lock()

    def acquire(self) -> bool:
        self._path.parent.mkdir(mode=self.PRIVATE_DIR, parents=True, exist_ok=True)
        deadline = time.monotonic() + self._wait
        while not self._try(self._lock):
            if time.monotonic() >= deadline:
                return False
            self._sleep(self.POLL)
        self._write_holder()
        return True

    def release(self) -> None:
        if self._lock.is_locked:
            self._holder_file.unlink(missing_ok=True)
            self._lock.release(force=True)

    def holder(self) -> int | None:
        if not self._path.exists():
            return None
        probe = self._file_lock()
        if self._try(probe):
            probe.release(force=True)
            return None
        try:
            return int(self._holder_file.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return None      # держатель ещё не успел записать номер

    def _file_lock(self) -> filelock.FileLock:
        # Свой дескриптор у каждого экземпляра: два замка на один файл и в одном процессе не берутся оба.
        return filelock.FileLock(self._path, mode=self.PRIVATE_FILE, thread_local=False)

    @staticmethod
    def _try(lock: filelock.FileLock) -> bool:
        try:
            lock.acquire(blocking=False)
        except filelock.Timeout:
            return False
        return True

    def _write_holder(self) -> None:
        descriptor = os.open(self._holder_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, self.PRIVATE_FILE)
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            file.write(str(os.getpid()))
