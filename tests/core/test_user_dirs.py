"""Стандартные места ОС: на Linux — те же, что были (иначе проекты потеряли бы состояние), на macOS и Windows —
по их правилам, а явные переменные XDG главнее везде."""

from pathlib import Path

import platformdirs
import pytest

from jericho.core.assembly.installation import Installation
from jericho.core.services.paths import Paths, UserDirs

XDG = {"XDG_STATE_HOME": "/x/state", "XDG_RUNTIME_DIR": "/x/run", "XDG_CONFIG_HOME": "/x/config"}


class TestLinux:
    def test_defaults_are_the_xdg_ones(self, tmp_path: Path) -> None:
        dirs = UserDirs.find({}, tmp_path, system="linux")

        assert dirs == UserDirs(tmp_path / ".local/state", None, tmp_path / ".config")

    def test_paths_did_not_move(self, tmp_path: Path) -> None:
        """Как до 0.65: долгое — `~/.local/state/<имя>`, сеанс — `$XDG_RUNTIME_DIR/<имя>`, без него — `…/run`."""
        with_session = Paths.under("demo", UserDirs.find({"XDG_RUNTIME_DIR": "/run/user/1000"}, tmp_path, system="linux"))
        without = Paths.under("demo", UserDirs.find({}, tmp_path, system="linux"))

        assert (with_session.state_dir, with_session.runtime_dir) == (tmp_path / ".local/state/demo", Path("/run/user/1000/demo"))
        assert without.runtime_dir == tmp_path / ".local/state/demo/run"

    def test_empty_variable_counts_as_unset(self, tmp_path: Path) -> None:
        assert UserDirs.find({"XDG_STATE_HOME": ""}, tmp_path, system="linux").state == tmp_path / ".local/state"


@pytest.mark.parametrize("system", ["darwin", "win32"])
class TestNative:
    def test_defaults_follow_the_system(self, system: str, tmp_path: Path) -> None:
        dirs = UserDirs.find({}, tmp_path, system=system)

        assert dirs == UserDirs(
            Path(platformdirs.user_state_dir()), Path(platformdirs.user_runtime_dir()), Path(platformdirs.user_config_dir())
        )

    def test_xdg_variables_win(self, system: str, tmp_path: Path) -> None:
        assert UserDirs.find(XDG, tmp_path, system=system) == UserDirs(Path("/x/state"), Path("/x/run"), Path("/x/config"))


def test_machine_files_live_in_the_config_dir(tmp_path: Path) -> None:
    installation = Installation.discover(
        {"JERICHO_SETTINGS_MODULE": "acme.settings", "XDG_CONFIG_HOME": str(tmp_path / "config")}, tmp_path, "python"
    )

    assert installation.config_dir == tmp_path / "config" / "acme"
    assert installation.user_config_home == tmp_path / "config"
