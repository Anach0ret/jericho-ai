"""Слои по списку из настроек: `пакет.модуль.Класс` → сам класс."""

from __future__ import annotations

from collections.abc import Sequence
from importlib import import_module
from typing import cast

from jericho.core.tools.dispatcher import ToolMiddleware


class MiddlewareLoadError(Exception):
    """Слой из `TOOL_MIDDLEWARE` не нашёлся или не годится в слои."""


class MiddlewareLoader:
    """Находит слои по их полным именам, в том же порядке."""

    def load(self, paths: Sequence[str]) -> tuple[ToolMiddleware, ...]:
        return tuple(self._layer(path) for path in paths)

    @staticmethod
    def _layer(path: str) -> ToolMiddleware:
        module_name, _, name = path.rpartition(".")
        try:
            layer = getattr(import_module(module_name), name)
        except (ImportError, AttributeError, ValueError) as error:
            raise MiddlewareLoadError(f"{path}: not found") from error
        if not callable(layer):
            raise MiddlewareLoadError(f"{path}: not callable")
        return cast(ToolMiddleware, layer)
