"""Замок между процессами на файле (flock): занят, пока жив процесс, который его взял.

В файле замка лежит номер процесса-держателя: по нему команда `stop` знает, кого останавливать. Номер верен,
пока замок занят, — поэтому его читают, только убедившись, что замок занят, и чужой номер не попадётся.
"""

from __future__ import annotations

import fcntl
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import IO


class FileLock:
    """Занятый замок ждёт не дольше `wait` секунд; по умолчанию не ждёт вовсе. Упавший процесс замок не держит."""

    POLL = 0.1

    def __init__(self, path: Path, wait: float = 0.0, sleep: Callable[[float], None] = time.sleep) -> None:
        self._path = path
        self._wait = wait
        self._sleep = sleep
        self._file: IO[str] | None = None

    def acquire(self) -> bool:
        self._path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        deadline = time.monotonic() + self._wait
        while not self._try():
            if time.monotonic() >= deadline:
                return False
            self._sleep(self.POLL)
        return True

    def release(self) -> None:
        if self._file is not None:
            fcntl.flock(self._file, fcntl.LOCK_UN)
            self._file.close()
            self._file = None

    def holder(self) -> int | None:
        if self._path.exists() and self._try():
            self.release()
            return None
        try:
            return int(self._path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return None      # замок свободен (файла нет) или держатель ещё не успел записать номер

    def _try(self) -> bool:
        # не "w": попытка взять занятый замок не стирает номер держателя; 600 — как все файлы ассистента (E015)
        file = os.fdopen(os.open(self._path, os.O_RDWR | os.O_CREAT | os.O_APPEND, 0o600), "a+", encoding="utf-8")
        try:
            fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            file.close()
            return False
        file.seek(0)
        file.truncate()
        file.write(str(os.getpid()))
        file.flush()
        self._file = file
        return True
