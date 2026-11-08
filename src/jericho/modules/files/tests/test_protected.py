from pathlib import Path

import pytest

from jericho.core import ConfirmationGate
from jericho.core.services.own_paths import OwnPaths
from jericho.core.services.paths import Paths
from jericho.core.testing import execute
from jericho.core.testing.fakes import Confirmations, say_yes
from jericho.modules.files.access import FileAccess
from jericho.modules.files.adapters.archives import StandardArchiver
from jericho.modules.files.adapters.trash import DirectoryTrash
from jericho.modules.files.entities import Root, shown
from jericho.modules.files.tests.conftest import MakeAccess, names
from jericho.modules.files.tools.archive import Pack
from jericho.modules.files.tools.change import CreateFile, EditFile
from jericho.modules.files.tools.delete import Delete
from jericho.modules.files.tools.read import ListDir, ReadFile
from jericho.modules.files.tools.transfer import Copy, Move


@pytest.fixture
def own(tree: Path, make_access: MakeAccess) -> FileAccess:
    """Внутри корня — код ассистента (`project/assistant`) с его настройками."""
    code = tree / "docs" / "project" / "assistant"
    code.mkdir()
    (code / "settings.py").write_text("roots = ['~/Документы']\n", encoding="utf-8")
    return make_access(protected=[code])


class TestProtected:
    def test_own_files_are_neither_read_nor_changed(self, own: FileAccess) -> None:
        settings = "project/assistant/settings.py"

        assert execute(ReadFile(own, 4096, 10**6), {"path": settings}).error == "protected_path"
        assert execute(EditFile(own, 10**6), {"path": settings, "old": "~/Документы", "new": "/"}).error == "protected_path"
        assert execute(CreateFile(own), {"path": "project/assistant/new.py"}).error == "protected_path"

    def test_the_folder_holding_them_is_not_moved_or_deleted(self, own: FileAccess, tree: Path) -> None:
        assert execute(Move(own), {"sources": ["project"], "target": "Obsidian"}).error == "protected_path"
        assert execute(Delete(own, DirectoryTrash(tree / "state" / "trash")), {"paths": ["project"]}).error == "protected_path"

    def test_but_it_is_still_an_ordinary_folder_for_everything_else(self, own: FileAccess, tree: Path) -> None:
        assert execute(Copy(own), {"sources": ["Obsidian/План.md"], "target": "project"}).ok
        assert names(execute(ListDir(own, 10), {"path": "project"}), "entries") == ["node_modules", "План.md"]


class TestWholeFolders:
    """Действие над папкой целиком не уносит и не убирает то, что внутри неё защищено (ревью 02.11.2026)."""

    @pytest.fixture
    def state(self, tree: Path) -> Path:
        """Состояние ассистента внутри корня: вопрос «да» и личные ответы."""
        runtime = tree / "docs" / "parent" / "runtime"
        runtime.mkdir(parents=True)
        (runtime / "private-replies.json").write_text("{}", encoding="utf-8")
        return runtime

    def test_copying_the_parent_of_own_files_is_refused(self, make_access: MakeAccess, state: Path, tree: Path) -> None:
        result = execute(Copy(make_access(protected=[state])), {"sources": ["parent"], "target": "copied"})

        assert result.error == "protected_path" and result.data["inside"] == shown(state)
        assert not (tree / "docs" / "copied").exists()

    def test_packing_the_parent_of_own_files_is_refused(self, make_access: MakeAccess, state: Path, tree: Path) -> None:
        result = execute(Pack(make_access(protected=[state]), StandardArchiver(), 100), {"sources": ["parent"], "archive": "a.zip"})

        assert result.error == "protected_path" and not (tree / "docs" / "a.zip").exists()

    def test_other_users_sessions_are_protected_too(self, make_access: MakeAccess, tree: Path) -> None:
        paths = Paths(tree / "docs" / "state", tree / "docs" / "run").for_user("alice")
        access = make_access(protected=[paths.state_dir, paths.all_sessions])

        assert execute(CreateFile(access), {"path": "run/users/bob/confirmation.json"}).error == "protected_path"

    def test_a_folder_holding_a_read_only_root_is_not_removed(self, make_access: MakeAccess, tree: Path) -> None:
        (tree / "docs" / "parent" / "archive").mkdir(parents=True)
        access = make_access(roots=[Root(tree / "docs"), Root(tree / "docs" / "parent" / "archive", read_only=True)])

        assert execute(Delete(access, DirectoryTrash(tree / "state" / "trash")), {"paths": ["parent"]}).error == "read_only_root"
        assert execute(Move(access), {"sources": ["parent"], "target": "elsewhere"}).error == "read_only_root"
        assert execute(Copy(access), {"sources": ["parent"], "target": "copied"}).ok      # копию взять можно

    def test_the_list_is_read_at_call_time(self, make_access: MakeAccess, tree: Path) -> None:
        """Модуль, собранный после модуля файлов (папка обмена inbox), защищает свою папку и так."""
        own = OwnPaths()
        access = make_access(protected=own)
        own.add(tree / "docs" / "Obsidian")

        assert execute(ReadFile(access, 4096, 10**6), {"path": "Obsidian/План.md"}).error == "protected_path"


class TestFromDownloads:
    """Файл из ненадёжного корня, положенный в доверенный, становится «своим» — только после «да», как у распаковки."""

    @pytest.mark.parametrize("tool", [Copy, Move])
    def test_transfer_into_own_folders_waits_for_yes(self, make_access: MakeAccess, store: Confirmations, tree: Path, tool: type[Copy]) -> None:
        request = {"sources": [str(tree / "downloads" / "письмо.txt")], "target": "письмо.txt"}

        asked = execute(tool(make_access()), request)
        gate = ConfirmationGate(store, "run-2")
        done = say_yes(gate, tool(make_access(gate=gate)))

        assert asked.error == "needs_confirm" and asked.data["untrusted"] == [shown(tree / "downloads" / "письмо.txt")]
        assert done.ok and (tree / "docs" / "письмо.txt").exists()

    def test_a_folder_holding_downloads_counts_as_downloads(self, make_access: MakeAccess, tree: Path) -> None:
        access = make_access(roots=[Root(tree), Root(tree / "downloads", untrusted=True)])

        assert execute(Copy(access), {"sources": ["downloads"], "target": "docs/загрузки"}).error == "needs_confirm"

    def test_pack_into_own_folders_waits_for_yes(self, access: FileAccess, tree: Path) -> None:
        result = execute(Pack(access, StandardArchiver(), 100), {"sources": [str(tree / "downloads")], "archive": "почта.zip"})

        assert result.error == "needs_confirm" and not (tree / "docs" / "почта.zip").exists()

    def test_inside_downloads_no_question(self, access: FileAccess, tree: Path) -> None:
        result = execute(Copy(access), {"sources": [str(tree / "downloads" / "письмо.txt")], "target": str(tree / "downloads" / "копия.txt")})

        assert result.ok
