"""Unit-файлы таймеров: в папке systemd — или «вхолостую», только в журнал."""

from __future__ import annotations

import logging
from pathlib import Path

from jericho.modules.tasks.protocols import UnitFiles

logger = logging.getLogger(__name__)


class DirectoryUnitFiles:
    """`~/.config/systemd/user/`: туда systemd смотрит после `daemon-reload`."""

    def __init__(self, directory: Path) -> None:
        self._directory = directory

    def names(self, pattern: str) -> list[str]:
        return sorted(path.name for path in self._directory.glob(pattern)) if self._directory.is_dir() else []

    def read(self, name: str) -> str | None:
        path = self._directory / name
        return path.read_text(encoding="utf-8") if path.is_file() else None

    def write(self, name: str, text: str) -> None:
        self._directory.mkdir(parents=True, exist_ok=True)
        (self._directory / name).write_text(text, encoding="utf-8")

    def remove(self, name: str) -> None:
        (self._directory / name).unlink(missing_ok=True)


class DryRunUnitFiles:
    """Читает настоящую папку — чтобы показать, что изменилось бы, — а запись и удаление только пишет в журнал."""

    def __init__(self, real: UnitFiles) -> None:
        self._real = real

    def names(self, pattern: str) -> list[str]:
        return self._real.names(pattern)

    def read(self, name: str) -> str | None:
        return self._real.read(name)

    def write(self, name: str, text: str) -> None:
        logger.info("dry_run", extra={"data": {"command": ["timers", "write", name], "bytes": len(text)}})

    def remove(self, name: str) -> None:
        logger.info("dry_run", extra={"data": {"command": ["timers", "remove", name]}})
