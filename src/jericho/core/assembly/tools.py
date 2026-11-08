"""Участок «ручки»: всё, что модель может вызвать, и цепочка слоёв, через которую идёт каждый вызов."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from jericho.core.assembly.skills import SkillSet
from jericho.core.assembly.state import State
from jericho.core.conf.settings import Settings
from jericho.core.discovery import repeated
from jericho.core.modules.registry import InstalledModules
from jericho.core.skills.load_skill import LoadSkill
from jericho.core.tools.catalog import ToolCatalog
from jericho.core.tools.confirm import Confirm
from jericho.core.tools.deadline import Deadline
from jericho.core.tools.dispatcher import ToolDispatcher, ToolMiddleware
from jericho.core.tools.loader import MiddlewareLoader
from jericho.core.tools.policy import RiskPolicy
from jericho.core.tools.session import CallSession
from jericho.core.tools.tool import Tool


@dataclass(frozen=True, slots=True)
class Toolset:
    tools: tuple[Tool[Any], ...]            # ручки ядра и навыков — всё, что сервер отдаёт модели
    dispatcher: ToolDispatcher              # вызовы этой фразы: навык нужно загрузить перед его ручками
    layers: Sequence[ToolMiddleware]
    tool_timeout: float                     # срок одного вызова ручки, секунд
    catalog: ToolCatalog                    # те же ручки для тех, кто спрашивает о них во время вызова

    @property
    def service(self) -> frozenset[str]:
        """Служебные ручки (`Tool.service`): в оценке фраз и в эпизодах журнала не дело."""
        return self.catalog.service

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(tool.name for tool in self.tools)

    def manual_dispatcher(self, loaded: Sequence[str]) -> ToolDispatcher:
        """Для вызова ручки из терминала: это проверка самой ручки, навыки считаются загруженными."""
        return ToolDispatcher(self.layers, CallSession(loaded), Deadline(self.tool_timeout))


def build_toolset(settings: Settings, skills: SkillSet, modules: InstalledModules, state: State) -> Toolset:
    session = state.session                 # сервер ручек живёт одно поручение — и сеанс вместе с ним
    layers = (*MiddlewareLoader().load(settings.TOOL_MIDDLEWARE), *modules.tool_layers())     # слои модулей — ближе к ручке
    ceiling = settings.user_risk.get(state.user, settings.default_user_risk) if state.user else None
    policy = RiskPolicy(
        state.gate, settings.unattended_effects, settings.agent.private_backends, state.active_backend, ceiling, state.services.foreign,
    )
    dispatcher = ToolDispatcher(layers, session, Deadline(settings.tool_timeout), policy, state.phrase_deadline)
    skill_tools, module_tools = skills.installed.tools(), modules.tools()
    # Ассистент без навыков — тоже ассистент (новый проект, ассистент на одних модулях): загружать ему нечего.
    names = skills.installed.names
    load_skill = (LoadSkill(skills.guides, session, names),) if names else ()
    confirm = Confirm(state.gate, dispatcher, (*module_tools, *skill_tools), session)
    tools = (*load_skill, confirm, *module_tools, *skill_tools)
    _check_unique(tools)
    state.tools.fill(tools, dispatcher)
    return Toolset(tools, dispatcher, layers, settings.tool_timeout, state.tools)


def _check_unique(tools: Sequence[Tool[Any]]) -> None:
    """Одно имя — одна ручка на весь набор: ядро, модули, навыки. Иначе каталог брал первую, а сервер ручек — последнюю,
    и одно имя значило разное действие в разных интерфейсах (ревью 02.11.2026, П1 №7)."""
    twice = repeated(tool.name for tool in tools)
    if twice:
        owners = {name: [f"навык {tool.skill}" if tool.skill else "ядро или модуль" for tool in tools if tool.name == name] for name in twice}
        named = "; ".join(f"{name}: {', '.join(where)}" for name, where in owners.items())
        raise ValueError(f"tool names are not unique — {named}; rename one of them")
