import os
from pathlib import Path

from jericho.core.checks.base import Project
from jericho.core.checks.permissions import FilesArePrivate
from jericho.core.services.adapters.file_lock import FileLock
from jericho.core.services.adapters.json_file import JsonStateFile
from jericho.core.skills.registry import InstalledSkills


def found(*dirs: Path) -> list[str]:
    return [message.text for message in FilesArePrivate().run(Project(Path("."), InstalledSkills([]), private_dirs=dirs))]


class TestFilesArePrivate:
    def test_open_file_and_folder_are_found_with_the_fix(self, tmp_path: Path) -> None:
        root = tmp_path / "jericho"
        (root / "telegram").mkdir(parents=True, mode=0o755)
        os.chmod(root, 0o700)
        session = root / "telegram" / "home.session"
        session.write_text("ключ")
        os.chmod(session, 0o644)

        problems = found(root)

        assert len(problems) == 2
        assert any("chmod 700" in text for text in problems) and any("chmod 600" in text and "home.session" in text for text in problems)

    def test_private_files_and_empty_locks_pass(self, tmp_path: Path) -> None:
        root = tmp_path / "state"
        root.mkdir(mode=0o700)
        os.chmod(root, 0o700)
        (root / "phrase.lock").write_text("")
        os.chmod(root / "phrase.lock", 0o664)

        assert found(root, tmp_path / "missing") == []

    def test_the_core_creates_its_files_private(self, tmp_path: Path) -> None:
        """Каркас сам создаёт папки 700 и файлы 600 — правилу остаётся созданное руками и чужими программами."""
        os.chmod(tmp_path, 0o700)
        JsonStateFile(tmp_path / "tasks" / "deferred.json").write({})
        lock = FileLock(tmp_path / "run" / "due.lock")
        lock.acquire()
        lock.release()

        assert found(tmp_path) == []
        assert (tmp_path / "run" / "due.lock").stat().st_mode & 0o077 == 0
