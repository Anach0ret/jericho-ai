"""Подключённые модули ядра как одно целое."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from jericho.core.agent.task import TaskLayer
from jericho.core.management.base import Command
from jericho.core.modules.config import ModuleConfig, ModuleServices
from jericho.core.prompting.protocols import PromptContext
from jericho.core.services.paths import Paths
from jericho.core.tools.dispatcher import ToolMiddleware
from jericho.core.tools.tool import Tool

if TYPE_CHECKING:
    from jericho.core.agent.handle_phrase import HandlePhrase
    from jericho.core.checks.base import Check


class ModuleError(Exception):
    """Модули подключены так, что работать не могут: нет нужного соседа или слой не назван."""


class InstalledModules:
    """Модули из `INSTALLED_MODULES` в порядке списка, каждый под именем своего пакета."""

    def __init__(self, modules: Sequence[tuple[str, ModuleConfig]] = ()) -> None:
        self._modules = dict(modules)
        self._tools: tuple[Tool[Any], ...] | None = None
        installed = {module.name for module in self._modules.values()}
        for package, module in self._modules.items():
            missing = [name for name in module.requires if name not in installed]
            if missing:
                raise ModuleError(f"{package}: requires module {', '.join(missing)} — add it to INSTALLED_MODULES")

    def __iter__(self) -> Iterator[ModuleConfig]:
        return iter(self._modules.values())

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(module.name for module in self)

    @property
    def packages(self) -> tuple[str, ...]:
        """Пакеты подключённых модулей — так они названы в настройках."""
        return tuple(self._modules)

    def ready(self, services: ModuleServices) -> None:
        for module in self:
            module.ready(services)

    def tools(self) -> tuple[Tool[Any], ...]:
        """Ручки модулей; каждый модуль собирает свои один раз."""
        if self._tools is None:
            self._tools = tuple(tool for module in self for tool in module.tools())
        return self._tools

    def layers(self, order: Sequence[str]) -> tuple[TaskLayer, ...]:
        """Слои вокруг поручения в порядке `TASK_MIDDLEWARE`; первый — самый внешний.

        Порядок — условие правильной работы, поэтому он не выводится из порядка модулей, а назван явно.
        Слой неподключённого модуля и слой, забытый в списке, — ошибка сборки, а не тихий пропуск.
        """
        unknown = [package for package in order if package not in self._modules]
        if unknown:
            raise ModuleError(f"TASK_MIDDLEWARE names {', '.join(unknown)} — not in INSTALLED_MODULES")
        layers = {package: module.task_layer() for package, module in self._modules.items()}
        forgotten = [package for package, layer in layers.items() if layer is not None and package not in order]
        if forgotten:
            raise ModuleError(f"{', '.join(forgotten)}: has a task layer — add it to TASK_MIDDLEWARE, or the layer will not run")
        without = [package for package in order if layers[package] is None]
        if without:
            raise ModuleError(f"TASK_MIDDLEWARE names {', '.join(without)} — the module has no task layer")
        return tuple(layer for package in order if (layer := layers[package]) is not None)

    def tool_layers(self) -> tuple[ToolMiddleware, ...]:
        return tuple(layer for module in self for layer in module.tool_layers())

    def contexts(self) -> tuple[PromptContext, ...]:
        return tuple(context for module in self for context in module.contexts())

    def guide_notes(self, skill: str) -> str:
        """Что модули дописывают в руководство навыка."""
        return "\n\n".join(notes for module in self if (notes := module.guide_notes(skill)))

    def commands(self, handle_phrase: HandlePhrase) -> tuple[Command, ...]:
        return tuple(command for module in self for command in module.commands(handle_phrase))

    def checks(self) -> tuple[Check, ...]:
        return tuple(check for module in self for check in module.checks())

    def statuses(self) -> dict[str, Mapping[str, object]]:
        """Части снимка `status` по именам модулей; модули, которым нечего показать, не попадают."""
        return {module.name: part for module in self if (part := module.status())}

    def eval_files(self, paths: Paths) -> tuple[Path, ...]:
        return tuple(file for module in self for file in module.eval_files(paths))