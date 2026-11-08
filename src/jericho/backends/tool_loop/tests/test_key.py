from pathlib import Path

import pytest

from jericho.backends.tool_loop.key import EnvironmentKey
from jericho.core.agent.protocols import AgentBackendError


class TestEnvironmentKey:
    def test_variable_comes_first(self, tmp_path: Path) -> None:
        (tmp_path / "gemini_key").write_text("из файла\n", encoding="utf-8")

        assert EnvironmentKey("GEMINI_API_KEY", {"GEMINI_API_KEY": "из окружения"}, tmp_path / "gemini_key").value() == "из окружения"

    def test_file_when_the_desktop_gave_no_variable(self, tmp_path: Path) -> None:
        (tmp_path / "gemini_key").write_text("из файла\n", encoding="utf-8")

        assert EnvironmentKey("GEMINI_API_KEY", {}, tmp_path / "gemini_key").value() == "из файла"

    def test_neither_is_named_and_where_to_put_it(self, tmp_path: Path) -> None:
        with pytest.raises(AgentBackendError, match="GEMINI_API_KEY or the file .*gemini_key"):
            EnvironmentKey("GEMINI_API_KEY", {}, tmp_path / "gemini_key").value()

    def test_no_key_needed_when_nothing_is_named(self) -> None:
        assert EnvironmentKey("", {}).value() == ""
