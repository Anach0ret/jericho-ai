import io
import tarfile
import zipfile
from pathlib import Path

import pytest

from jericho.core import ConfirmationGate, ToolResult
from jericho.core.testing import execute
from jericho.core.testing.fakes import Confirmations, say_yes
from jericho.modules.files.access import FileAccess
from jericho.modules.files.adapters.archives import StandardArchiver
from jericho.modules.files.adapters.dry_run import DryRunArchiver
from jericho.modules.files.entities import ArchiveFormat
from jericho.modules.files.errors import AlreadyExists
from jericho.modules.files.tests.conftest import MakeAccess
from jericho.modules.files.tools.archive import Pack, Unpack

LIMIT = 10**6


def unpack(access: FileAccess, max_bytes: int = LIMIT, **arguments: object) -> ToolResult:
    return execute(Unpack(access, StandardArchiver(), max_bytes, 100), arguments)


def zip_with(path: Path, entries: dict[str, str]) -> Path:
    with zipfile.ZipFile(path, "w") as file:
        for name, text in entries.items():
            file.writestr(name, text)
    return path


def tar_with(path: Path, *members: tarfile.TarInfo) -> Path:
    with tarfile.open(path, "w") as file:
        for member in members:
            file.addfile(member, io.BytesIO(b"x" * member.size) if member.isfile() else None)
    return path


def link(name: str, target: str) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.type, info.linkname = tarfile.SYMTYPE, target
    return info


def regular(name: str, size: int = 1) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.size = size
    return info


class TestUnpack:
    def test_into_a_new_folder_next_to_the_archive(self, access: FileAccess, tree: Path) -> None:
        zip_with(tree / "docs" / "фото.zip", {"a.txt": "1", "внутри/b.txt": "2"})

        result = execute(Unpack(access, StandardArchiver(), LIMIT, 100), {"archive": "фото.zip"})

        assert result.ok and result.data["files"] == 2 and result.data["top"] == ["a.txt", "внутри"]
        assert (tree / "docs" / "фото" / "внутри" / "b.txt").read_text() == "2"

    @pytest.mark.parametrize("name", ["../evil.txt", "a/../../evil.txt", "/etc/evil", "C:/evil.txt"])
    def test_a_path_leading_out_refuses_the_whole_archive(self, access: FileAccess, tree: Path, name: str) -> None:
        zip_with(tree / "docs" / "злой.zip", {"ok.txt": "1", name: "2"})

        assert execute(Unpack(access, StandardArchiver(), LIMIT, 100), {"archive": "злой.zip"}).error == "archive_unsafe"
        assert not (tree / "docs" / "злой").exists() and not (tree / "evil.txt").exists()

    def test_link_out_is_unsafe_link_inside_is_fine(self, access: FileAccess, tree: Path) -> None:
        tar_with(tree / "docs" / "ссылка-вовне.tar", regular("a"), link("b", "/etc/passwd"))
        tar_with(tree / "docs" / "внутрь.tar", regular("dir/a"), link("dir/b", "a"))

        assert execute(Unpack(access, StandardArchiver(), LIMIT, 100), {"archive": "ссылка-вовне.tar"}).error == "archive_unsafe"
        assert execute(Unpack(access, StandardArchiver(), LIMIT, 100), {"archive": "внутрь.tar"}).ok
        assert (tree / "docs" / "внутрь" / "dir" / "b").is_symlink()

    def test_bomb_is_refused_by_declared_size(self, access: FileAccess, tree: Path) -> None:
        tar_with(tree / "docs" / "бомба.tar", regular("big", 5000))

        assert execute(Unpack(access, StandardArchiver(), 4096, 100), {"archive": "бомба.tar"}).error == "archive_too_big"

    def test_secrets_inside_are_skipped(self, access: FileAccess, tree: Path) -> None:
        zip_with(tree / "docs" / "проект.zip", {"src/main.py": "print()", ".env": "SECRET=1", "repo/.git/config": "[x]"})

        result = execute(Unpack(access, StandardArchiver(), LIMIT, 100), {"archive": "проект.zip"})

        assert result.data["skipped_count"] == 2
        assert (tree / "docs" / "проект" / "src" / "main.py").exists() and not (tree / "docs" / "проект" / ".env").exists()

    def test_existing_folder_and_unknown_format(self, access: FileAccess, tree: Path) -> None:
        zip_with(tree / "docs" / "Obsidian.zip", {"a": "1"})
        (tree / "docs" / "архив.rar").write_bytes(b"Rar!")

        assert execute(Unpack(access, StandardArchiver(), LIMIT, 100), {"archive": "Obsidian.zip"}).error == "already_exists"
        assert execute(Unpack(access, StandardArchiver(), LIMIT, 100), {"archive": "архив.rar"}).error == "unknown_format"

    def test_broken_archive(self, access: FileAccess, tree: Path) -> None:
        (tree / "docs" / "битый.zip").write_bytes(b"not an archive")

        assert execute(Unpack(access, StandardArchiver(), LIMIT, 100), {"archive": "битый.zip"}).error == "broken_archive"


class TestLinksToSkipped:
    """Ссылка на пропущенное (`.env`) пропускается вместе с ним: иначе `tarfile` достал бы содержимое `.env`
    под разрешённым именем (ревью 02.11.2026, П3a №5)."""

    def test_hard_link_to_a_secret_is_skipped(self, access: FileAccess, tree: Path) -> None:
        hard = regular("visible.txt", 0)
        hard.type, hard.linkname = tarfile.LNKTYPE, ".env"
        tar_with(tree / "docs" / "a.tar", regular(".env", 8), hard)

        result = unpack(access, archive="a.tar")

        assert result.ok and result.data["skipped"] == [".env", "visible.txt"]
        assert not (tree / "docs" / "a" / "visible.txt").exists()

    def test_symbolic_link_to_a_secret_is_skipped(self, access: FileAccess, tree: Path) -> None:
        tar_with(tree / "docs" / "a.tar", regular("inner/.env", 8), link("inner/visible.txt", ".env"))

        assert unpack(access, archive="a.tar").data["skipped"] == ["inner/.env", "inner/visible.txt"]

    def test_the_adapter_drops_a_hard_link_to_an_unchosen_member(self, tree: Path) -> None:
        hard = regular("visible.txt", 0)
        hard.type, hard.linkname = tarfile.LNKTYPE, "secret.txt"
        tar_with(tree / "a.tar", regular("secret.txt", 8), hard)

        StandardArchiver().unpack(tree / "a.tar", tree / "out", ["visible.txt"])

        assert list((tree / "out").iterdir()) == []


class TestLinkChains:
    """Ревью 07.11.2026, №1: `three → two → one → .env` — отброшено было только `two`, а `tarfile`, не найдя `two`
    на диске, доставал по цепочке содержимое `.env` под именем `three`."""

    @staticmethod
    def hard(name: str, target: str) -> tarfile.TarInfo:
        info = regular(name, 0)
        info.type, info.linkname = tarfile.LNKTYPE, target
        return info

    def chain(self, path: Path) -> Path:
        return tar_with(path, regular(".env", 8), self.hard("one", ".env"), self.hard("two", "one"), self.hard("three", "two"))

    def test_the_adapter_drops_the_whole_chain(self, tree: Path) -> None:
        StandardArchiver().unpack(self.chain(tree / "a.tar"), tree / "out", ["two", "three"])

        assert list((tree / "out").iterdir()) == []

    def test_the_tool_unpacks_no_link_that_leads_to_a_secret(self, access: FileAccess, tree: Path) -> None:
        self.chain(tree / "docs" / "a.tar")

        assert unpack(access, archive="a.tar").ok
        assert list((tree / "docs" / "a").iterdir()) == []

    def test_a_chain_to_a_chosen_file_is_kept(self, tree: Path) -> None:
        tar_with(tree / "a.tar", regular("data.txt", 3), self.hard("one", "data.txt"), self.hard("two", "one"))

        StandardArchiver().unpack(tree / "a.tar", tree / "out", ["data.txt", "one", "two"])

        assert sorted(item.name for item in (tree / "out").iterdir()) == ["data.txt", "one", "two"]


class TestDownloads:
    def test_out_of_downloads_into_own_folders_waits_for_yes(
        self, make_access: MakeAccess, store: Confirmations, tree: Path
    ) -> None:
        zip_with(tree / "downloads" / "вложение.zip", {"a.txt": "1"})
        request = {"archive": str(tree / "downloads" / "вложение.zip"), "target": "из почты"}

        asked = execute(Unpack(make_access(), StandardArchiver(), LIMIT, 100), request)
        gate = ConfirmationGate(store, "run-2")
        done = say_yes(gate, Unpack(make_access(gate=gate), StandardArchiver(), LIMIT, 100))

        assert asked.error == "needs_confirm" and done.ok and (tree / "docs" / "из почты" / "a.txt").exists()

    def test_inside_downloads_no_question(self, access: FileAccess, tree: Path) -> None:
        zip_with(tree / "downloads" / "вложение.zip", {"a.txt": "1"})

        assert execute(Unpack(access, StandardArchiver(), LIMIT, 100), {"archive": str(tree / "downloads" / "вложение.zip")}).ok


class TestPack:
    @pytest.mark.parametrize("suffix", [".zip", ".tar", ".tar.gz", ".tar.bz2", ".tar.xz", ".tar.zst"])
    def test_round_trip_without_secrets(self, access: FileAccess, tree: Path, suffix: str) -> None:
        (tree / "docs" / "project" / "main.py").write_text("print()")

        packed = execute(Pack(access, StandardArchiver(), 100), {"sources": ["project", "Obsidian/План.md"], "archive": f"out{suffix}"})
        names = {member.name for member in StandardArchiver().members(tree / "docs" / f"out{suffix}")}

        assert packed.ok and "project/main.py" in names and "План.md" in names
        assert not any(".env" in name or ".git" in name for name in names)
        assert execute(Unpack(access, StandardArchiver(), LIMIT, 100), {"archive": f"out{suffix}"}).ok

    def test_never_overwrites_and_needs_a_known_ending(self, access: FileAccess) -> None:
        assert execute(Pack(access, StandardArchiver(), 100), {"sources": ["Obsidian"], "archive": "Отчёт март.pdf"}).error == "unknown_format"
        assert execute(Pack(access, StandardArchiver(), 100), {"sources": ["Obsidian"], "archive": "a.zip"}).ok
        assert execute(Pack(access, StandardArchiver(), 100), {"sources": ["Obsidian"], "archive": "a.zip"}).error == "already_exists"


    def test_a_file_that_appeared_meanwhile_is_not_deleted(self, tree: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Чужой файл с тем же именем появился после проверки «нет такого» — отказ, и файл цел (П3a №14)."""
        archive = tree / "docs" / "a.zip"
        archive.write_text("чужое")
        monkeypatch.setattr(Path, "exists", lambda self: False if self == archive else Path.is_dir(self) or Path.is_file(self))

        with pytest.raises(AlreadyExists):
            StandardArchiver().pack(archive, [(tree / "docs" / "Obsidian" / "План.md", "План.md")], ArchiveFormat.ZIP)

    def test_a_failed_write_does_not_delete_a_file_put_in_its_place(self, tree: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Ревью 07.11.2026, №4: имя занято, а другой процесс подменил путь — сбой записи удалял его файл."""
        archive, foreign = tree / "docs" / "a.zip", tree / "docs" / "чужой.zip"
        foreign.write_text("чужое")

        def replaced_then_failed(*_: object) -> None:
            foreign.replace(archive)
            raise OSError("диск полон")

        monkeypatch.setattr(StandardArchiver, "_write", replaced_then_failed)
        with pytest.raises(OSError, match="диск полон"):
            StandardArchiver().pack(archive, [(tree / "docs" / "Obsidian" / "План.md", "План.md")], ArchiveFormat.ZIP)

        assert archive.read_text() == "чужое"

    def test_the_archive_is_written_into_the_name_it_took(self, tree: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Подмена пути после `O_EXCL` не направит запись в чужой файл: пишется в уже открытый."""
        archive, foreign = tree / "docs" / "a.tar", tree / "docs" / "чужой.tar"
        foreign.write_text("чужое")
        taken = StandardArchiver._new_tar  # pyright: ignore[reportPrivateUsage]

        def swapped(stream: object, format: ArchiveFormat) -> tarfile.TarFile:
            foreign.replace(archive)
            return taken(stream, format)  # pyright: ignore[reportArgumentType]

        monkeypatch.setattr(StandardArchiver, "_new_tar", staticmethod(swapped))
        StandardArchiver().pack(archive, [(tree / "docs" / "Obsidian" / "План.md", "План.md")], ArchiveFormat.TAR)

        assert archive.read_text() == "чужое"

        assert archive.read_text() == "чужое"


class TestDryRun:
    def test_nothing_appears(self, access: FileAccess, tree: Path) -> None:
        zip_with(tree / "docs" / "фото.zip", {"a.txt": "1"})
        archiver = DryRunArchiver(StandardArchiver())

        assert execute(Unpack(access, archiver, LIMIT, 100), {"archive": "фото.zip"}).ok
        assert execute(Pack(access, archiver, 100), {"sources": ["Obsidian"], "archive": "a.zip"}).ok
        assert not (tree / "docs" / "фото").exists() and not (tree / "docs" / "a.zip").exists()
