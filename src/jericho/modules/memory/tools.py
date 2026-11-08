"""Ручки памяти: `memorize`, `recall`, `forget_memory`."""

from __future__ import annotations

import re

from pydantic import Field

from jericho.core.journal.user_words import UserWords
from jericho.core.services.confirmation import ConfirmationGate
from jericho.core.services.foreign import ForeignText
from jericho.core.tools.consent import require_consent
from jericho.core.tools.description import ToolDescription
from jericho.core.tools.request import ToolRequest
from jericho.core.tools.result import ToolRefusal, ToolResult
from jericho.core.tools.risk import Risk
from jericho.core.tools.tool import Tool
from jericho.modules.memory.book import MemoryBook


class MemorizeRequest(ToolRequest):
    text: str = Field(min_length=3, max_length=300, description="Слова пользователя из его фразы — дословно, без пересказа.")
    tags: list[str] = Field(min_length=1, max_length=6, description=(
        "2–5 тегов одним словом, строчными: о ком/чём («маша», «солнышко»), тема («люди», «стиль», «курс», «portfolio») "
        "и имя навыка, если запись про работу с ним («telegram») — тогда она придёт с руководством навыка."))


class RecallRequest(ToolRequest):
    words: list[str] = Field(min_length=1, max_length=8, description="Теги из облака точно («маша», «стиль») и основы слов для поиска в тексте («маш», «пятниц»).")


class ForgetMemoryRequest(ToolRequest):
    id: str = Field(pattern=r"^[0-9a-f]{6}$", description="id записи из recall.")


class Memorize(Tool[MemorizeRequest]):
    """Записывает, что пользователь сказал о себе, людях, делах. Текст — только его собственные слова (UserWords)."""

    name = "memorize"
    risk = Risk.CHANGE
    service = True
    request_type = MemorizeRequest
    description = ToolDescription(
        when=(
            "пользователь просит запомнить или объясняет то, что пригодится потом: кто есть кто («солнышко — это Маша»), "
            "как он хочет («с ней пишу тепло, со смайликами»), факты о себе и делах."
        ),
        does="сохраняет его слова с тегами; тот же текст уже есть — дополняет теги.",
        returns='{"ok": true, "id", "text", "tags", "new": была ли запись новой}.',
        refusals=(
            "not_said — этих слов не было в его фразах за последние 15 минут: бери кусок его фразы дословно; "
            "request_not_fact + hint — в тексте сама просьба («запомни, что это…»), а не то, что запомнить; "
            "needs_confirm + text — в этой фразе ты читал чужой текст: спроси «да», назвав запись; "
            "memory_full + candidates — память полна: назови пользователю кандидатов и спроси, что забыть; invalid_parameters."
        ),
    )

    def __init__(self, book: MemoryBook, words: UserWords, gate: ConfirmationGate, foreign: ForeignText) -> None:
        self._book = book
        self._words = words
        self._gate = gate
        self._foreign = foreign

    REQUEST = re.compile(r"^\s*(?:запомни|запиши|помни|remember)\b", re.IGNORECASE)

    def _run(self, request: MemorizeRequest) -> ToolResult:
        if self.REQUEST.match(request.text):
            # Журнал 30.10.2026: «<чат> запомни что это группа курса» → в память легло «запомни что это группа курса».
            raise ToolRefusal(
                "request_not_fact", text=request.text,
                hint="запиши то, что надо помнить, — его словами, без «запомни». Чат, сайт или приложение под своим "
                "названием («группа курса» → какой чат) — это заметка навыка (remember), а не память",
            )
        arguments = request.model_dump()
        agreed = self._gate.has_consent(self.name, arguments, arguments)
        if not agreed and not self._words.said(request.text):
            raise ToolRefusal("not_said", text=request.text)
        if not agreed and self._foreign.sources:
            # Запись живёт дольше фразы: после чужого текста — только с «да» пользователя.
            require_consent(self._gate, self.name, arguments, f"запомнить: «{request.text}»", arguments, text=request.text)
        memory, new = self._book.add(request.text, request.tags)
        return ToolResult.success(id=memory.id, text=memory.text, tags=list(memory.tags), new=new, memo=f"запомнил: {memory.text}")


class Recall(Tool[RecallRequest]):
    name = "recall"
    risk = Risk.READ
    service = True
    request_type = RecallRequest
    description = ToolDescription(
        when="во фразе есть то, о чём может быть запись (имя, тема из облака тегов памяти), а в руководстве её нет.",
        does="ищет записи по тегам (точно, бери из облака тегов) и по началу слов в тексте, до 5 лучших.",
        returns='{"ok": true, "found": [{"id", "text", "tags"}]} — пусто: ничего нет, не выдумывай.',
        refusals="invalid_parameters.",
    )

    def __init__(self, book: MemoryBook) -> None:
        self._book = book

    def _run(self, request: RecallRequest) -> ToolResult:
        found = self._book.search(request.words)
        return ToolResult.success(found=[{"id": m.id, "text": m.text, "tags": list(m.tags)} for m in found])


class ForgetMemory(Tool[ForgetMemoryRequest]):
    name = "forget_memory"
    risk = Risk.CHANGE
    service = True
    request_type = ForgetMemoryRequest
    description = ToolDescription(
        when="просят забыть запись памяти или она оказалась неверной.",
        does="удаляет запись по id (id — из recall).",
        returns='{"ok": true, "forgotten": текст}.',
        refusals="memory_not_found — такой записи нет: найди её через recall.",
    )

    def __init__(self, book: MemoryBook) -> None:
        self._book = book

    def _run(self, request: ForgetMemoryRequest) -> ToolResult:
        gone = self._book.forget(request.id)
        if gone is None:
            raise ToolRefusal("memory_not_found", id=request.id)
        return ToolResult.success(forgotten=gone.text)
