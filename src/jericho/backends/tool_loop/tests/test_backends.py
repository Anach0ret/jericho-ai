import pytest

from jericho.backends.anthropic_api.backend import AnthropicApi
from jericho.backends.openai_api.backend import OpenAiApi
from jericho.backends.tool_loop.loop import ToolLoop
from jericho.backends.tool_loop.testing import Open
from jericho.core.backends.config import BackendError, BackendLoader, BackendServices
from jericho.core.conf.settings import AgentSettings, Settings
from jericho.core.tools.dispatcher import ToolDispatcher


def services(backend: str, tools: tuple[Open, ...] = ()) -> BackendServices:
    settings = Settings(agent=AgentSettings(backend=backend))
    return BackendServices(settings, tools, ToolDispatcher(), {}, ("python", "-m", "jericho"), {})


@pytest.mark.parametrize(("package", "expected"), [("jericho.backends.anthropic_api", AnthropicApi), ("jericho.backends.openai_api", OpenAiApi)])
def test_backend_by_key_is_one_line_of_the_settings_and_needs_no_key_to_assemble(package: str, expected: type) -> None:
    backend = BackendLoader().load(package)
    backend.ready(services(package, (Open(),)))

    assert isinstance(backend, expected) and isinstance(backend.backend(), ToolLoop) and backend.commands() == ()


def test_tool_named_like_the_final_answer_stops_the_assembly() -> None:
    class Reply(Open):
        name = "reply"

    with pytest.raises(BackendError, match="reserved"):
        BackendLoader().load("jericho.backends.anthropic_api").ready(services("jericho.backends.anthropic_api", (Reply(),)))
