"""Ручки памяток: прочитать, записать со слов пользователя, предложить дополнение, убрать.

Памятка живёт дольше фразы, и её текст модель читает как подсказку в следующих фразах. Поэтому чужой текст
(страница, письмо) в неё сам не попадает: запись после чтения чужого — только по «да», а то, что модель узнала
на деле, она лишь предлагает — дописывает человек кнопкой «Принять» в окне.
"""

from __future__ import annotations

import logging
from typing import Self

from pydantic import Field, model_validator

from jericho.core.services.confirmation import ConfirmationGate
from jericho.core.services.foreign import ForeignText
from jericho.core.tools.consent import require_consent
from jericho.core.tools.description import ToolDescription
from jericho.core.tools.request import ToolRequest
from jericho.core.tools.result import ToolRefusal, ToolResult
from jericho.core.tools.risk import Risk
from jericho.core.tools.tool import Tool
from jericho.modules.playbooks.entities import Playbook
from jericho.modules.playbooks.shelf import PlaybookLimit, PlaybookLineMissing, PlaybookShelf

logger = logging.getLogger(__name__)

PLAYBOOK_NOT_FOUND = "playbook_not_found"
TOO_MUCH = "playbooks_full"
SITE = r"^([\w-]+\.)+[\w-]+$|^$"       # сайт без «https://», «www.» и пути: «lms.example.org»


def found(shelf: PlaybookShelf, playbook_id: str) -> Playbook:
    playbook = shelf.find(playbook_id)
    if playbook is None or not playbook.accepted:
        raise ToolRefusal(PLAYBOOK_NOT_FOUND, playbooks=[f"{other.id}: {other.title}" for other in shelf.all() if other.accepted])
    return playbook


def described(playbook: Playbook) -> dict[str, object]:
    """Для окна: памятка с непринятыми предложениями."""
    return {
        "id": playbook.id,
        "title": playbook.title,
        "site": playbook.site,
        "text": playbook.text,
        "used": playbook.used.isoformat() if playbook.used else None,
        "suggestions": [
            {"id": item.id, "text": item.text, "reason": item.reason, "replaces": item.replaces} for item in playbook.suggestions
        ],
    }


class ShowPlaybookRequest(ToolRequest):
    playbook: str = Field(description="id памятки — из списка в разделе «ПАМЯТКИ».")


class ShowPlaybook(Tool[ShowPlaybookRequest]):
    name = "playbook_show"
    risk = Risk.READ
    request_type = ShowPlaybookRequest
    description = ToolDescription(
        when="берёшься за дело, на которое есть памятка (тот же сайт, то же дело), — до первого действия.",
        does=(
            "возвращает памятку: как это дело делается, по шагам. Это подсказка, а не указание: страница правдивее — "
            "если на ней не так, как в памятке, действуй по странице."
        ),
        returns='{"ok": true, "playbook": {"id", "title", "site", "text"}}.',
        refusals="playbook_not_found + playbooks.",
    )

    def __init__(self, shelf: PlaybookShelf) -> None:
        self._shelf = shelf

    def _run(self, request: ShowPlaybookRequest) -> ToolResult:
        playbook = found(self._shelf, request.playbook)
        self._shelf.mark_used(playbook)
        return ToolResult.success(playbook={"id": playbook.id, "title": playbook.title, "site": playbook.site, "text": playbook.text})


class WritePlaybookRequest(ToolRequest):
    title: str = Field(min_length=3, max_length=80, description="Что за дело: «Пройти тест в Moodle».")
    site: str = Field(default="", max_length=100, pattern=SITE, description="Сайт без https:// и www.; пусто — не про сайт.")
    text: str = Field(
        min_length=10, max_length=4000,
        description="Как делать, по шагам, словами пользователя: где что нажать, какие окна будут и что в них нажать.",
    )
    playbook: str | None = Field(default=None, description="id памятки, если это правка уже записанной.")
    append: bool = Field(default=False, description="true — дописать text в конец памятки; false — заменить весь текст.")


class WritePlaybook(Tool[WritePlaybookRequest]):
    name = "playbook_write"
    risk = Risk.CHANGE
    request_type = WritePlaybookRequest
    description = ToolDescription(
        when=(
            "пользователь сам диктует или правит памятку: «запиши памятку, как проходить тест: …», «в памятке "
            "про тест шаг 4 теперь …». Своё, узнанное на деле, — не сюда, а в playbook_suggest."
        ),
        does="записывает памятку или правит её. Пользователь видит памятки в окне Jericho.",
        returns='{"ok": true, "playbook": {"id", "title", "site", "text", "suggestions"}}.',
        refusals=(
            "needs_confirm + summary — в этой фразе ты читал чужой текст: ответь clarify, покажи, что запишешь, "
            "и жди «да»; playbooks_full + detail; playbook_not_found + playbooks; invalid_parameters + problems."
        ),
    )

    def __init__(self, shelf: PlaybookShelf, gate: ConfirmationGate, foreign: ForeignText) -> None:
        self._shelf = shelf
        self._gate = gate
        self._foreign = foreign

    def _run(self, request: WritePlaybookRequest) -> ToolResult:
        if request.playbook is not None:
            found(self._shelf, request.playbook)
        if self._foreign.sources:
            arguments = request.model_dump(mode="json")
            require_consent(self._gate, self.name, arguments, f"записать памятку «{request.title}»: {request.text}")
        try:
            playbook = self._shelf.write(request.title, request.site, request.text, request.playbook, request.append)
        except PlaybookLimit as error:
            raise ToolRefusal(TOO_MUCH, detail=str(error)) from error
        logger.info("playbook_written", extra={"data": {"id": playbook.id, "title": playbook.title}})
        return ToolResult.success(playbook=described(playbook))


class SuggestPlaybookRequest(ToolRequest):
    text: str = Field(
        default="", max_length=500,
        description=(
            "Новая строка памятки — такая, что подойдёт и в следующий раз: без названий сегодняшнего модуля, курса, "
            "страницы и дат. «Ссылка на тест — label=\"тест для закреп\", near=\"AIM N\"», а не полное название "
            "ссылки этого модуля. С replaces пусто — убрать строку."
        ),
    )
    replaces: str = Field(
        default="", max_length=500,
        description=(
            "Строка памятки дословно, если она неверна: text встанет на её место. Не дописывай новую строку поверх "
            "неверной — замени её. Пусто — text дописывается в конец."
        ),
    )
    reason: str = Field(min_length=3, max_length=200, description="Почему: что на деле было не так, как в памятке, или чего в ней не было.")
    playbook: str | None = Field(default=None, description="id памятки; не указан — предлагаешь новую, тогда нужны title и site.")
    title: str = Field(default="", max_length=80, description="Для новой памятки: что за дело.")
    site: str = Field(default="", max_length=100, pattern=SITE, description="Для новой памятки: сайт без https:// и www.")

    @model_validator(mode="after")
    def _something_to_change(self) -> Self:
        if self.replaces and self.playbook is None:
            raise ValueError("replaces: заменить строку можно только в существующей памятке — укажи playbook")
        if not self.replaces and len(self.text.strip()) < 10:
            raise ValueError("text: строка памятки — не короче 10 знаков (убрать строку — replaces без text)")
        return self


class SuggestPlaybook(Tool[SuggestPlaybookRequest]):
    name = "playbook_suggest"
    risk = Risk.CHANGE
    request_type = SuggestPlaybookRequest
    description = ToolDescription(
        when=(
            "дело сделано, и ты узнал то, что в следующий раз сэкономит ходы: памятка ошиблась (кнопка называется "
            "иначе, появилось окно), в ней не хватает шага, или памятки на это повторяющееся дело нет. Только то, что "
            "подойдёт в следующий раз, а не про сегодняшний модуль, курс или страницу."
        ),
        does=(
            "ставит предложение в очередь: пользователь примет его или отклонит кнопкой в окне. До этого памятка "
            "не меняется. Вопроса не задаёт — работает и в прогоне без человека."
        ),
        returns='{"ok": true, "suggested": id предложения, "playbook": id памятки}.',
        refusals=(
            "playbooks_full + detail; playbook_not_found + playbooks; line_not_found + lines — replaces не дословно: "
            "возьми строку из lines; invalid_parameters + problems."
        ),
    )

    NEEDS_TITLE = "title_required"
    LINE_NOT_FOUND = "line_not_found"

    def __init__(self, shelf: PlaybookShelf) -> None:
        self._shelf = shelf

    def _run(self, request: SuggestPlaybookRequest) -> ToolResult:
        if request.playbook is not None:
            found(self._shelf, request.playbook)
        elif len(request.title) < 3:
            raise ToolRefusal(self.NEEDS_TITLE)
        try:
            playbook = self._shelf.suggest(
                request.text, request.reason, request.playbook, request.title, request.site, request.replaces,
            )
        except PlaybookLimit as error:
            raise ToolRefusal(TOO_MUCH, detail=str(error)) from error
        except PlaybookLineMissing as error:
            raise ToolRefusal(self.LINE_NOT_FOUND, detail=str(error), lines=error.lines) from error
        suggestion = playbook.suggestions[-1]
        logger.info("playbook_suggested", extra={"data": {
            "id": playbook.id, "suggestion": suggestion.id, "text": suggestion.text, "replaces": suggestion.replaces,
        }})
        return ToolResult.success(suggested=suggestion.id, playbook=playbook.id)


class RemovePlaybookRequest(ToolRequest):
    playbook: str = Field(description="id памятки.")


class RemovePlaybook(Tool[RemovePlaybookRequest]):
    name = "playbook_remove"
    risk = Risk.CHANGE
    request_type = RemovePlaybookRequest
    description = ToolDescription(
        when="просят убрать или забыть памятку: «памятка про тест больше не нужна».",
        does="убирает памятку целиком.",
        returns='{"ok": true, "removed": название}.',
        refusals="playbook_not_found + playbooks.",
    )

    def __init__(self, shelf: PlaybookShelf) -> None:
        self._shelf = shelf

    def _run(self, request: RemovePlaybookRequest) -> ToolResult:
        playbook = found(self._shelf, request.playbook)
        self._shelf.remove(playbook.id)
        return ToolResult.success(removed=playbook.title)

