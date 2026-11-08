from collections.abc import Mapping
from datetime import datetime
from pathlib import Path

import pytest

from jericho.core.evals.adapters.json_runs import JsonRunStore
from jericho.core.evals.adapters.markdown_file import MarkdownEvalFile
from jericho.core.evals.entities import ActualCall, CaseResult, EvalCase, ExpectedCall, PhraseOutcome
from jericho.core.evals.report import EvalReport
from jericho.core.evals.session import EvalSession

TABLE = """# Фразы

| # | Фраза | Ручки | Статус | После | Заметка |
|---|---|---|---|---|---|
| 1 | открой портфолио на третьем | open_project {"project": "portfolio", "workspace": 3} | done | | |
| 2 | закрой всё | close_windows {"scope": "workspace"}; hyprctl? | clarify/done | | зависит от стола |
| 3 | да | close_windows {"confirm": true} | done | 2 | |
| 4 | пауза | media | done | | |
| 5 | э-э | — | ignored | | |
"""


def cases(tmp_path: Path) -> dict[str, EvalCase]:
    file = tmp_path / "evals.md"
    file.write_text(TABLE, encoding="utf-8")
    return {case.key: case for case in MarkdownEvalFile("desktop", file).cases()}


def result(case: EvalCase, *calls: ActualCall, status: str = "done", message: str = "Готово") -> CaseResult:
    return CaseResult(case, PhraseOutcome(calls, status, message))


def call(tool: str, **params: object) -> ActualCall:
    return ActualCall(tool, params)


class TestMarkdownEvalFile:
    def test_reads_phrases_with_expected_calls_and_statuses(self, tmp_path: Path) -> None:
        read = cases(tmp_path)

        assert list(read) == ["desktop:1", "desktop:2", "desktop:3", "desktop:4", "desktop:5"]
        assert read["desktop:1"].calls == (ExpectedCall("open_project", {"project": "portfolio", "workspace": 3}),)
        assert read["desktop:2"].calls[1] == ExpectedCall("hyprctl", {}, optional=True)
        assert read["desktop:2"].statuses == ("clarify", "done") and read["desktop:2"].note == "зависит от стола"
        assert read["desktop:3"].after == "desktop:2"
        assert read["desktop:5"].calls == ()

    def test_broken_parameters_name_the_file_and_the_phrase(self, tmp_path: Path) -> None:
        file = tmp_path / "evals.md"
        file.write_text('| 7 | фраза | open_app {"app": } | done | | |\n', encoding="utf-8")

        with pytest.raises(ValueError, match="evals.md: фраза 7"):
            MarkdownEvalFile("desktop", file).cases()


class TestCaseResult:
    def test_right_call_with_extra_parameters_passes(self, tmp_path: Path) -> None:
        case = cases(tmp_path)["desktop:1"]

        assert result(case, call("open_project", project="portfolio", workspace=3, editor="zed")).passed

    def test_wrong_parameter_fails_only_parameters(self, tmp_path: Path) -> None:
        marks = result(cases(tmp_path)["desktop:1"], call("open_project", project="portfolio", workspace=2)).marks

        assert marks == {"tools": True, "params": False, "outcome": True, "status": True, "message": True}

    def test_extra_or_missing_tool_fails_tools(self, tmp_path: Path) -> None:
        case = cases(tmp_path)["desktop:1"]
        right = call("open_project", project="portfolio", workspace=3)

        assert not result(case, right, call("hyprctl", command="dispatch workspace 3")).tools_ok
        assert not result(case).tools_ok

    def test_optional_call_may_happen_any_number_of_times(self, tmp_path: Path) -> None:
        case = cases(tmp_path)["desktop:2"]
        close = call("close_windows", scope="workspace")

        assert result(case, close, status="clarify").passed
        assert result(case, call("hyprctl", command="clients"), call("hyprctl", command="clients"), close).passed

    def test_any_of_the_listed_statuses_passes(self, tmp_path: Path) -> None:
        case = cases(tmp_path)["desktop:2"]
        close = call("close_windows", scope="workspace")

        assert result(case, close, status="clarify").status_ok and result(case, close, status="done").status_ok
        assert not result(case, close, status="refused").status_ok

    def test_long_message_fails_message(self, tmp_path: Path) -> None:
        assert not result(cases(tmp_path)["desktop:5"], status="ignored", message="я" * 81).message_ok

    def test_phrase_for_a_tool_that_is_not_connected_expects_a_plain_refusal(self, tmp_path: Path) -> None:
        case = cases(tmp_path)["desktop:4"].for_connected({"open_project", "close_windows"})

        assert (case.calls, case.statuses) == ((), ("refused",))
        assert result(case, status="refused").passed and not result(case, call("media"), status="done").passed


class TestPartlyConnected:
    CASE = EvalCase("desktop:19", "открой портфолио и включи музыку", (ExpectedCall("open_project"), ExpectedCall("media")), ("done",))

    def test_compound_phrase_expects_the_part_that_can_be_done(self) -> None:
        case = self.CASE.for_connected({"open_project"})

        assert case.calls == (ExpectedCall("open_project"),) and case.statuses == ("done", "refused")
        assert result(case, call("open_project", project="portfolio"), message="Открыл portfolio. Музыку пока не умею").passed

    def test_doing_nothing_at_all_is_not_enough(self) -> None:
        assert not result(self.CASE.for_connected({"open_project"}), status="refused").tools_ok

    def test_optional_call_alone_does_not_make_the_phrase_doable(self) -> None:
        case = EvalCase("desktop:9", "погромче", (ExpectedCall("media"), ExpectedCall("hyprctl", optional=True)), ("done",))

        assert case.for_connected({"hyprctl"}).calls == ()


class Runner:
    def __init__(self) -> None:
        self.log: list[str] = []

    def forget(self) -> None:
        self.log.append("— забыл —")

    def run(self, phrase: str) -> PhraseOutcome:
        self.log.append(phrase)
        return PhraseOutcome(status="ignored")


class Source:
    def __init__(self, cases_: Mapping[str, EvalCase]) -> None:
        self._cases = cases_

    def cases(self) -> tuple[EvalCase, ...]:
        return tuple(self._cases.values())


class TestEvalSession:
    def test_every_phrase_starts_a_new_conversation(self, tmp_path: Path) -> None:
        runner = Runner()

        EvalSession([Source(cases(tmp_path))], runner, {"open_project"}).run(only=["desktop:1", "desktop:5"])

        assert runner.log == ["— забыл —", "открой портфолио на третьем", "— забыл —", "э-э"]

    def test_follow_up_phrase_is_said_right_after_the_one_it_answers(self, tmp_path: Path) -> None:
        runner = Runner()

        results = EvalSession([Source(cases(tmp_path))], runner, {"close_windows", "hyprctl"}).run(only=["desktop:3"])

        assert runner.log == ["— забыл —", "закрой всё", "да"]
        assert [item.case.key for item in results] == ["desktop:3"]

    def test_expectation_follows_what_is_connected(self, tmp_path: Path) -> None:
        (item,) = EvalSession([Source(cases(tmp_path))], Runner(), {"open_project"}).run(only=["desktop:4"])

        assert item.case.statuses == ("refused",)


class TestEvalReport:
    def test_shows_what_happened_and_what_was_expected_for_a_failed_phrase(self, tmp_path: Path) -> None:
        case = cases(tmp_path)["desktop:1"]
        report = EvalReport([result(case, call("open_project", project="portfolio", workspace=2))])

        lines = report.lines()

        assert lines[0].startswith("✗ desktop:1") and 'open_project {"project": "portfolio", "workspace": 2} · done' in lines[1]
        assert "не сошлось: параметры" in lines[2]
        assert report.summary().startswith("Прошло 0 из 1  ·  ручки 1/1  параметры 0/1  исход 1/1  статус 1/1  сообщение 1/1")

    def test_names_phrases_whose_marks_changed_since_the_previous_run(self, tmp_path: Path) -> None:
        read = cases(tmp_path)
        report = EvalReport([
            result(read["desktop:1"], call("open_project", project="portfolio", workspace=3)),
            result(read["desktop:5"], status="ignored"),
        ])
        before = {
            "desktop:1": {"tools": True, "params": False, "status": True, "message": True},
            "desktop:5": {"tools": True, "params": True, "status": True, "message": True},
        }

        assert report.changes(before) == ["  desktop:1    открой портфолио на третьем: параметры ✗→✓"]


class TestJsonRunStore:
    def test_previous_run_is_the_latest_saved(self, tmp_path: Path) -> None:
        times = iter([datetime(2026, 10, 11, 20, 0), datetime(2026, 10, 11, 21, 0)])
        store = JsonRunStore(tmp_path / "runs", clock=lambda: next(times))
        marks = {"tools": True, "params": True, "status": False, "message": True}

        assert store.previous() is None
        store.save({"cases": [{"key": "desktop:1", "marks": {**marks, "status": True}}]})
        store.save({"cases": [{"key": "desktop:1", "marks": marks}]})

        assert store.previous() == {"desktop:1": marks}


class TestOutcome:
    """Ревью R10: ручка отказала, а модель сказала «сделано» — фраза не засчитывается."""

    def test_done_on_top_of_a_failed_tool_fails_the_outcome(self, tmp_path: Path) -> None:
        failed = ActualCall("open_project", {"project": "portfolio", "workspace": 3}, {"ok": False, "error": "tool_failed"})

        assert result(cases(tmp_path)["desktop:1"], failed).marks["outcome"] is False

    def test_expected_refusal_is_a_pass(self) -> None:
        case = EvalCase("d:1", "закрой всё", (ExpectedCall("close_windows", {}, error="needs_confirm"),), ("clarify",))
        asked = ActualCall("close_windows", {}, {"ok": False, "error": "needs_confirm"})

        assert CaseResult(case, PhraseOutcome((asked,), "clarify", "Закрыть пять окон?")).outcome_ok

    def test_expected_refusal_is_written_after_an_exclamation_mark(self, tmp_path: Path) -> None:
        file = tmp_path / "evals.md"
        file.write_text("| # | Фраза | Ручки | Статус | После | Заметка |\n|---|---|---|---|---|---|\n| 1 | закрой всё | close_windows !needs_confirm | clarify | | |\n", encoding="utf-8")

        (case,) = MarkdownEvalFile("desktop", file).cases()

        assert case.calls == (ExpectedCall("close_windows", {}, error="needs_confirm"),)
