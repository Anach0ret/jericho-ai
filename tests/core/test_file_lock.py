"""Номер держателя замка — в соседнем файле: на Windows занятый замок другим процессам не прочитать."""

import os
import stat
import sys
from pathlib import Path

import pytest

from jericho.core.services.adapters.file_lock import FileLock


class TestHolder:
    def test_holder_number_lies_next_to_the_lock(self, tmp_path: Path) -> None:
        lock = FileLock(tmp_path / "phrase.lock")
        assert lock.acquire()

        assert (tmp_path / "phrase.lock.pid").read_text(encoding="utf-8") == str(os.getpid())
        assert FileLock(tmp_path / "phrase.lock").holder() == os.getpid()

    def test_release_takes_the_number_away(self, tmp_path: Path) -> None:
        lock = FileLock(tmp_path / "phrase.lock")
        lock.acquire()
        lock.release()

        assert not (tmp_path / "phrase.lock.pid").exists()
        assert FileLock(tmp_path / "phrase.lock").holder() is None

    def test_number_left_by_a_crashed_holder_is_not_shown(self, tmp_path: Path) -> None:
        """Упавший держатель не убрал файл с номером, но замок свободен — останавливать некого."""
        (tmp_path / "phrase.lock").touch()
        (tmp_path / "phrase.lock.pid").write_text("999999", encoding="utf-8")

        assert FileLock(tmp_path / "phrase.lock").holder() is None

    def test_second_lock_in_the_same_process_waits(self, tmp_path: Path) -> None:
        first = FileLock(tmp_path / "phrase.lock")
        assert first.acquire()

        assert not FileLock(tmp_path / "phrase.lock").acquire()
        first.release()
        assert FileLock(tmp_path / "phrase.lock").acquire()


@pytest.mark.skipif(sys.platform == "win32", reason="права файла — POSIX; на Windows папку закрывает ACL профиля")
def test_number_file_is_private(tmp_path: Path) -> None:
    FileLock(tmp_path / "run" / "phrase.lock").acquire()

    assert stat.S_IMODE((tmp_path / "run" / "phrase.lock.pid").stat().st_mode) == 0o600
    assert stat.S_IMODE((tmp_path / "run").stat().st_mode) == 0o700
