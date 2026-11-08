from collections.abc import Sequence
from pathlib import Path

import pytest

from jericho.core import CommandError
from jericho.core.testing import execute
from jericho.modules.files.access import FileAccess
from jericho.modules.files.adapters.opener import CommandOpener
from jericho.modules.files.tools.open import OpenFile


class Opened:
    """Подмена «двойного щелчка»: запоминает, что открыли."""

    def __init__(self) -> None:
        self.paths: list[Path] = []

    def open(self, path: Path) -> None:
        self.paths.append(path)


class Runner:
    def __init__(self, fails: bool = False) -> None:
        self.launched: list[list[str]] = []
        self._fails = fails

    def run(self, command: Sequence[str], stdin: str | None = None, *, reads: bool = False, dry_answer: str = "") -> str:
        raise AssertionError("open must not wait")

    def launch(self, command: Sequence[str]) -> None:
        if self._fails:
            raise CommandError("gio: нет программы для этого вида")
        self.launched.append(list(command))


@pytest.fixture
def opened() -> Opened:
    return Opened()


class TestOpenFile:
    @pytest.mark.parametrize("path", ["Obsidian/План.md", "Отчёт март.pdf", "Obsidian"])
    def test_documents_and_folders_open(self, access: FileAccess, opened: Opened, tree: Path, path: str) -> None:
        assert execute(OpenFile(access, opened), {"path": path}).ok
        assert opened.paths == [tree / "docs" / path]

    @pytest.mark.parametrize("name", ["start.sh", "app.desktop", "tool.AppImage", "setup.exe", "run.py"])
    def test_launchers_are_never_run(self, access: FileAccess, opened: Opened, tree: Path, name: str) -> None:
        (tree / "docs" / name).write_text("#!/bin/sh\nrm -rf ~\n", encoding="utf-8")

        assert execute(OpenFile(access, opened), {"path": name}).error == "not_openable"
        assert opened.paths == []

    def test_executable_bit_wins_over_a_harmless_ending(self, access: FileAccess, opened: Opened, tree: Path) -> None:
        script = tree / "docs" / "notes.txt"
        script.write_text("#!/bin/sh\n", encoding="utf-8")
        script.chmod(0o755)

        assert execute(OpenFile(access, opened), {"path": "notes.txt"}).error == "not_openable"

    def test_unknown_type_is_not_opened(self, access: FileAccess, opened: Opened, tree: Path) -> None:
        (tree / "docs" / "без-окончания").write_text("?", encoding="utf-8")

        assert execute(OpenFile(access, opened), {"path": "без-окончания"}).error == "unknown_type"

    def test_page_from_downloads_waits_for_yes(self, access: FileAccess, opened: Opened, tree: Path) -> None:
        (tree / "downloads" / "счёт.html").write_text("<script>…</script>", encoding="utf-8")
        (tree / "docs" / "своя.html").write_text("<p>моя</p>", encoding="utf-8")

        assert execute(OpenFile(access, opened), {"path": str(tree / "downloads" / "счёт.html")}).error == "needs_confirm"
        assert execute(OpenFile(access, opened), {"path": "своя.html"}).ok
        assert execute(OpenFile(access, opened), {"path": str(tree / "downloads" / "письмо.txt")}).ok

    def test_secrets_and_outside_are_refused(self, access: FileAccess, opened: Opened) -> None:
        assert execute(OpenFile(access, opened), {"path": "project/.env"}).error == "forbidden_path"
        assert execute(OpenFile(access, opened), {"path": "/etc/passwd"}).error == "outside_roots"


class TestCommandOpener:
    def test_launches_without_waiting(self, tree: Path) -> None:
        runner = Runner()

        CommandOpener(runner, ("gio", "open")).open(tree / "docs")

        assert runner.launched == [["gio", "open", str(tree / "docs")]]

    def test_failure_is_a_refusal(self, access: FileAccess, tree: Path) -> None:
        tool = OpenFile(access, CommandOpener(Runner(fails=True), ("gio", "open")))

        assert execute(tool, {"path": "Obsidian/План.md"}).error == "open_failed"
