"""Ручки ядра `remember` и `forget`: модель сама ведёт заметки о том, что повторяется."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, create_model

from jericho.core.services.confirmation import ConfirmationGate
from jericho.core.services.foreign import ForeignText
from jericho.core.tools.consent import require_consent
from jericho.core.tools.description import ToolDescription
from jericho.core.tools.request import ToolRequest
from jericho.core.tools.result import ToolRefusal, ToolResult
from jericho.core.tools.risk import Risk
from jericho.core.tools.session import CallSession
from jericho.core.tools.tool import Tool
from jericho.modules.notes.evidence import Evidence
from jericho.modules.notes.notebook import Notebook

NAME = r"^[\w][\w .,«»\"'-]*$"      # слова пользователя: буквы, цифры, пробелы и немного знаков — без переводов строк


class RememberRequest(ToolRequest):
    skill: str
    kind: str
    name: str = Field(
        min_length=2,
        max_length=40,
        pattern=NAME,
        description="Как это называет пользователь, его словами и коротко: «сайт курса», «назир», «рабочий проект».",
    )
    value: str = Field(
        min_length=1,
        max_length=200,
        description="Что за этим стоит — строго по образцу вида: адрес, идентификатор, надпись. Не фраза и не совет.",
    )


class ForgetRequest(ToolRequest):
    skill: str
    name: str = Field(min_length=2, max_length=40, pattern=NAME, description="Имя заметки, как оно записано.")


def _skill_field(notebook: Notebook) -> Any:
    """Допустимые навыки известны только при запуске — это подключённые навыки."""
    names: Any = Literal[*notebook.skills]  # pyright: ignore[reportInvalidTypeForm]
    return names, Field(description="Навык, к которому относится заметка: с ним ты работал в этой фразе.")


def _kind_field(notebook: Notebook) -> Any:
    names: Any = Literal[*(kind.name for kind in notebook.kinds)]  # pyright: ignore[reportInvalidTypeForm]
    described = "; ".join(f"«{kind.name}» — {kind.description} Пример: {kind.example}" for kind in notebook.kinds)
    return names, Field(description=f"Вид заметки: {described}")


class Remember(Tool[RememberRequest]):
    """Записывает заметку навыка. Значение проходит две проверки, и обе держит код.

    Образец вида: адрес, имя из списка или короткая надпись — свободный текст не проходит. Доказательство:
    значение уже стояло в успешном вызове ручки — выдуманное и прочитанное на чужой странице не проходит.
    """

    name = "remember"
    risk = Risk.CHANGE
    service = True
    description = ToolDescription(
        when=(
            "после удачно выполненной просьбы, если в ней было то, что пользователь назовёт так же снова, а тебе "
            "пришлось это выяснять: адрес сайта по его названию, приложение по прозвищу, надпись на кнопке."
        ),
        does=(
            "сохраняет заметку «как называют → что это»; в следующих фразах она придёт вместе с руководством навыка. "
            "Заметка с тем же именем заменяется. Пользователь увидит в уведомлении, что именно ты запомнил."
        ),
        returns='{"ok": true, "remembered": имя, "value", "replaced": прежнее значение, если было; "unchanged": true — такая уже есть}.',
        refusals=(
            "skill_not_loaded — заметку пишут о навыке, с которым только что работали; "
            "invalid_value + pattern, example — значение не по образцу вида: исправь или не записывай; "
            "no_evidence — этим значением целиком не вызывалась успешно ни одна ручка: записывай ровно то, что сработало "
            "(тот же адрес, ту же надпись), или не записывай; "
            "notes_full + names — места нет: сначала forget ненужную; "
            "needs_confirm + name, value, read — в этой фразе ты читал чужой текст (страницу, список), заметка не "
            "записана: ответь clarify, назови имя и значение, после «да» в следующей фразе вызови confirm(); "
            "invalid_parameters + problems."
        ),
    )

    def __init__(
        self, notebook: Notebook, session: CallSession, evidence: Evidence, gate: ConfirmationGate, foreign: ForeignText
    ) -> None:
        self._notebook = notebook
        self._session = session
        self._evidence = evidence
        self._gate = gate
        self._foreign = foreign
        self.request_type = create_model(
            "RememberRequest", __base__=RememberRequest, skill=_skill_field(notebook), kind=_kind_field(notebook)
        )

    def _run(self, request: RememberRequest) -> ToolResult:
        if self._notebook.knows(request.skill, request.name, request.value):
            return ToolResult.success(remembered=request.name, value=request.value, unchanged=True)   # спрашивать не о чем
        arguments = request.model_dump()
        agreed = self._gate.has_consent(self.name, arguments, arguments)     # «да» из прошлой фразы на эту самую заметку
        if not agreed and not self._session.is_loaded(request.skill):
            raise ToolRefusal("skill_not_loaded", skill=request.skill)
        kind = self._notebook.kind(request.kind)
        if kind is None:        # вид проверен схемой запроса; сюда доходит только рассогласование в коде
            raise ToolRefusal("invalid_value", detail=f"нет вида {request.kind}")
        if not kind.accepts(request.value):
            raise ToolRefusal("invalid_value", pattern=kind.pattern, example=kind.example)
        if not self._evidence.supports(kind.name, request.value):
            raise ToolRefusal("no_evidence", value=request.value)
        if not self._notebook.has_room(request.skill, request.name):
            raise ToolRefusal("notes_full", names=[note.name for note in self._notebook.of(request.skill)])
        if not agreed:
            self._ask_if_foreign(request, arguments)
        replaced = self._notebook.remember(request.skill, kind.name, request.name, request.value)
        if replaced is None:
            return ToolResult.success(remembered=request.name, value=request.value)
        return ToolResult.success(remembered=request.name, value=request.value, replaced=replaced.value)

    def _ask_if_foreign(self, request: RememberRequest, arguments: dict[str, Any]) -> None:
        """В этой фразе модель читала чужой текст — заметку пишем только после «да».

        Заметка живёт дольше фразы: указание со страницы, попав в неё, действовало бы во всех следующих.
        Образец и доказательство это сужают, но решить, что адрес «тот самый», может только пользователь.
        """
        if not self._foreign.sources:
            return
        summary = f"запомнить «{request.name}» → {request.value}"
        require_consent(
            self._gate, self.name, arguments, summary, arguments,
            name=request.name, value=request.value, read=sorted(self._foreign.sources),
        )


class Forget(Tool[ForgetRequest]):
    """Убирает заметку: она устарела, оказалась ошибкой, или пользователь попросил забыть."""

    name = "forget"
    risk = Risk.CHANGE
    service = True
    description = ToolDescription(
        when=(
            "пользователь просит забыть («забудь про сайт курса») или заметка подвела: по ней ручка вернула отказ, "
            "адрес больше не тот."
        ),
        does="удаляет одну заметку навыка по имени. load_skill для этого не нужен.",
        returns='{"ok": true, "forgotten": имя, "value": что за ним стояло}.',
        refusals="note_not_found + names — такой заметки нет, в names те, что есть; invalid_parameters + problems.",
    )

    def __init__(self, notebook: Notebook) -> None:
        self._notebook = notebook
        self.request_type = create_model("ForgetRequest", __base__=ForgetRequest, skill=_skill_field(notebook))

    def _run(self, request: ForgetRequest) -> ToolResult:
        gone = self._notebook.forget(request.skill, request.name)
        if gone is None:
            raise ToolRefusal("note_not_found", names=[note.name for note in self._notebook.of(request.skill)])
        return ToolResult.success(forgotten=gone.name, value=gone.value)
