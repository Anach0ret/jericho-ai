"""Слой «навык загружен»: ручку навыка нельзя вызвать, пока модель не прочитала его руководство."""

from __future__ import annotations

from jericho.core.tools.dispatcher import CallHandler, ToolCall
from jericho.core.tools.result import ToolRefusal, ToolResult


class RequireLoadedSkill:
    """Отказывает `skill_not_loaded`, если ручку навыка вызвали до `load_skill` в этой фразе.

    Правило записано и в тексте ядра, но держит его код: идентификаторы приложений и правила навыка есть
    только в руководстве, без него модель угадывала бы. Ручки ядра слой пропускает.
    """

    def __init__(self, handle: CallHandler) -> None:
        self._handle = handle

    def __call__(self, call: ToolCall) -> ToolResult:
        skill = call.tool.skill
        if skill and not call.session.is_loaded(skill):
            raise ToolRefusal("skill_not_loaded", skill=skill, hint=f'сначала load_skill(names=["{skill}"])')
        return self._handle(call)
