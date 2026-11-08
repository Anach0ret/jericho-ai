import io
import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar, cast

import pytest

from jericho.core import ForeignText
from jericho.core.modules.config import ModuleServices
from jericho.core.testing import execute
from jericho.modules.search import module as search_module
from jericho.modules.search.adapters.brave import BraveSearch
from jericho.modules.search.adapters.offline import OfflineSearch
from jericho.modules.search.adapters.tavily import TavilySearch
from jericho.modules.search.key import SearchKey
from jericho.modules.search.module import SearchModule
from jericho.modules.search.settings import SearchSettings
from jericho.modules.search.tool import WebSearch

ANSWER = {
    "web": {
        "results": [
            {"title": "Atlético <strong>lineup</strong>", "url": "https://example.org/a", "description": "Oblak &amp; Co", "age": "2 hours ago"},
            {"title": "Second", "url": "https://example.org/b", "description": "без даты"},
        ]
    }
}


class Network:
    """Подмена сети: запоминает запрос, отвечает заданным телом или ошибкой HTTP."""

    def __init__(self, body: object = ANSWER, status: int = 200) -> None:
        self.requests: list[urllib.request.Request] = []
        self._body = body
        self._status = status

    def __call__(self, request: urllib.request.Request, timeout: float) -> bytes:
        self.requests.append(request)
        if self._status != 200:
            raise urllib.error.HTTPError(request.full_url, self._status, "error", {}, io.BytesIO())  # pyright: ignore[reportArgumentType]
        return json.dumps(self._body).encode()

    def parameters(self) -> dict[str, list[str]]:
        return urllib.parse.parse_qs(urllib.parse.urlparse(self.requests[0].full_url).query)


def engine(network: Network, environment: dict[str, str] | None = None, file: Path | None = None) -> BraveSearch:
    key = SearchKey("BRAVE_SEARCH_API_KEY", file, {"BRAVE_SEARCH_API_KEY": "secret"} if environment is None else environment)
    return BraveSearch(key, country="DE", fetch=network)


class TestWebSearch:
    def test_plain_snippets_with_links(self) -> None:
        result = execute(WebSearch(engine(Network()), ForeignText()), {"query": "atletico lineup"})

        assert result.data["results"] == [
            {"title": "Atlético lineup", "url": "https://example.org/a", "snippet": "Oblak & Co", "age": "2 hours ago"},
            {"title": "Second", "url": "https://example.org/b", "snippet": "без даты"},
        ]

    def test_request_carries_key_freshness_and_country(self) -> None:
        network = Network()

        execute(WebSearch(engine(network), ForeignText()), {"query": "news", "count": 3, "freshness": "day"})

        assert network.requests[0].get_header("X-subscription-token") == "secret"
        assert {name: value[0] for name, value in network.parameters().items()} == {
            "q": "news", "count": "3", "safesearch": "moderate", "freshness": "pd", "country": "DE",
        }

    def test_found_text_is_foreign_nothing_found_is_not(self) -> None:
        found, empty = ForeignText(), ForeignText()

        execute(WebSearch(engine(Network()), found), {"query": "x y"})
        execute(WebSearch(engine(Network({"web": {"results": []}})), empty), {"query": "x y"})

        assert found.sources == {"web_search"} and empty.sources == frozenset()

    @pytest.mark.parametrize(("status", "error"), [(401, "search_not_configured"), (429, "search_limit"), (500, "search_failed")])
    def test_http_errors(self, status: int, error: str) -> None:
        assert execute(WebSearch(engine(Network(status=status)), ForeignText()), {"query": "x y"}).error == error


class TestKey:
    def test_without_a_key_it_says_so_and_sends_nothing(self) -> None:
        network = Network()

        result = execute(WebSearch(engine(network, environment={}), ForeignText()), {"query": "x y"})

        assert result.error == "search_not_configured" and network.requests == []

    def test_file_when_no_variable(self, tmp_path: Path) -> None:
        file = tmp_path / "key"
        file.write_text("from-file\n", encoding="utf-8")
        network = Network()

        execute(WebSearch(engine(network, environment={}, file=file), ForeignText()), {"query": "x y"})

        assert network.requests[0].get_header("X-subscription-token") == "from-file"


class TestTavily:
    ANSWER: ClassVar[dict[str, object]] = {"results": [{"title": "Погода", "url": "https://example.org/w", "content": "x" * 900, "published_date": "Sat, 17 Oct 2026"}]}

    def test_post_with_bearer_key_and_time_range(self) -> None:
        network = Network(self.ANSWER)
        key = SearchKey("TAVILY_API_KEY", None, {"TAVILY_API_KEY": "tvly-secret"})

        result = execute(WebSearch(TavilySearch(key, fetch=network), ForeignText()), {"query": "weather berlin", "freshness": "day"})

        request = network.requests[0]
        assert request.get_header("Authorization") == "Bearer tvly-secret" and request.get_method() == "POST"
        assert json.loads(cast(bytes, request.data)) == {"query": "weather berlin", "max_results": 5, "search_depth": "basic", "time_range": "day"}
        hit = cast(list[dict[str, str]], result.data["results"])[0]
        assert hit["age"] == "Sat, 17 Oct 2026" and len(hit["snippet"]) == 601

    @pytest.mark.parametrize(("status", "error"), [(401, "search_not_configured"), (432, "search_limit")])
    def test_http_errors(self, status: int, error: str) -> None:
        key = SearchKey("TAVILY_API_KEY", None, {"TAVILY_API_KEY": "k"})

        assert execute(WebSearch(TavilySearch(key, fetch=Network(status=status)), ForeignText()), {"query": "x y"}).error == error


class TestOffline:
    def test_no_network_and_still_foreign(self) -> None:
        foreign = ForeignText()

        result = execute(WebSearch(OfflineSearch(), foreign), {"query": "погода берлин"})

        assert cast(list[dict[str, str]], result.data["results"])[0]["title"] == "Поиск вхолостую: погода берлин"
        assert foreign.sources == {"web_search"}


class TestKeyFile:
    """Файл ключа по умолчанию — в папке файлов машины своего проекта, а не чужого: ту папку ручки `files` не трогают."""

    def files(self, monkeypatch: pytest.MonkeyPatch, settings: SearchSettings, config_dir: Path) -> list[Path | None]:
        seen: list[Path | None] = []

        def recorded(variable: str, file: Path | None, environment: object) -> SearchKey:
            seen.append(file)
            return SearchKey(variable, file, {})

        monkeypatch.setattr(search_module, "SearchKey", recorded)
        module = SearchModule()
        own = SimpleNamespace(section=lambda name, section_class: settings)
        services = SimpleNamespace(settings=own, core=SimpleNamespace(dry_run=False), program=SimpleNamespace(config_dir=config_dir))
        module.ready(cast(ModuleServices, services))
        module.engine()
        return seen

    def test_default_lies_in_the_project_machine_folder(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        assert self.files(monkeypatch, SearchSettings(), tmp_path / "server") == [tmp_path / "server" / "search_key"]

    def test_named_file_wins(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        named = tmp_path / "keys" / "tavily"

        assert self.files(monkeypatch, SearchSettings(api_key_file=named), tmp_path / "server") == [named]


class TestDryRun:
    def test_dry_run_searches_offline_whatever_the_provider(self, tmp_path: Path) -> None:
        """П3b №4: `dry_run=True` с унаследованным `tavily` и ключом отправлял настоящий запрос."""
        module = SearchModule()
        own = SimpleNamespace(section=lambda name, section_class: SearchSettings(provider="tavily"))
        core = SimpleNamespace(dry_run=True)
        module.ready(cast(ModuleServices, SimpleNamespace(settings=own, core=core, program=SimpleNamespace(config_dir=tmp_path))))

        assert isinstance(module.engine(), OfflineSearch)
