import logging
import signal
import time
from typing import ClassVar

import pytest
from pydantic import Field

from jericho.core import PortError, Risk, Tool, ToolCall, ToolDescription, ToolRefusal, ToolRequest, ToolResult
from jericho.core.conf.settings import Settings
from jericho.core.services.confirmation import ConfirmationGate
from jericho.core.skills.middleware import RequireLoadedSkill
from jericho.core.testing.fakes import Confirmations
from jericho.core.tools.confirm import Confirm
from jericho.core.tools.deadline import Deadline
from jericho.core.tools.dispatcher import CallHandler, ToolDispatcher
from jericho.core.tools.loader import MiddlewareLoader, MiddlewareLoadError
from jericho.core.tools.middleware import Journal, Refusals
from jericho.core.tools.session import CallSession


class EchoRequest(ToolRequest):
    text: str = Field(description="Что повторить.")
    times: int = Field(default=1, ge=1, le=3, description="Сколько раз.")


class DiskError(PortError):
    code = "disk_error"


class Echo(Tool[EchoRequest]):
    name = "echo"
    description = ToolDescription(when="Просят повторить.", does="Повторяет.", returns="Текст.", refusals="empty.")
    request_type = EchoRequest

    def _run(self, request: EchoRequest) -> ToolResult:
        if not request.text:
            raise ToolRefusal("empty", hint="скажи что-нибудь")
        if request.text == "диск":
            raise DiskError("no space left")
        if request.text == "долго":
            time.sleep(5)
        if request.text == "упрямо":
            try:
                time.sleep(5)
            except Exception:
                return ToolResult.success(said="проглотил")
        if request.text == "сбой":
            raise ZeroDivisionError("секрет из недр ручки")
        return ToolResult.success(said=request.text)


def tracing(name: str, trace: list[str]) -> type:
    class Layer:
        def __init__(self, handle: CallHandler) -> None:
            self._handle = handle

        def __call__(self, call: ToolCall) -> ToolResult:
            trace.append(f"{name} до")
            result = self._handle(call)
            trace.append(f"{name} после")
            return result

    return Layer


class TestToolDispatcher:
    def test_without_layers_the_call_goes_straight_to_the_tool(self) -> None:
        assert ToolDispatcher().call(Echo(), {"text": "привет"}) == ToolResult.success(said="привет")

    def test_first_layer_is_the_outermost(self) -> None:
        trace: list[str] = []

        ToolDispatcher([tracing("внешний", trace), tracing("внутренний", trace)]).call(Echo(), {"text": "привет"})

        assert trace == ["внешний до", "внутренний до", "внутренний после", "внешний после"]

    def test_tool_gets_a_checked_request_with_defaults_filled_in(self) -> None:
        seen: list[EchoRequest] = []

        class Spy(Echo):
            def _run(self, request: EchoRequest) -> ToolResult:
                seen.append(request)
                return ToolResult.success()

        ToolDispatcher().call(Spy(), {"text": "привет"})

        assert seen == [EchoRequest(text="привет", times=1)]


class TestInvalidParameters:
    @pytest.mark.parametrize(
        ("arguments", "field"),
        [({}, "text"), ({"text": "привет", "times": 9}, "times"), ({"text": "привет", "loud": True}, "loud")],
    )
    def test_wrong_parameters_become_one_refusal_that_names_the_field(self, arguments: dict[str, object], field: str) -> None:
        result = ToolDispatcher([Refusals]).call(Echo(), arguments)

        assert result.error == "invalid_parameters"
        problems = result.data["problems"]
        assert isinstance(problems, list) and [problem["field"] for problem in problems] == [field]

    def test_tool_is_not_run_when_parameters_are_wrong(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.INFO, logger="jericho"):
            ToolDispatcher([Journal, Refusals]).call(Echo(), {"text": "привет", "times": 9})

        data = caplog.records[-1].data  # pyright: ignore[reportAttributeAccessIssue] — поле из extra
        assert data["params"] == {"text": "привет", "times": 9} and data["result"]["error"] == "invalid_parameters"


class TestToolSchema:
    def test_model_sees_descriptions_limits_and_no_extra_titles(self) -> None:
        schema = EchoRequest.tool_schema()

        assert schema["required"] == ["text"] and schema["additionalProperties"] is False
        assert schema["properties"]["times"] == {"default": 1, "description": "Сколько раз.", "maximum": 3, "minimum": 1, "type": "integer"}
        assert "title" not in schema and "title" not in schema["properties"]["text"]


class TestRefusals:
    def test_refusal_becomes_an_answer_with_its_code_and_details(self) -> None:
        result = ToolDispatcher([Refusals]).call(Echo(), {"text": ""})

        assert result == ToolResult.failure("empty", hint="скажи что-нибудь")

    def test_outside_world_error_becomes_an_answer_with_the_port_code(self) -> None:
        result = ToolDispatcher([Refusals]).call(Echo(), {"text": "диск"})

        assert result == ToolResult.failure("disk_error", detail="no space left")


class TestUnexpectedFailure:
    """Находка ревью: исключение, которого не ждал ни один слой, уходило мимо журнала прямо в библиотеку протокола."""

    def test_crash_in_the_tool_becomes_a_short_code_and_a_journal_record(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.INFO, logger="jericho"):
            result = ToolDispatcher([Journal, Refusals]).call(Echo(), {"text": "сбой"})

        record = caplog.records[-1]
        data = record.data  # pyright: ignore[reportAttributeAccessIssue] — поле из extra
        assert result == ToolResult.failure("tool_failed", detail="ZeroDivisionError")
        assert (record.getMessage(), record.levelname, record.exc_info is not None) == ("tool", "ERROR", True)
        assert (data["tool"], data["params"], data["result"]["error"]) == ("echo", {"text": "сбой"}, "tool_failed")

    def test_text_of_the_exception_does_not_reach_the_model(self) -> None:
        assert "секрет" not in str(ToolDispatcher().call(Echo(), {"text": "сбой"}).to_dict())

    def test_crash_in_a_layer_is_caught_too(self) -> None:
        class Broken:
            def __init__(self, handle: CallHandler) -> None:
                pass

            def __call__(self, call: ToolCall) -> ToolResult:
                raise RuntimeError("слой сломан")

        assert ToolDispatcher([Broken]).call(Echo(), {"text": "привет"}).error == "tool_failed"

    def test_refusal_without_its_layer_is_a_failure_not_an_exception(self) -> None:
        assert ToolDispatcher().call(Echo(), {"text": ""}).error == "tool_failed"


class TestRisk:
    def test_every_core_tool_declares_its_own_risk(self) -> None:
        from jericho.core.skills.load_skill import LoadSkill
        from jericho.core.tools.confirm import Confirm

        assert all("risk" in vars(tool) for tool in (LoadSkill, Confirm))

    def test_tool_that_forgot_its_risk_is_treated_as_the_most_dangerous(self) -> None:
        assert (Echo.risk, Echo().destructive, Echo().read_only) == (Risk.EFFECT, True, False)


class TestDeadline:
    """Находка ревью: срока у ручки не было, и действие могло идти дольше фразы — уже после ответа «не получилось»."""

    def test_tool_that_takes_too_long_is_cut_off_and_reported(self, caplog: pytest.LogCaptureFixture) -> None:
        started = time.perf_counter()

        with caplog.at_level(logging.INFO, logger="jericho"):
            result = ToolDispatcher([Journal, Refusals], deadline=Deadline(0.1)).call(Echo(), {"text": "долго"})

        assert (result.error, result.data["seconds"]) == ("tool_timeout", 0.1)
        assert time.perf_counter() - started < 2
        assert (caplog.records[-1].getMessage(), caplog.records[-1].levelname) == ("tool", "ERROR")

    def test_tool_that_is_in_time_is_not_disturbed_and_the_timer_is_cleared(self) -> None:
        dispatcher = ToolDispatcher([Refusals], deadline=Deadline(0.2))

        assert dispatcher.call(Echo(), {"text": "привет"}).ok
        time.sleep(0.3)      # таймер снят: сигнал после вызова не приходит
        assert signal.getitimer(signal.ITIMER_REAL)[0] == 0

    def test_broad_except_inside_the_tool_cannot_swallow_the_deadline(self) -> None:
        assert ToolDispatcher(deadline=Deadline(0.1)).call(Echo(), {"text": "упрямо"}).error == "tool_timeout"

    def test_without_a_deadline_nothing_is_limited(self) -> None:
        assert ToolDispatcher().call(Echo(), {"text": "привет"}).ok


class TestJournal:
    def test_writes_the_tool_its_parameters_the_final_answer_and_the_time(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.INFO, logger="jericho"):
            ToolDispatcher([Journal, Refusals]).call(Echo(), {"text": ""})

        record = caplog.records[-1]
        data = record.data  # pyright: ignore[reportAttributeAccessIssue] — поле из extra
        assert record.getMessage() == "tool"
        assert (data["tool"], data["params"]) == ("echo", {"text": ""})
        assert data["result"] == {"ok": False, "error": "empty", "hint": "скажи что-нибудь"} and data["ms"] >= 0

    def test_long_text_in_the_answer_is_cut_in_the_journal_but_not_in_the_answer(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.INFO, logger="jericho"):
            result = ToolDispatcher([Journal]).call(Echo(), {"text": "я" * 1000})

        logged = caplog.records[-1].data["result"]["said"]  # pyright: ignore[reportAttributeAccessIssue]
        assert result.data["said"] == "я" * 1000
        assert logged == "я" * 300 + "… (всего 1000 знаков)"


class TestMiddlewareLoader:
    def test_default_settings_name_layers_that_exist(self) -> None:
        assert MiddlewareLoader().load(Settings().TOOL_MIDDLEWARE) == (Journal, Refusals, RequireLoadedSkill)

    @pytest.mark.parametrize("path", ["jericho.core.tools.middleware.Jurnal", "jericho.nowhere.Layer", "Journal"])
    def test_unknown_layer_is_named_in_the_error(self, path: str) -> None:
        with pytest.raises(MiddlewareLoadError, match=path):
            MiddlewareLoader().load([path])


class ReadChat(Tool[EchoRequest]):
    """Отдаёт чужую переписку: её поля — личные."""

    name = "read_chat"
    risk = Risk.READ
    private = ("text", "messages")
    description = ToolDescription(when="Просят прочитать.", does="Читает.", returns="Сообщения.", refusals="—.")
    request_type = EchoRequest

    def _run(self, request: EchoRequest) -> ToolResult:
        return ToolResult.success(messages=["буду в 7", "захвати ключи"], memo="прочитал чат: 2 сообщения")


class TestPrivateFields:
    def test_private_fields_stay_out_of_the_journal_but_reach_the_model(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.INFO, logger="jericho"):
            result = ToolDispatcher([Journal, Refusals]).call(ReadChat(), {"text": "Марина"})

        data = caplog.records[-1].data  # pyright: ignore[reportAttributeAccessIssue] — поле из extra
        assert result.data["messages"] == ["буду в 7", "захвати ключи"]          # модели — целиком
        assert data["params"] == {"text": "скрыто: 6 знаков"}
        assert data["result"]["messages"] == "скрыто: 2 шт." and data["result"]["memo"] == "прочитал чат: 2 сообщения"
        assert data["private"] is True

    def test_ordinary_tool_has_no_private_mark(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.INFO, logger="jericho"):
            ToolDispatcher([Journal, Refusals]).call(Echo(), {"text": "привет"})

        assert "private" not in caplog.records[-1].data  # pyright: ignore[reportAttributeAccessIssue]



class PrivateEcho(Echo):
    """Как echo, но `text` — чужая переписка."""

    name = "private_echo"
    private: ClassVar[tuple[str, ...]] = ("text", "said")

    def _run(self, request: EchoRequest) -> ToolResult:
        if request.text.startswith("сбой"):
            raise ValueError(f"не разобрал: {request.text}")      # текст исключения несёт сам личный текст
        return super()._run(request)


class TestPrivateFieldsEverywhere:
    """Личные поля скрыты не только слоем журнала, но и на путях мимо него (ревью 02.11.2026, П1 №1, П2 №2)."""

    def test_crash_record_hides_the_fields_and_the_text_of_the_exception(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.INFO, logger="jericho"):
            ToolDispatcher([Journal, Refusals]).call(PrivateEcho(), {"text": "сбой: у Анны в 7"})

        record = caplog.records[-1]
        data = record.data  # pyright: ignore[reportAttributeAccessIssue] — поле из extra
        assert data["params"] == {"text": "скрыто: 16 знаков"} and data["private"] is True
        assert data["error"] == "ValueError" and "_run" in data["trace"]
        assert record.exc_info is None and "Анн" not in str(data)

    def test_question_of_the_framework_hides_them(self) -> None:
        summary = PrivateEcho().consent_summary({"text": "встретимся у Анны в 7", "times": 2})

        assert "Анн" not in summary and '"times": 2' in summary and "скрыто: 21 знаков" in summary

    def test_confirm_record_hides_the_fields_of_the_confirmed_tool(self, caplog: pytest.LogCaptureFixture) -> None:
        store = Confirmations()
        store.ask("private_echo", {"text": "привет от Анны"}, "повторить", "run-1")     # вопрос из прошлой фразы
        gate = ConfirmationGate(store, "run-2")
        gate.user_said_yes()
        dispatcher = ToolDispatcher([Journal, Refusals])
        confirm = Confirm(gate, dispatcher, [PrivateEcho()], CallSession())

        with caplog.at_level(logging.INFO, logger="jericho"):
            result = dispatcher.call(confirm, {})

        outer = caplog.records[-1].data  # pyright: ignore[reportAttributeAccessIssue] — поле из extra
        assert result.ok and result.data["said"] == "привет от Анны"         # модель получает ответ целиком
        assert outer["tool"] == "confirm" and outer["private"] is True and "Анн" not in str(outer)
