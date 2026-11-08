import os
import sys
from pathlib import Path

import pytest

from jericho.core.checks.base import Project
from jericho.core.checks.permissions import FilesArePrivate
from jericho.core.services.adapters.file_lock import FileLock
from jericho.core.services.adapters.json_file import JsonStateFile
from jericho.core.skills.registry import InstalledSkills


def found(*dirs: Path, check: FilesArePrivate | None = None) -> list[str]:
    rule = check or FilesArePrivate(system="linux")
    return [message.text for message in rule.run(Project(Path("."), InstalledSkills([]), private_dirs=dirs))]


@pytest.mark.skipif(sys.platform == "win32", reason="биты chmod — договор POSIX; на Windows права — ACL")
class TestFilesArePrivate:
    def test_open_file_and_folder_are_found_with_the_fix(self, tmp_path: Path) -> None:
        root = tmp_path / "jericho"
        (root / "telegram").mkdir(parents=True, mode=0o755)
        os.chmod(root, 0o700)
        session = root / "telegram" / "home.session"
        session.write_text("ключ", encoding="utf-8")
        os.chmod(session, 0o644)

        problems = found(root)

        assert len(problems) == 2
        assert any("chmod 700" in text for text in problems) and any("chmod 600" in text and "home.session" in text for text in problems)

    def test_private_files_and_empty_locks_pass(self, tmp_path: Path) -> None:
        root = tmp_path / "state"
        root.mkdir(mode=0o700)
        os.chmod(root, 0o700)
        (root / "phrase.lock").write_text("", encoding="utf-8")
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


class TestOnWindows:
    """На Windows — не биты chmod, а место: папки в профиле пользователя его Windows закрывает от других учётных записей."""

    def test_folders_inside_the_profile_pass_whatever_their_mode(self, tmp_path: Path) -> None:
        root = tmp_path / "AppData" / "Local" / "jericho"
        root.mkdir(parents=True)
        (root / "journal.jsonl").write_text("{}", encoding="utf-8")

        assert found(root, check=FilesArePrivate(system="win32", home=tmp_path)) == []

    def test_folder_outside_the_profile_is_found_with_the_fix(self, tmp_path: Path) -> None:
        home, shared = tmp_path / "Users" / "anna", tmp_path / "Shared" / "jericho"
        home.mkdir(parents=True)
        shared.mkdir(parents=True)

        problems = found(shared, check=FilesArePrivate(system="win32", home=home))

        assert len(problems) == 1 and "вне профиля" in problems[0] and "XDG_" in problems[0]
