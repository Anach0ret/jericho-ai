import pytest

from jericho.backends.claude_cli.backend import ClaudeCli
from jericho.backends.claude_cli.client import ClaudeCliBackend
from jericho.core.agent.protocols import AgentBackendError
from jericho.core.backends.config import BackendError, BackendLoader, BackendServices, NoBackend
from jericho.core.conf.settings import AgentSettings, Settings
from jericho.core.tools.dispatcher import ToolDispatcher


class WithClaude(Settings):
    agent: AgentSettings = AgentSettings(backend="jericho.backends.claude_cli")


def services(settings: Settings) -> BackendServices:
    return BackendServices(settings, (), ToolDispatcher(), {}, ("/venv/python", "-m", "jericho"), {"JERICHO_RUN": "run-1"})


class TestBackendByName:
    def test_backend_is_found_by_the_package_named_in_the_settings(self) -> None:
        backend = BackendLoader().load(WithClaude().agent.backend)
        backend.ready(services(WithClaude()))

        assert isinstance(backend, ClaudeCli) and isinstance(backend.backend(), ClaudeCliBackend)
        assert [command.name for command in backend.commands()] == ["mcp"]      # сервер ручек — часть этого бэкенда

    def test_unknown_backend_is_named(self) -> None:
        with pytest.raises(BackendError, match="jericho.backends.nothing.backend: module not found"):
            BackendLoader().load("jericho.backends.nothing")

    def test_assistant_without_a_backend_is_assembled_and_fails_only_when_asked(self) -> None:
        """Каркас без бэкенда собирается: ручки можно вызывать из терминала, а поручение получит сбой с подсказкой."""
        backend = BackendLoader().load(Settings().agent.backend)

        assert isinstance(backend, NoBackend) and backend.commands() == ()
        with pytest.raises(AgentBackendError, match="set agent.backend"):
            backend.backend().ask("ПРОМПТ", "открой")


def test_builtin_web_search_makes_the_whole_phrase_foreign() -> None:
    """Что нашёл встроенный поиск, каркас не видит — значит, фраза целиком считается прочитавшей чужое (ревью R06)."""
    from jericho.backends.claude_cli.settings import ClaudeSettings
    from jericho.core.services.foreign import ForeignText

    class WithSearch(Settings):
        agent: AgentSettings = AgentSettings(backend="jericho.backends.claude_cli")
        claude_cli: ClaudeSettings = ClaudeSettings(builtin_tools=("WebSearch",))

    foreign = ForeignText()
    services = BackendServices(WithSearch(), (), ToolDispatcher(), {}, ("python",), {}, foreign=foreign)

    BackendLoader().load(WithSearch().agent.backend).ready(services)

    assert foreign.sources == {"web_search"}
