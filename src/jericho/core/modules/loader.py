"""Поиск модулей ядра по списку `INSTALLED_MODULES`."""

from __future__ import annotations

from collections.abc import Sequence

from jericho.core.discovery import PartLoader, repeated
from jericho.core.modules.config import ModuleConfig
from jericho.core.modules.registry import InstalledModules, ModuleError


class ModuleLoader:
    """Превращает список пакетов в модули: в каждом пакете ищет `module.py` и в нём один класс модуля."""

    _PARTS = PartLoader(ModuleConfig, "module", ModuleError)

    def load(self, installed: Sequence[str]) -> InstalledModules:
        modules = [(package, self._PARTS.load(package)) for package in installed]
        twice = repeated(module.name for _, module in modules)
        if twice:
            raise ModuleError(f"module names are not unique: {', '.join(twice)}")
        return InstalledModules(modules)
