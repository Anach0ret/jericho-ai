from datetime import UTC, datetime

from jericho.core import ForeignText, Tool, ToolRequest, ToolResult
from jericho.core.journal.entities import JournalEntry
from jericho.core.testing import execute
from jericho.core.tools.catalog import ToolCatalog
from jericho.modules.journal_reader.tool import ReadJournal


def entry(minute: int, event: str, level: str = "INFO", **details: object) -> JournalEntry:
    return JournalEntry(datetime(2026, 10, 11, 21, minute, tzinfo=UTC), event, level, "jericho", details)


ENTRIES = [
    entry(1, "voice", heard="открой перегрыз на третьем"),
    entry(2, "tool", tool="load_skill", params={"names": ["desktop"]}, result={"ok": True, "guides": {"desktop": "я" * 500}}),
    entry(3, "phrase", phrase="открой перегрыз на третьем", status="clarify", message="Что открыть на столе 3?"),
    entry(4, "tool", tool="open_app", params={"app": "фотошоп"}, result={"ok": False, "error": "app_not_found"}),
    entry(5, "phrase", phrase="открой фотошоп", status="refused", message="Фотошопа нет в списке"),
    entry(6, "voice", "ERROR", error="Capture socket not found"),
]


class Journal:
    def tail(self, limit: int) -> list[JournalEntry]:
        return ENTRIES[-limit:]


NOW = datetime(2026, 10, 11, 21, 10, tzinfo=UTC)


class _Service(Tool[ToolRequest]):
    """Служебная ручка с заданным именем — чтобы каталог знал, какие вызовы не считать делом."""

    request_type = ToolRequest
    service = True

    def __init__(self, name: str) -> None:
        self.name = name

    def _run(self, request: ToolRequest) -> ToolResult:
        return ToolResult.success()


SERVICE = ToolCatalog()
SERVICE.fill(_Service(name) for name in ("load_skill", "remember", "forget"))


def read(**arguments: object) -> list[dict[str, object]]:
    return execute(ReadJournal(Journal(), SERVICE, now=lambda: NOW), arguments).data["entries"]  # pyright: ignore[reportReturnType]


class TestReadJournal:
    def test_returns_the_latest_entries_from_old_to_new(self) -> None:
        entries = read(limit=2)

        assert [(item["time"], item["event"]) for item in entries] == [("11.10 21:05:00", "phrase"), ("11.10 21:06:00", "voice")]
        assert entries[0]["message"] == "Фотошопа нет в списке"

    def test_phrases_only(self) -> None:
        assert [item["phrase"] for item in read(kind="phrases")] == ["открой перегрыз на третьем", "открой фотошоп"]

    def test_tool_calls_only(self) -> None:
        assert [item["tool"] for item in read(kind="tools")] == ["load_skill", "open_app"]

    def test_errors_are_refused_calls_and_failures(self) -> None:
        assert [item["event"] for item in read(kind="errors")] == ["tool", "voice"]

    def test_long_text_is_cut(self) -> None:
        guide = read(kind="tools")[0]["result"]["guides"]["desktop"]  # pyright: ignore[reportIndexIssue]

        assert guide == "я" * 200 + "…"

    def test_calls_of_one_tool(self) -> None:
        assert [item["params"] for item in read(tool="open_app")] == [{"app": "фотошоп"}]

    def test_text_is_searched_in_phrases_parameters_and_answers(self) -> None:
        assert [item["event"] for item in read(contains="ФОТОШОП")] == ["tool", "phrase"]
        assert [item["event"] for item in read(contains="app_not_found")] == ["tool"]

    def test_filters_add_up(self) -> None:
        assert [item["event"] for item in read(contains="фотошоп", kind="phrases")] == ["phrase"]
        assert read(contains="фотошоп", tool="load_skill") == []

    def test_time_window_in_hours_or_from_a_moment(self) -> None:
        old = JournalEntry(datetime(2026, 10, 9, 12, 0, tzinfo=UTC), "phrase", details={"phrase": "давняя"})

        class Long:
            def tail(self, limit: int) -> list[JournalEntry]:
                return [old, *ENTRIES][-limit:]

        def phrases(**arguments: object) -> list[object]:
            found = execute(ReadJournal(Long(), now=lambda: NOW), {"kind": "phrases", **arguments}).data["entries"]
            return [item["phrase"] for item in found]  # pyright: ignore[reportGeneralTypeIssues, reportUnknownVariableType]

        assert phrases(hours=72)[0] == "давняя"
        assert "давняя" not in phrases(hours=24)
        assert phrases(since="2026-10-11 21:04") == ["открой фотошоп"]

    def test_answer_says_what_time_it_is_and_how_much_was_found(self) -> None:
        result = execute(ReadJournal(Journal(), now=lambda: NOW), {"limit": 2})

        assert (result.data["now"], result.data["found"], len(result.data["entries"])) == ("2026-10-11 21:10", 6, 2)  # pyright: ignore[reportArgumentType]

    def test_episodes_put_each_phrase_together_with_its_calls(self) -> None:
        """Так видно, что было названо и что после этого сработало; служебные вызовы эпизод не заслоняют."""
        episodes = read(kind="episodes")

        assert [(item["phrase"], item["calls"]) for item in episodes] == [
            ("открой перегрыз на третьем", []),
            ("открой фотошоп", [{"tool": "open_app", "params": {"app": "фотошоп"}, "error": "app_not_found"}]),
        ]

    def test_episodes_are_found_by_what_was_said_or_by_what_was_called(self) -> None:
        assert [item["phrase"] for item in read(kind="episodes", contains="перегрыз")] == ["открой перегрыз на третьем"]
        assert [item["phrase"] for item in read(kind="episodes", tool="open_app")] == ["открой фотошоп"]
        assert read(kind="episodes", tool="close_windows") == []

    def test_episode_is_joined_by_run_and_not_by_order(self) -> None:
        """Две фразы шли вперемешку, третий запуск оборвался без записи о фразе: чужие вызовы к эпизоду не липнут."""

        def of(run: str, minute: int, event: str, **details: object) -> JournalEntry:
            return JournalEntry(datetime(2026, 10, 13, 12, minute, tzinfo=UTC), event, run=run, details=details)

        class Mixed:
            def tail(self, limit: int) -> list[JournalEntry]:
                return [
                    of("lost", 1, "tool", tool="open_url", params={"url": "https://lost.example"}, result={"ok": True}),
                    of("a", 2, "tool", tool="open_app", params={"app": "zed"}, result={"ok": True}),
                    of("b", 3, "tool", tool="open_url", params={"url": "https://b.example"}, result={"ok": True}),
                    of("b", 4, "phrase", phrase="открой сайт", status="done", message="Открыл"),
                    of("a", 5, "phrase", phrase="открой иде", status="done", message="Открыл"),
                ]

        episodes = execute(ReadJournal(Mixed(), SERVICE, now=lambda: NOW), {"kind": "episodes"}).data["entries"]

        assert [(item["phrase"], [call["tool"] for call in item["calls"]]) for item in episodes] == [  # pyright: ignore[reportGeneralTypeIssues, reportUnknownVariableType]
            ("открой сайт", ["open_url"]),
            ("открой иде", ["open_app"]),
        ]

    def test_limit_is_bounded(self) -> None:
        assert execute(ReadJournal(Journal()), {"limit": 500}).error == "invalid_parameters"


class TestJournalIsForeignText:
    """В журнале — ответы ручек, а в них куски страниц: путь «страница → журнал → модель» не обходит учёт."""

    def test_entries_given_to_the_model_count_as_foreign_text(self) -> None:
        foreign = ForeignText()

        execute(ReadJournal(Journal(), now=lambda: NOW, foreign=foreign), {"kind": "tools"})

        assert foreign.sources == {ReadJournal.FOREIGN_SOURCE}

    def test_nothing_found_is_nothing_read(self) -> None:
        foreign = ForeignText()

        execute(ReadJournal(Journal(), now=lambda: NOW, foreign=foreign), {"contains": "такого нет"})

        assert foreign.sources == set()


class TestPrivateReplies:
    def test_reply_about_private_correspondence_is_veiled_for_the_model(self) -> None:
        entries = [
            JournalEntry(NOW, "tool", "INFO", "jericho", {"tool": "tg_recent", "private": True, "result": {"ok": True}}, run="r1"),
            JournalEntry(NOW, "phrase", "INFO", "jericho", {"phrase": "что пишет Марина", "status": "done", "message": "Марина: буду в 7"}, run="r1"),
            JournalEntry(NOW, "phrase", "INFO", "jericho", {"phrase": "открой ютуб", "status": "done", "message": "Открыл YouTube"}, run="r2"),
        ]

        veiled = ReadJournal._veiled(entries)

        assert [entry.details["message"] for entry in veiled if entry.event == "phrase"] == [ReadJournal.VEILED, "Открыл YouTube"]

