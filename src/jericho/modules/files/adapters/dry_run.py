"""«Вхолостую»: изменения не выполняются, а пишутся в журнал — как команды у `CommandRunner`."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path

from jericho.modules.files.entities import ArchiveFormat, Member
from jericho.modules.files.protocols import Archiver

logger = logging.getLogger(__name__)


class DryRunChanger:
    def make_dir(self, path: Path) -> None:
        self._log("make_dir", path)

    def create(self, path: Path, data: bytes) -> None:
        self._log("create", path, f"{len(data)} bytes")

    def replace(self, path: Path, data: bytes) -> None:
        self._log("replace", path, f"{len(data)} bytes")

    def copy(self, source: Path, target: Path) -> None:
        self._log("copy", source, target)

    def move(self, source: Path, target: Path) -> None:
        self._log("move", source, target)

    @staticmethod
    def _log(action: str, *arguments: object) -> None:
        logger.info("dry_run", extra={"data": {"command": ["files", action, *map(str, arguments)]}})


class NoVersions:
    """Вхолостую сохранять нечего: файл не меняется."""

    def keep(self, path: Path) -> Path | None:
        return None


class DryRunTrash:
    def discard(self, path: Path) -> str:
        logger.info("dry_run", extra={"data": {"command": ["files", "trash", str(path)]}})
        return "корзина (вхолостую)"


class DryRunArchiver:
    """Что внутри — читает по-настоящему (это не меняет мир), распаковку и упаковку — только в журнал."""

    def __init__(self, archiver: Archiver) -> None:
        self._archiver = archiver

    def members(self, archive: Path) -> list[Member]:
        return self._archiver.members(archive)

    def unpack(self, archive: Path, target: Path, names: Sequence[str]) -> None:
        logger.info("dry_run", extra={"data": {"command": ["files", "unpack", str(archive), str(target), f"{len(names)} entries"]}})

    def pack(self, archive: Path, items: Sequence[tuple[Path, str]], format: ArchiveFormat) -> None:
        logger.info("dry_run", extra={"data": {"command": ["files", "pack", str(archive), f"{len(items)} entries"]}})
