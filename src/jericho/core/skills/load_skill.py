"""Ручка ядра `load_skill` и то, что модель видит о ручках навыка до его загрузки."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal

from pydantic import Field, create_model

from jericho.core.skills.guide import SkillGuides
from jericho.core.tools.description import ToolDescription
from jericho.core.tools.request import ToolRequest
from jericho.core.tools.result import ToolResult
from jericho.core.tools.risk import Risk
from jericho.core.tools.session import CallSession
from jericho.core.tools.tool import Tool


class LoadSkillRequest(ToolRequest):
    names: list[str]


class LoadSkill(Tool[LoadSkillRequest]):
    """Отдаёт модели руководство навыка и отмечает навык загруженным на эту фразу."""

    name = "load_skill"
    risk = Risk.READ
    service = True
    description = ToolDescription(
        when="фраза относится к одному или нескольким навыкам из списка — первым ходом, до любой их ручки.",
        does=(
            "возвращает руководства названных навыков: правила, списки (приложения, проекты), текущее состояние "
            "и полные описания ручек. После этого ручки этих навыков можно вызывать. Нужны два навыка — "
            "назови оба в одном вызове."
        ),
        returns='{"ok": true, "guides": {имя навыка: текст руководства}}.',
        refusals="invalid_parameters + problems — такого навыка нет в списке или список пуст.",
    )

    def __init__(self, guides: SkillGuides, session: CallSession, skills: Sequence[str]) -> None:
        self._guides = guides
        self._session = session
        # Допустимые имена известны только при запуске — это подключённые навыки, — поэтому тип собирается здесь.
        names: Any = list[Literal[*skills]]  # pyright: ignore[reportInvalidTypeForm]
        description = "Имена навыков из списка навыков — все, что нужны для этой фразы."
        self.request_type = create_model(
            "LoadSkillRequest",
            __base__=LoadSkillRequest,
            names=(names, Field(min_length=1, description=description)),
        )

    def _run(self, request: LoadSkillRequest) -> ToolResult:
        names = list(dict.fromkeys(request.names))     # повтор имени не должен удвоить руководство
        guides = {name: self._guides.guide(name) for name in names}
        for name in names:
            self._session.load(name)
        return ToolResult.success(guides=guides)


def brief_description(tool: Tool[Any]) -> str:
    """Что модель читает о ручке в списке ручек: у ручки навыка — одна строка, полное описание придёт с навыком.

    Навык, чьё руководство уже в общем промпте, — сразу полное описание: загружать нечего.
    """
    if not tool.skill or tool.in_prompt:
        return tool.description.render()
    return (
        f"Ручка навыка `{tool.skill}`. Сначала вызови {LoadSkill.name}(names=[\"{tool.skill}\"]): в ответе — её описание "
        "и правила навыка. Без этого вызов вернёт отказ skill_not_loaded."
    )
