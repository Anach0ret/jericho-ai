"""Все ручки ассистента в одном месте — чтобы о них можно было спросить, не собирая заново."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, Any

from jericho.core.tools.tool import Tool

if TYPE_CHECKING:   # каталог знает о диспетчере только по имени типа: диспетчер собирается из тех же ручек
    from jericho.core.tools.dispatcher import ToolDispatcher
    from jericho.core.tools.result import ToolResult


class ToolCatalog:
    """Заполняется при сборке ручек; до этого пуст. Спрашивают его уже во время вызова.

    Нужен тем, кому важно знать о ручках соседей: например, чтобы отличить служебные вызовы от дела.
    """

    def __init__(self) -> None:
        self._tools: tuple[Tool[Any], ...] = ()
        self._dispatcher: ToolDispatcher | None = None

    def fill(self, tools: Iterable[Tool[Any]], dispatcher: ToolDispatcher | None = None) -> None:
        self._tools = tuple(tools)
        self._dispatcher = dispatcher

    def get(self, name: str) -> Tool[Any] | None:
        return next((tool for tool in self._tools if tool.name == name), None)

    def call(self, name: str, arguments: Mapping[str, object]) -> ToolResult:
        """Вызвать ручку по имени тем же диспетчером, что и модель: слои, политика риска, срок, журнал.

        Для модулей, которые сами составляют вызовы (сценарии): так у них не больше прав, чем у фразы.
        Навык ручки помечается загруженным — руководство нужно модели, а тут вызов составил человек.
        """
        tool = self.get(name)
        if tool is None or self._dispatcher is None:
            raise LookupError(f"no tool '{name}' in the catalog")
        if tool.skill:
            self._dispatcher.session.load(tool.skill)
        return self._dispatcher.call(tool, arguments)

    @property
    def service(self) -> frozenset[str]:
        """Имена ручек, которые обслуживают работу, а не делают дело (`Tool.service`)."""
        return frozenset(tool.name for tool in self._tools if tool.service)
