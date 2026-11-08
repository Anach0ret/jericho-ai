import json
import logging
import sys
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from jericho.core.services.adapters.json_file import JsonStateFile

NOON = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)


def names(data: Any) -> list[str]:
    return [record["name"] for record in data]


@pytest.fixture(autouse=True)
def reports(caplog: pytest.LogCaptureFixture) -> Iterator[None]:
    """Записи берутся прямо у логгера хранилища: корневой их не видит, когда журнал Jericho уже настроен."""
    logger = logging.getLogger("jericho.core.services.adapters.json_file")
    logger.addHandler(caplog.handler)
    yield
    logger.removeHandler(caplog.handler)


def state_file(path: Path) -> JsonStateFile:
    return JsonStateFile(path, clock=lambda: NOON)


class TestJsonStateFile:
    def test_what_is_written_is_read_back(self, tmp_path: Path) -> None:
        file = state_file(tmp_path / "state" / "notes.json")

        file.write([{"name": "сайт курса"}])

        assert file.read(names, []) == ["сайт курса"]

    def test_missing_file_is_empty_and_nothing_is_reported(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        assert state_file(tmp_path / "notes.json").read(names, []) == []
        assert caplog.records == []

    @pytest.mark.skipif(sys.platform == "win32", reason="права 0600 — договор POSIX; на Windows — профиль пользователя (E015)")
    def test_file_is_private_and_no_temporary_file_is_left(self, tmp_path: Path) -> None:
        path = tmp_path / "notes.json"

        state_file(path).write([])

        assert path.stat().st_mode & 0o777 == 0o600
        assert [item.name for item in tmp_path.iterdir()] == ["notes.json"]

    def test_failed_write_leaves_the_previous_content(self, tmp_path: Path) -> None:
        """Запись идёт во временный файл: сбой посередине не оставляет половину файла."""
        path = tmp_path / "notes.json"
        file = state_file(path)
        file.write([{"name": "сайт курса"}])

        with pytest.raises(TypeError):
            file.write([{"name": object()}])

        assert file.read(names, []) == ["сайт курса"]
        assert [item.name for item in tmp_path.iterdir()] == ["notes.json"]

    @pytest.mark.parametrize("content", ["", "{не json", '{"name": "не список"}', '[{"title": "нет поля name"}]'])
    def test_file_that_cannot_be_understood_is_set_aside_and_reported(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture, content: str
    ) -> None:
        path = tmp_path / "notes.json"
        path.write_text(content, encoding="utf-8")

        assert state_file(path).read(names, []) == []

        aside = tmp_path / "notes.json.corrupt-20261013T120000"
        assert (path.exists(), aside.read_text(encoding="utf-8")) == (False, content)
        reported = {(record.getMessage(), record.__dict__["data"]["moved_to"]) for record in caplog.records}
        assert reported == {("state_file_corrupt", str(aside))}

    def test_removed_file_reads_as_empty(self, tmp_path: Path) -> None:
        file = state_file(tmp_path / "confirmation.json")
        file.write({"tool": "close_windows"})

        file.remove()
        file.remove()

        assert file.read(json.dumps, "") == ""
