import stat
from pathlib import Path

from jericho.core import ConfirmationGate, ToolResult
from jericho.core.testing import execute
from jericho.core.testing.fakes import Confirmations, say_yes
from jericho.modules.files.adapters.dry_run import DryRunTrash
from jericho.modules.files.adapters.trash import DirectoryTrash
from jericho.modules.files.tests.conftest import MakeAccess
from jericho.modules.files.tools.delete import Delete

PLAN = "Obsidian/План.md"
REQUEST = {"paths": [PLAN, "Отчёт март.pdf"]}


def trash(tree: Path) -> DirectoryTrash:
    return DirectoryTrash(tree / "state" / "trash")


def in_trash(tree: Path) -> list[str]:
    return sorted(path.name for path in (tree / "state" / "trash").rglob("*") if path.is_file())


def ask_then_yes(make_access: MakeAccess, store: Confirmations, tree: Path) -> tuple[ToolResult, ToolResult]:
    asked = execute(Delete(make_access(), trash(tree)), REQUEST)
    gate = ConfirmationGate(store, "run-2")
    return asked, say_yes(gate, Delete(make_access(gate=gate), trash(tree)))


class TestDelete:
    def test_always_asks_first_and_names_what_goes(self, make_access: MakeAccess, tree: Path) -> None:
        result = execute(Delete(make_access(), trash(tree)), REQUEST)

        assert (result.error, result.data["count"]) == ("needs_confirm", 2)
        assert (tree / "docs" / PLAN).exists()

    def test_yes_in_the_next_phrase_moves_to_the_trash(self, make_access: MakeAccess, store: Confirmations, tree: Path) -> None:
        _, done = ask_then_yes(make_access, store, tree)

        assert done.ok and not (tree / "docs" / PLAN).exists()
        assert in_trash(tree) == ["Отчёт март.pdf", "План.md"]

    def test_yes_does_not_cover_a_file_changed_after_the_question(
        self, make_access: MakeAccess, store: Confirmations, tree: Path
    ) -> None:
        execute(Delete(make_access(), trash(tree)), REQUEST)
        (tree / "docs" / PLAN).write_text("дописали после вопроса", encoding="utf-8")
        gate = ConfirmationGate(store, "run-2")

        result = say_yes(gate, Delete(make_access(gate=gate), trash(tree)))

        assert not result.ok and (tree / "docs" / PLAN).exists()

    def test_yes_does_not_cover_a_folder_changed_deep_inside(self, make_access: MakeAccess, store: Confirmations, tree: Path) -> None:
        """Время папки меняют только её прямые записи — поэтому согласие на папку помнит и всё под ней (П3a №12)."""
        request = {"paths": ["project"]}
        execute(Delete(make_access(), trash(tree)), request)
        (tree / "docs" / "project" / "node_modules" / "lib" / "новое.md").write_text("появилось после вопроса")
        gate = ConfirmationGate(store, "run-2")

        result = say_yes(gate, Delete(make_access(gate=gate), trash(tree)))

        assert not result.ok and (tree / "docs" / "project").exists()

    def test_what_goes_to_the_own_trash_is_owner_only(self, make_access: MakeAccess, store: Confirmations, tree: Path) -> None:
        """Своя корзина — в состоянии ассистента: E015 после удаления проходит (П3a №13)."""
        (tree / "docs" / PLAN).chmod(0o755)
        ask_then_yes(make_access, store, tree)

        modes = {path.name: stat.S_IMODE(path.stat().st_mode) for path in (tree / "state" / "trash").rglob("*")}

        assert all(mode & 0o077 == 0 for mode in modes.values()) and modes["План.md"] == 0o700

    def test_a_root_is_never_deleted_whole(self, make_access: MakeAccess, tree: Path) -> None:
        assert execute(Delete(make_access(), trash(tree)), {"paths": ["."]}).error == "root_itself"

    def test_forbidden_and_outside_are_refused_before_asking(self, make_access: MakeAccess, store: Confirmations, tree: Path) -> None:
        assert execute(Delete(make_access(), trash(tree)), {"paths": [PLAN, "project/.git"]}).error == "forbidden_path"
        assert execute(Delete(make_access(), trash(tree)), {"paths": ["наружу/чужое.txt"]}).error == "outside_roots"
        assert store.pending() is None

    def test_dry_run_keeps_everything(self, make_access: MakeAccess, store: Confirmations, tree: Path) -> None:
        execute(Delete(make_access(), DryRunTrash()), REQUEST)
        gate = ConfirmationGate(store, "run-2")

        assert say_yes(gate, Delete(make_access(gate=gate), DryRunTrash())).ok
        assert (tree / "docs" / PLAN).exists() and (tree / "docs" / "Отчёт март.pdf").exists()
