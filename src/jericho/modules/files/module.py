"""Модуль ядра «файлы»: ассистент смотрит, ищет, читает и меняет файлы внутри разрешённых папок."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from jericho.core.modules.config import ModuleConfig, ModuleServices
from jericho.core.prompting.protocols import PromptContext
from jericho.core.tools.tool import Tool
from jericho.modules.files.access import FileAccess
from jericho.modules.files.adapters.archives import StandardArchiver
from jericho.modules.files.adapters.dry_run import DryRunArchiver, DryRunChanger, DryRunTrash, NoVersions
from jericho.modules.files.adapters.local import LocalFileSystem
from jericho.modules.files.adapters.opener import CommandOpener
from jericho.modules.files.adapters.trash import DirectoryTrash, FreedesktopTrash
from jericho.modules.files.adapters.versions import DirectoryVersions
from jericho.modules.files.context import FileRoots
from jericho.modules.files.entities import Root
from jericho.modules.files.guard import PathGuard
from jericho.modules.files.protocols import Archiver, FileChanger, FileSystem, Opener, Trash, Versions
from jericho.modules.files.settings import FilesSettings
from jericho.modules.files.tools.archive import Pack, Unpack
from jericho.modules.files.tools.change import CreateFile, EditFile, MakeDir, WriteFile
from jericho.modules.files.tools.delete import Delete
from jericho.modules.files.tools.open import OpenFile
from jericho.modules.files.tools.read import FileInfo, FindFiles, ListDir, ReadFile
from jericho.modules.files.tools.transfer import Copy, Move


class FilesModule(ModuleConfig):
    """Части собирают фабричные методы — проект меняет одну, а не всю сборку:

        class ServerFiles(FilesModule):
            def filesystem(self) -> FileSystem:
                return HostFileSystem(...)

    Фабрики вызываются в `ready()`; `self.services` и `self.settings` к этому времени уже есть.
    """

    name = "files"

    VERSIONS = "files/versions"      # в папке состояния: прежние версии живут дольше поручения
    TRASH = "files/trash"            # своя корзина, если общей нет (`trash = "directory"`)

    def ready(self, services: ModuleServices) -> None:
        self.services = services
        self.settings = services.settings.section(self.name, FilesSettings)
        self.access = FileAccess(
            self.guard(), self.filesystem(), self.changer(), self.versions(), services.core.confirmation, services.core.foreign
        )

    def guard(self) -> PathGuard:
        roots = [Root(root.path, root.read_only, root.untrusted) for root in self.settings.roots]
        return PathGuard(roots, self.settings.deny, self.protected())

    def protected(self) -> Iterable[Path]:
        """Папки самого ассистента (`core.own_paths`) — список живой, см. `PathGuard`."""
        return self.services.core.own_paths

    def filesystem(self) -> FileSystem:
        return LocalFileSystem()

    def changer(self) -> FileChanger:
        return DryRunChanger() if self.services.core.dry_run else LocalFileSystem()

    def versions(self) -> Versions:
        if self.services.core.dry_run:
            return NoVersions()
        return DirectoryVersions(self.services.core.paths.state_dir / self.VERSIONS)

    def trash(self) -> Trash:
        if self.services.core.dry_run:
            return DryRunTrash()
        if self.settings.trash == "directory":
            return DirectoryTrash(self.services.core.paths.state_dir / self.TRASH)
        return FreedesktopTrash()

    def archiver(self) -> Archiver:
        archiver = StandardArchiver()
        return DryRunArchiver(archiver) if self.services.core.dry_run else archiver

    def opener(self) -> Opener | None:
        """Нет команды открытия в настройках — нет и ручки: на сервере открывать нечем."""
        command = self.settings.open_command
        return CommandOpener(self.services.core.runner, command) if command else None

    def tools(self) -> Sequence[Tool[Any]]:
        settings, access, opener = self.settings, self.access, self.opener()
        return (
            ListDir(access, settings.max_results),
            FileInfo(access),
            FindFiles(access),
            ReadFile(access, settings.max_read_bytes, settings.max_file_bytes),
            MakeDir(access),
            CreateFile(access),
            EditFile(access, settings.max_file_bytes),
            WriteFile(access),
            Copy(access),
            Move(access),
            Delete(access, self.trash()),
            Unpack(access, self.archiver(), settings.max_unpack_bytes, settings.max_unpack_files),
            Pack(access, self.archiver(), settings.max_unpack_files),
            *((OpenFile(access, opener),) if opener else ()),
        )

    def contexts(self) -> Sequence[PromptContext]:
        return (FileRoots(self.access.guard),)
