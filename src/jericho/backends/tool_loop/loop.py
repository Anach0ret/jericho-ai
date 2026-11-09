"""Цикл «модель → ручка → модель» в нашем процессе — общий для бэкендов по ключу API.

Программа `claude` ведёт этот цикл сама; модель по ключу — нет: ей отдают ручки, она возвращает вызовы,
и выполнить их, вернуть результаты и спросить снова должен кто-то из нас. Этот кто-то — `ToolLoop`.
Вызовы идут через тот же диспетчер, что и у сервера ручек: те же слои, отказы и журнал.

Итоговый ответ модель даёт вызовом служебной ручки `reply`, параметры которой — форма ответа проекта.
Так ответ всегда структурный, и на любом API, где есть вызов ручек, а не только там, где есть «ответ по схеме».

Ответ не по форме получает **одну** вторую попытку, и только ответа: с этого хода вызовы ручек не выполняются
(`reply_only`). Модель уже сделала то, что сделала, — переписать можно слова, но не дела.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from jericho.backends.tool_loop.entities import CallAnswer, ToolCall, ToolSpec, Usage
from jericho.backends.tool_loop.protocols import ChatModel
from jericho.core.agent.entities import BackendAnswer
from jericho.core.agent.protocols import AgentBackendError, ModelTimeout
from jericho.core.services.phrase_deadline import PhraseDeadline
from jericho.core.skills.load_skill import brief_description
from jericho.core.tools.dispatcher import ToolDispatcher
from jericho.core.tools.tool import Tool


class ToolLoop:
    """Ведёт разговор с моделью, пока она не вызовет `reply`, не кончатся ходы или время."""

    REPLY = "reply"
    REPLY_DESCRIPTION = (
        "Итоговый ответ пользователю: параметры — тот самый JSON-объект из раздела «Формат ответа». Вызови последним "
        "и отдельно: в одном ходе с другими ручками он не принимается — сначала посмотри, что они вернули."
    )
    UNKNOWN_TOOL = "unknown_tool"
    REPLY_TOO_EARLY = "reply_too_early"
    NO_CALL = "Ответ принимается только вызовом ручки. Если всё сделано — вызови reply."
    REPLY_INVALID = "reply_invalid"
    REPLY_ONLY = "reply_only"
    INVALID_ARGUMENTS = "invalid_arguments"
    OUT_OF_TIME = "out_of_time"
    TOO_MANY_CALLS = "too_many_calls"
    RETRY = "ответ не по форме — верни его ещё раз вызовом reply; новые действия больше не выполняются"
    _FENCE, _FENCE_TAG = "```", "json"      # ответ текстом в ограде ```json

    def __init__(
        self,
        model: ChatModel,
        tools: Sequence[Tool[Any]],
        dispatcher: ToolDispatcher,
        reply_schema: Mapping[str, object],
        timeout: float,
        max_turns: int,
        clock: Callable[[], float] = time.monotonic,
        max_calls: int = 30,
        check_reply: Callable[[Mapping[str, object]], object] = lambda reply: None,
        phrase: PhraseDeadline | None = None,
    ) -> None:
        self._model = model
        self._phrase = phrase or PhraseDeadline()     # общий срок фразы: запасной цикл получает остаток, а не новый срок
        self._check_reply = check_reply        # форма ответа проекта: не по форме — ValueError
        self._tools = {tool.name: tool for tool in tools}
        if self.REPLY in self._tools:
            raise ValueError(f"tool name '{self.REPLY}' is reserved for the final answer of a model behind an API key")
        self._dispatcher = dispatcher
        self._specs = (
            *(ToolSpec(tool.name, brief_description(tool), tool.request_type.tool_schema()) for tool in tools),
            ToolSpec(self.REPLY, self.REPLY_DESCRIPTION, reply_schema),
        )
        self._timeout = timeout
        self._max_turns = max_turns
        self._max_calls = max_calls          # вызовов ручек на поручение: ходы ограничены, а вызовов в одном ходе — нет
        self._clock = clock

    def ask(self, system_prompt: str, phrase: str) -> BackendAnswer:
        left = self._phrase.left()
        deadline = self._clock() + (self._timeout if left is None else min(self._timeout, left))
        chat = self._model.chat(system_prompt, phrase, self._specs)
        usage, made, retried = Usage(), list[dict[str, object]](), False
        for turns in range(1, self._max_turns + 1):
            left = deadline - self._clock()
            if left <= 0:
                raise ModelTimeout(f"model did not answer within {self._timeout:g} s")
            turn = chat.turn(left)
            usage += turn.usage
            replies = [call for call in turn.calls if call.name == self.REPLY]
            actions = [call for call in turn.calls if call.name != self.REPLY]
            # Слабая модель пишет ответ текстом, а не вызовом: форма та же, его проверит форма ответа.
            written = self._written_reply(turn.text) if not turn.calls else None
            # Ответ, параметры которого не разобрались, — ответ не по форме: он получит ту же вторую попытку.
            reply = ({} if replies[0].problem else dict(replies[0].arguments)) if replies and not actions else written
            if reply is not None:
                problem = self._problem(reply)
                if problem is None or retried:
                    meta = {**self._meta(turns, made, usage), **({"reply_as_text": True} if written is not None else {})}
                    return BackendAnswer(reply, {**meta, **({"reply_retried": True} if retried else {})})
                retried = True
                if written is not None:
                    chat.remind(f"{self.RETRY}: {problem}")
                else:
                    chat.answer([self._invalid(call, problem) for call in replies])
                continue
            if not turn.calls:
                chat.remind(self.NO_CALL)
                continue
            chat.answer([self._answer(call, made, deadline, reply_only=retried) for call in turn.calls])
        raise AgentBackendError(f"model did not reply in {self._max_turns} turns")

    def _refusal(self, call: ToolCall, made: list[dict[str, object]], deadline: float, reply_only: bool) -> str:
        """Почему вызов не выполняется, не доходя до ручки; пусто — выполняется."""
        if reply_only:
            return self.REPLY_ONLY
        if call.problem:
            return self.INVALID_ARGUMENTS
        if deadline - self._clock() <= 0:
            return self.OUT_OF_TIME
        if len(made) >= self._max_calls:
            return self.TOO_MANY_CALLS
        return ""

    def _problem(self, reply: Mapping[str, object]) -> str | None:
        try:
            self._check_reply(reply)
        except ValueError as error:
            return str(error)[:300]
        return None

    def _invalid(self, call: ToolCall, problem: str) -> CallAnswer:
        return CallAnswer(call.id, {"ok": False, "error": self.REPLY_INVALID, "problem": problem, "hint": self.RETRY}, is_error=True)

    def _answer(self, call: ToolCall, made: list[dict[str, object]], deadline: float, reply_only: bool = False) -> CallAnswer:
        """Ответ на вызов. `reply` рядом с действиями не принимается: модель писала его, не видя их итога.

        Перед каждой ручкой — остаток срока поручения и счёт вызовов: ход модели может прийти на последней секунде
        и с десятком вызовов сразу (ревью R08). Срок ручки не выходит за остаток.
        """
        if call.name == self.REPLY:
            return CallAnswer(call.id, {"ok": False, "error": self.REPLY_TOO_EARLY}, is_error=True)
        refusal = self._refusal(call, made, deadline, reply_only)
        if refusal:
            made.append({"tool": call.name, "error": refusal})
            return CallAnswer(call.id, {"ok": False, "error": refusal, **({"hint": self.RETRY} if refusal == self.REPLY_ONLY else {})}, is_error=True)
        tool = self._tools.get(call.name)
        if tool is None:
            made.append({"tool": call.name, "error": self.UNKNOWN_TOOL})
            return CallAnswer(call.id, {"ok": False, "error": self.UNKNOWN_TOOL, "available": list(self._tools)}, is_error=True)
        result = self._dispatcher.call(tool, call.arguments, budget=deadline - self._clock())
        made.append({"tool": call.name, "ok": True} if result.ok else {"tool": call.name, "error": result.error})
        return CallAnswer(call.id, result.to_dict(), is_error=not result.ok, images=result.images)

    def _written_reply(self, text: str) -> dict[str, object] | None:
        """Ответ, написанный текстом: один JSON-объект, можно в ограде ```json. Проверит его форма ответа."""
        try:
            parsed = json.loads(self._unfenced(text.strip()))
        except ValueError:
            return None
        return parsed if isinstance(parsed, dict) else None

    @classmethod
    def _unfenced(cls, text: str) -> str:
        """Тело ограды ```json … ``` без пробелов по краям; не ограда — текст как есть.

        Строками, а не регуляркой: `^```(?:json)?\\s*(.*?)\\s*```$` на незакрытой ограде с длинными пробелами
        перебирала взрывно (Sonar S8786; 4000 пробелов — 49 с).
        """
        fence = cls._FENCE
        if len(text) < 2 * len(fence) or not (text.startswith(fence) and text.endswith(fence)):
            return text
        return text[len(fence) : -len(fence)].removeprefix(cls._FENCE_TAG).strip()

    def _meta(self, turns: int, made: list[dict[str, object]], usage: Usage) -> dict[str, object]:
        return {
            "model": self._model.name, "num_turns": turns, "calls": made,
            "input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens, "cached_tokens": usage.cached_tokens,
        }
