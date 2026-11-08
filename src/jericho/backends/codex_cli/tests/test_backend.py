from jericho.backends.codex_cli.backend import CodexCli
from jericho.backends.codex_cli.client import CodexCliBackend
from jericho.core.backends.config import BackendLoader, BackendServices
from jericho.core.conf.settings import AgentSettings, Settings
from jericho.core.tools.dispatcher import ToolDispatcher


class WithCodex(Settings):
    agent: AgentSettings = AgentSettings(backend="jericho.backends.codex_cli")


def test_backend_is_found_by_the_package_named_in_the_settings() -> None:
    backend = BackendLoader().load(WithCodex().agent.backend)
    backend.ready(BackendServices(WithCodex(), (), ToolDispatcher(), {}, ("/venv/python", "-m", "jericho"), {"JERICHO_RUN": "run-1"}))

    assert isinstance(backend, CodexCli) and isinstance(backend.backend(), CodexCliBackend)
    assert [command.name for command in backend.commands()] == ["mcp"]      # тот же сервер ручек, что у claude_cli
