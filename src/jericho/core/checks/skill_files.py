"""Правила файлов навыка: обязательное на месте, ручки вписаны и проверены тестами, у подстановок есть источник."""

from __future__ import annotations

import ast
from importlib import import_module
from pathlib import Path
from typing import Any

from jericho.core.checks.base import TESTS, CheckMessage, Project
from jericho.core.checks.imports import python_files
from jericho.core.prompting.template import placeholders
from jericho.core.tools.allowlist import Allowlist, AllowlistTool
from jericho.core.tools.tool import Tool


class RequiredFiles:
    """E001: у навыка есть `skill.py`, `SKILL.md`, `tests/` и хотя бы одно из двух — ручки или белый список."""

    def run(self, project: Project) -> list[CheckMessage]:
        messages: list[CheckMessage] = []
        for skill in project.skill_sources():
            missing = [item for item in ("skill.py", "SKILL.md", TESTS) if not (skill.directory / item).exists()]
            has_tools = any((skill.directory / item).exists() for item in ("tools.py", "tools", "allowlist.py"))
            messages += [CheckMessage("jericho.E001", skill.name, f"нет обязательного `{item}`") for item in missing]
            if not has_tools:
                text = "нет ни ручек (`tools`), ни белого списка (`allowlist.py`)"
                messages.append(CheckMessage("jericho.E001", skill.name, text))
        return messages


class ToolsAreListed:
    """E006: каждая ручка из `tools/` и каждый белый список из `allowlist.py` вписаны в `tools()` навыка."""

    def run(self, project: Project) -> list[CheckMessage]:
        messages: list[CheckMessage] = []
        for skill in project.skill_sources():
            package = skill.package
            listed = project.skills.tools_of(skill.name)
            listed_types = {type(tool) for tool in listed}
            listed_allowlists = {id(tool.allowlist) for tool in listed if isinstance(tool, AllowlistTool)}
            for tool_class in self._declared_tools(skill.directory, package):
                if tool_class not in listed_types:
                    messages.append(CheckMessage("jericho.E006", skill.name, f"ручка `{tool_class.__name__}` не вписана в `tools()`"))
            for name, allowlist in self._declared_allowlists(skill.directory, package):
                if id(allowlist) not in listed_allowlists:
                    messages.append(CheckMessage("jericho.E006", skill.name, f"белый список `{name}` не вписан в `tools()`"))
        return messages

    @staticmethod
    def _declared_tools(directory: Path, package: str) -> list[type[Tool[Any]]]:
        tools_dir, tools_file = directory / "tools", directory / "tools.py"
        modules = [f"{package}.tools.{file.stem}" for file in sorted(tools_dir.glob("*.py"))] if tools_dir.is_dir() else []
        modules += [f"{package}.tools"] if tools_file.exists() else []
        return [
            value
            for module in modules
            for value in vars(import_module(module)).values()
            if isinstance(value, type) and issubclass(value, Tool) and value.__module__ == module
        ]

    @staticmethod
    def _declared_allowlists(directory: Path, package: str) -> list[tuple[str, Allowlist]]:
        if not (directory / "allowlist.py").exists():
            return []
        module = import_module(f"{package}.allowlist")
        return [(name, value) for name, value in vars(module).items() if isinstance(value, Allowlist)]


class GuidePlaceholders:
    """E007: у каждой подстановки `{{имя}}` в `SKILL.md` есть источник в `contexts()` навыка."""

    def run(self, project: Project) -> list[CheckMessage]:
        messages: list[CheckMessage] = []
        for skill in project.skills:
            guide = skill.directory / "SKILL.md"
            if not guide.exists():
                continue   # об этом скажет E001
            provided = {name for context in skill.contexts() for name in context.values()}
            used = placeholders(guide.read_text(encoding="utf-8"))
            for name in sorted(used - provided):
                messages.append(CheckMessage("jericho.E007", skill.name, f"в `SKILL.md` подстановка `{{{{{name}}}}}`, а источника нет"))
        return messages


class ToolsAreTested:
    """E012: класс каждой ручки навыка **используется в коде** его тестов — не только упомянут.

    Имя в комментарии или неиспользованный импорт не в счёт (ревью R12): нужен вызов или создание ручки
    в теле теста. Это проверка наличия теста, а не того, что тест проверяет нужное свойство. Файл в файл
    правило не требует: несколько ручек одного адаптера часто проверяются вместе. Белые списки не в счёт:
    это данные, их ручку проверяет сам каркас.
    """

    def run(self, project: Project) -> list[CheckMessage]:
        messages: list[CheckMessage] = []
        for skill in project.skills:
            used = self._used_names(skill.directory / "tests")
            for tool in skill.tools():
                name = type(tool).__name__
                if isinstance(tool, AllowlistTool) or name in used:
                    continue
                problem = f"ручку `{tool.name}` не проверяет ни один тест: класс `{name}` не используется в коде `tests/` — `starttool` кладёт заготовку"
                messages.append(CheckMessage("jericho.E012", skill.name, problem))
        return messages

    @staticmethod
    def _used_names(tests: Path) -> set[str]:
        """Имена, к которым тесты обращаются в коде: `Name` в выражениях, а не строки импорта и комментарии."""
        if not tests.is_dir():
            return set()
        used: set[str] = set()
        for file in python_files(tests):
            tree = ast.parse(file.read_text(encoding="utf-8"), filename=str(file))
            used.update(node.id for node in ast.walk(tree) if isinstance(node, ast.Name))
        return used
