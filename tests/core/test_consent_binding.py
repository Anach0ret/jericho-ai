"""«Да» относится ровно к тому вопросу, который пользователь видел (ревью 02.11.2026: сводка №2, П1 №2, №4, №5, П3b №1).

Каждая фраза — свой запуск, как в работе: своя служба подтверждения, свой диспетчер с политикой, свой `HandlePhrase`.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import partial
from typing import Any

from jericho.core import ConfirmationGate, Risk, Tool, ToolDescription, ToolRefusal, ToolRequest, ToolResult
from jericho.core.agent.consent import AnswerWithoutModel, AskedQuestion, PhraseConsent
from jericho.core.agent.entities import AgentReply, BackendAnswer, ReplyStatus
from jericho.core.agent.handle_phrase import HandlePhrase
from jericho.core.testing import Confirmations, FakeBackend, builder
from jericho.core.tools.confirm import Confirm
from jericho.core.tools.dispatcher import ToolDispatcher
from jericho.core.tools.middleware import Refusals
from jericho.core.tools.policy import RiskPolicy
from jericho.core.tools.session import CallSession

DESCRIPTION = ToolDescription(when="тест", does="тест", returns="тест", refusals="тест")


class SendRequest(ToolRequest):
    to: str


class Send(Tool[SendRequest]):
    """EFFECT: «да» спрашивает политика (`approval=ASK`)."""

    name = "send"
    request_type = SendRequest
    description = DESCRIPTION

    def __init__(self, sent: list[str]) -> None:
        self.sent = sent

    def consent_summary(self, arguments: Mapping[str, object]) -> str:
        return f"отправить письмо {arguments['to']}"

    def _run(self, request: SendRequest) -> ToolResult:
        self.sent.append(request.to)
        return ToolResult.success()


@dataclass
class World:
    """То, что переживает фразы: что отправлено, что подходит под «стереть», что открыто."""

    found: list[str]
    erased: list[str]
    sent: list[str]
    opened: list[str]


class EraseRequest(ToolRequest):
    what: str


class Erase(Tool[EraseRequest]):
    """Согласие — на то, что сейчас подходит под запрос (`subject`): изменилось — спросить заново."""

    name = "erase"
    risk = Risk.CHANGE
    request_type = EraseRequest
    description = DESCRIPTION

    def __init__(self, gate: ConfirmationGate, world: World) -> None:
        self._gate = gate
        self._world = world

    def _run(self, request: EraseRequest) -> ToolResult:
        consent = self._gate.consent(self.name, request.model_dump(), f"стереть {request.what}", sorted(self._world.found))
        if not consent.granted:
            raise ToolRefusal("needs_confirm", **consent.notes())
        self._world.erased.append(request.what)
        return ToolResult.success()


class OpenRequest(ToolRequest):
    url: str


class OpenPage(Tool[OpenRequest]):
    """Выносит наружу: после личных данных — только с «да» (`OutboundAfterPrivate`)."""

    name = "open_page"
    risk = Risk.NAVIGATE
    outbound = True
    request_type = OpenRequest
    description = DESCRIPTION

    def __init__(self, opened: list[str]) -> None:
        self.opened = opened

    def _run(self, request: OpenRequest) -> ToolResult:
        self.opened.append(request.url)
        return ToolResult.success()


class Model(FakeBackend):
    """Модель одной фразы: сначала вызывает ручку (`act`), потом отвечает `structured`."""

    def __init__(self, structured: dict[str, object], act: Callable[[], object] | None = None) -> None:
        super().__init__(structured)
        self._act = act

    def ask(self, system_prompt: str, phrase: str) -> BackendAnswer:
        if self._act is not None:
            self._act()
        return super().ask(system_prompt, phrase)


@dataclass
class Run:
    """Один запуск: всё, что ассистент собирает на фразу."""

    gate: ConfirmationGate
    dispatcher: ToolDispatcher
    session: CallSession
    tools: dict[str, Tool[Any]]

    def handle(self, model: Model) -> HandlePhrase:
        confirm = Confirm(self.gate, self.dispatcher, list(self.tools.values()), self.session)
        return HandlePhrase(
            builder(), model, consent=AnswerWithoutModel(PhraseConsent(self.gate), partial(self.dispatcher.call, confirm, {})),
            question=AskedQuestion(self.gate),
        )

    def call(self, name: str, **arguments: object) -> Callable[[], ToolResult]:
        return partial(self.dispatcher.call, self.tools[name], arguments)


def run(store: Confirmations, run_id: str, world: World, ceiling: Risk | None = None) -> Run:
    gate, session = ConfirmationGate(store, run_id), CallSession()
    dispatcher = ToolDispatcher((Refusals,), session, policy=RiskPolicy(gate, ceiling=ceiling))
    tools: dict[str, Tool[Any]] = {
        tool.name: tool for tool in (Send(world.sent), Erase(gate, world), OpenPage(world.opened))
    }
    return Run(gate, dispatcher, session, tools)


def world() -> World:
    return World(found=["файл-1"], erased=[], sent=[], opened=[])


DONE: dict[str, object] = {"status": "done", "message": "модель ответила"}


def clarify(message: str) -> dict[str, object]:
    return {"status": "clarify", "message": message}


class TestQuestionTextIsTheCores:
    def test_yes_to_the_models_own_words_names_what_will_really_happen(self) -> None:
        """Сводка №2: показано «Продолжать читать?», а «да» выполнило отправку письма X."""
        store, state = Confirmations(), world()
        first = run(store, "run-1", state)
        model = Model(clarify("Продолжать читать?"), first.call("send", to="X"))

        shown = first.handle(model).execute("прочитай почту")

        assert shown.status is ReplyStatus.CLARIFY and shown.options == ("Да", "Нет")
        assert shown.message.splitlines()[0] == "Отправить письмо X? Да или нет."

    def test_models_own_question_in_a_later_phrase_withdraws_the_waiting_one(self) -> None:
        """«Да» на новый вопрос модели не выполняет старый, о котором пользователь уже не думает."""
        store, state = Confirmations(), world()
        first = run(store, "run-1", state)
        first.handle(Model(clarify("Отправить?"), first.call("send", to="X"))).execute("ответь X")

        run(store, "run-2", state).handle(Model(clarify("Продолжать читать?"))).execute("а что там дальше")
        third = run(store, "run-3", state).handle(Model(DONE)).execute("да")

        assert state.sent == [] and store.pending() is None
        assert third.message == "модель ответила"


class TestStaleButton:
    def test_button_of_a_replaced_question_does_not_confirm_the_new_one(self) -> None:
        """П3b №1: кнопка «Да» под «Удалить A» подтвердила появившийся позже «Удалить B»."""
        store, state = Confirmations(), world()
        first = run(store, "run-1", state)
        first.handle(Model(clarify("?"), first.call("send", to="A"))).execute("ответь A")
        asked_a = store.pending()
        second = run(store, "run-2", state)
        second.handle(Model(clarify("?"), second.call("send", to="B"))).execute("нет, ответь B")
        assert asked_a is not None and asked_a.id

        reply = run(store, "run-3", state).handle(Model(DONE)).execute("да", question=asked_a.id)

        assert state.sent == [] and reply.status is ReplyStatus.REFUSED
        pending = store.pending()
        assert pending is not None and pending.summary == "отправить письмо B" and not pending.approved_by

    def test_button_of_the_shown_question_confirms_it(self) -> None:
        store, state = Confirmations(), world()
        first = run(store, "run-1", state)
        first.handle(Model(clarify("?"), first.call("send", to="A"))).execute("ответь A")
        pending = store.pending()
        assert pending is not None

        reply = run(store, "run-2", state).handle(Model(DONE)).execute("да", question=pending.id)

        assert state.sent == ["A"] and reply.status is ReplyStatus.DONE

    def test_every_question_has_its_own_id(self) -> None:
        store = Confirmations()
        gate = ConfirmationGate(store, "run-1")
        gate.consent("send", {"to": "A"}, "отправить A")
        first = store.pending()
        gate.consent("send", {"to": "B"}, "отправить B")
        second = store.pending()

        assert first is not None and second is not None and first.id != second.id


class TestChangedSubject:
    def test_changed_world_asks_anew_and_the_third_phrase_yes_works(self) -> None:
        """П1 №4: новый вопрос после изменения тут же снимался — второе «да» уже нечего было подтверждать."""
        store, state = Confirmations(), world()
        first = run(store, "run-1", state)
        first.handle(Model(clarify("?"), first.call("erase", what="черновик"))).execute("сотри черновик")
        state.found = ["файл-1", "файл-2"]

        second = run(store, "run-2", state).handle(Model(DONE)).execute("да")

        assert second.status is ReplyStatus.CLARIFY and second.options == ("Да", "Нет")
        assert second.message.splitlines()[0] == "Стереть черновик? Да или нет."
        assert store.pending() is not None and state.erased == []
        third = run(store, "run-3", state).handle(Model(DONE)).execute("да")
        assert third.status is ReplyStatus.DONE and state.erased == ["черновик"]


class TestUserCeilingAndConfirm:
    def test_user_may_confirm_what_is_within_their_limit(self) -> None:
        """П1 №5: `confirm` — EFFECT, и предел NAVIGATE отказывал в разрешённом переходе после личных данных."""
        store, state = Confirmations(), world()
        first = run(store, "run-1", state, ceiling=Risk.NAVIGATE)
        first.session.read_private()
        asked = first.call("open_page", url="https://example.org")()
        assert asked.error == "needs_confirm"
        first.handle(Model(clarify("?"))).execute("открой")  # вопрос уже записан этой фразой

        reply = run(store, "run-2", state, ceiling=Risk.NAVIGATE).handle(Model(DONE)).execute("да")

        assert reply.status is ReplyStatus.DONE and state.opened == ["https://example.org"]

    def test_the_target_is_still_held_to_the_limit(self) -> None:
        """Предел проверяется у подтверждённой ручки: вопрос, заданный под другим пределом, «да» не исполнит."""
        store, state = Confirmations(), world()
        first = run(store, "run-1", state)
        first.handle(Model(clarify("?"), first.call("send", to="X"))).execute("ответь X")

        reply = run(store, "run-2", state, ceiling=Risk.NAVIGATE).handle(Model(DONE)).execute("да")

        assert state.sent == [] and reply.status is ReplyStatus.REFUSED and isinstance(reply, AgentReply)
