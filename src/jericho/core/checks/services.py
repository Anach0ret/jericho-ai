"""Правило служб: в службе нет ручек — действия для модели объявляет навык."""

from __future__ import annotations

import ast
from pathlib import Path

from jericho.core.checks.base import CheckMessage, Project, in_tests
from jericho.core.checks.imports import python_files


class NoToolsInServices:
    """E013: в службе нет ручек — ни своих классов-наследников `Tool`, ни белых списков.

    Модель о службе не знает: действия для неё объявляет навык, который службой пользуется. Ручку службы
    некуда подключить, поэтому её появление — признак того, что код положен не в тот слой.
    """

    _BASES = frozenset({"Tool", "AllowlistTool", "Allowlist"})

    def run(self, project: Project) -> list[CheckMessage]:
        messages: list[CheckMessage] = []
        for directory in project.service_dirs():
            for file in python_files(directory):
                if in_tests(file, directory):
                    continue
                for name in self._tools(file):
                    text = f"в службе ручка `{name}`: действие для модели объявляет навык, служба только даёт доступ"
                    messages.append(CheckMessage("jericho.E013", project.location(file), text))
        return messages

    def _tools(self, file: Path) -> list[str]:
        tree = ast.parse(file.read_text(encoding="utf-8"), filename=str(file))
        found = [node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef) and self._BASES & set(map(self._base, node.bases))]
        calls = [
            node.func.id for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Allowlist"
        ]
        return found + calls

    @staticmethod
    def _base(node: ast.expr) -> str:
        if isinstance(node, ast.Subscript):
            node = node.value
        if isinstance(node, ast.Attribute):
            return node.attr
        return node.id if isinstance(node, ast.Name) else ""
