from pathlib import Path

import pytest

from jericho.core import ConfirmationGate, ToolResult
from jericho.core.testing import execute
from jericho.core.testing.fakes import Confirmations, say_yes
from jericho.modules.files.access import FileAccess
from jericho.modules.files.adapters.dry_run import DryRunChanger, NoVersions
from jericho.modules.files.entities import Root
from jericho.modules.files.tests.conftest import MakeAccess
from jericho.modules.files.tools.change import CreateFile, EditFile, MakeDir, WriteFile
from jericho.modules.files.tools.read import ReadFile
from jericho.modules.files.tools.transfer import Copy, Move

PLAN = "Obsidian/План.md"


def text(tree: Path, relative: str) -> str:
    return (tree / "docs" / relative).read_text(encoding="utf-8")


def versions(tree: Path) -> list[Path]:
    return sorted(path for path in (tree / "state" / "versions").rglob("*") if path.is_file())


def read_downloads(access: FileAccess, tree: Path) -> None:
    """Модель прочитала скачанное письмо — дальше в этой фразе чужой текст."""
    assert execute(ReadFile(access, 4096, 10**6), {"path": str(tree / "downloads" / "письмо.txt")}).ok


def edit(access: FileAccess, **arguments: object) -> ToolResult:
    return execute(EditFile(access, 10**6), {"path": PLAN, **arguments})


class TestMakeDirAndCreateFile:
    def test_creates_parents(self, access: FileAccess, tree: Path) -> None:
        assert execute(CreateFile(access), {"path": "Новое/вложенное/заметка.md", "text": "привет"}).ok
        assert text(tree, "Новое/вложенное/заметка.md") == "привет"

    def test_never_overwrites(self, access: FileAccess, tree: Path) -> None:
        assert execute(CreateFile(access), {"path": PLAN, "text": "x"}).error == "already_exists"
        assert text(tree, PLAN).startswith("строка 1")

    def test_existing_folder_is_fine(self, access: FileAccess) -> None:
        assert execute(MakeDir(access), {"path": "Obsidian"}).data["existed"] is True
        assert execute(MakeDir(access), {"path": PLAN}).error == "already_exists"

    def test_not_in_forbidden_places(self, access: FileAccess) -> None:
        assert execute(CreateFile(access), {"path": "project/.git/hooks/post-checkout"}).error == "forbidden_path"


class TestEditFile:
    def test_replaces_exactly_one_piece_and_keeps_the_previous_version(self, access: FileAccess, tree: Path) -> None:
        result = edit(access, old="строка 2", new="вторая")

        assert result.ok and result.data["replaced"] == 1
        assert text(tree, PLAN) == "строка 1\nвторая\nстрока 3\n"
        assert [path.read_text(encoding="utf-8") for path in versions(tree)] == ["строка 1\nстрока 2\nстрока 3\n"]

    def test_ambiguous_piece_needs_more_text_or_every(self, access: FileAccess, tree: Path) -> None:
        assert edit(access, old="строка", new="line").data["count"] == 3
        assert edit(access, old="строка", new="line", every=True).data["replaced"] == 3
        assert text(tree, PLAN) == "line 1\nline 2\nline 3\n"

    def test_missing_piece(self, access: FileAccess) -> None:
        assert edit(access, old="нет такого", new="x").error == "text_not_found"

    def test_not_utf8_is_not_edited(self, access: FileAccess, tree: Path) -> None:
        (tree / "docs" / "cp1251.txt").write_bytes("привет".encode("cp1251"))

        assert execute(EditFile(access, 10**6), {"path": "cp1251.txt", "old": "x", "new": "y"}).error == "not_utf8"

    def test_write_file_replaces_all_and_keeps_the_previous_version(self, access: FileAccess, tree: Path) -> None:
        assert execute(WriteFile(access), {"path": PLAN, "text": "новое"}).ok
        assert text(tree, PLAN) == "новое" and len(versions(tree)) == 1

    def test_write_file_does_not_create(self, access: FileAccess) -> None:
        assert execute(WriteFile(access), {"path": "нет.md", "text": "x"}).error == "not_found"


class TestForeignText:
    def test_after_reading_downloads_an_edit_waits_for_yes(self, make_access: MakeAccess, tree: Path) -> None:
        access = make_access()
        read_downloads(access, tree)

        assert edit(access, old="строка 2", new="x").error == "needs_confirm"
        assert text(tree, PLAN).startswith("строка 1\nстрока 2")

    def test_yes_in_the_next_phrase_does_it(self, make_access: MakeAccess, store: Confirmations, tree: Path) -> None:
        access = make_access()
        read_downloads(access, tree)
        edit(access, old="строка 2", new="x")
        gate = ConfirmationGate(store, "run-2")

        assert say_yes(gate, EditFile(make_access(gate=gate), 10**6)).ok
        assert "\nx\n" in text(tree, PLAN)


class TestTransfer:
    def test_copy_into_a_folder_keeps_names(self, access: FileAccess, tree: Path) -> None:
        result = execute(Copy(access), {"sources": [PLAN, "Отчёт март.pdf"], "target": "project"})

        assert result.ok and (tree / "docs" / "project" / "План.md").exists() and (tree / "docs" / PLAN).exists()

    def test_move_renames(self, access: FileAccess, tree: Path) -> None:
        assert execute(Move(access), {"sources": [PLAN], "target": "Obsidian/Plan.md"}).ok
        assert not (tree / "docs" / PLAN).exists() and text(tree, "Obsidian/Plan.md").startswith("строка 1")

    def test_overwrite_waits_for_yes_then_keeps_the_previous_version(
        self, make_access: MakeAccess, store: Confirmations, tree: Path
    ) -> None:
        (tree / "docs" / "project" / "План.md").write_text("старый план", encoding="utf-8")
        request = {"sources": [PLAN], "target": "project"}

        asked = execute(Copy(make_access()), request)
        gate = ConfirmationGate(store, "run-2")
        done = say_yes(gate, Copy(make_access(gate=gate)))

        assert asked.error == "needs_confirm" and asked.data["replaces"] == [str(tree / "docs" / "project" / "План.md")]
        assert done.ok and text(tree, "project/План.md").startswith("строка 1")
        assert [path.read_text(encoding="utf-8") for path in versions(tree)] == ["старый план"]

    @pytest.mark.parametrize(
        ("sources", "target", "error"),
        [
            (["Obsidian"], "Obsidian/внутри", "into_itself"),
            ([PLAN, "Отчёт март.pdf"], "новое-имя.md", "target_not_a_directory"),
            (["Obsidian"], "project/node_modules/..", "already_exists"),
            (["нет.md"], "project", "not_found"),
            ([PLAN], "../outside", "outside_roots"),
        ],
    )
    def test_refusals_before_anything_is_done(
        self, access: FileAccess, tree: Path, sources: list[str], target: str, error: str
    ) -> None:
        if error == "already_exists":
            (tree / "docs" / "project" / "Obsidian").mkdir()

        assert execute(Move(access), {"sources": sources, "target": target}).error == error
        assert (tree / "docs" / PLAN).exists()

    def test_moving_out_of_a_read_only_root_is_refused(self, make_access: MakeAccess, tree: Path) -> None:
        access = make_access(roots=[Root(tree / "docs"), Root(tree / "downloads", read_only=True)])

        assert execute(Move(access), {"sources": [str(tree / "downloads" / "письмо.txt")], "target": "."}).error == "read_only_root"
        assert execute(Copy(access), {"sources": [str(tree / "downloads" / "письмо.txt")], "target": "."}).ok


class TestDryRun:
    def test_nothing_changes_on_disk(self, make_access: MakeAccess, tree: Path) -> None:
        access = make_access(changer=DryRunChanger(), versions=NoVersions())

        assert edit(access, old="строка 2", new="x").ok
        assert execute(CreateFile(access), {"path": "новое.md"}).ok
        assert execute(Move(access), {"sources": [PLAN], "target": "project"}).ok

        assert text(tree, PLAN) == "строка 1\nстрока 2\nстрока 3\n"
        assert not (tree / "docs" / "новое.md").exists() and not (tree / "state").exists()
