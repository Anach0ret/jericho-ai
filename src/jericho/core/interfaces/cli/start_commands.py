"""Команды заготовок: новый проект, навык, ручка и служба."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path

from jericho.core.management.scaffold import ProjectScaffold, Scaffold, ScaffoldError


class StartSkillCommand:
    name = "startskill"
    help = "создать заготовку навыка: skill.py, SKILL.md, tools/, tests/"

    def __init__(self, scaffold: Scaffold, skills_package: str, command: str = "jericho") -> None:
        self._scaffold = scaffold
        self._skills_package = skills_package
        self._command = command

    def configure(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("skill", help="имя навыка: латинские строчные буквы, например media")
        default = "одной строкой: когда этот навык нужен."
        parser.add_argument("--description", default=default, help="описание для списка навыков")

    def run(self, args: argparse.Namespace) -> None:
        _create(lambda: self._scaffold.skill(args.skill, args.description))
        print(f"\nДальше: опиши навык в SKILL.md, добавь ручку (`{self._command} starttool {args.skill} <имя>`)")
        print(f'и подключи навык — строка "{self._skills_package}.{args.skill}" в INSTALLED_SKILLS (settings/base.py).')


class StartToolCommand:
    name = "starttool"
    help = "создать заготовку ручки в навыке: файл ручки, файл её тестов, строка в шапке SKILL.md"

    def __init__(self, scaffold: Scaffold, command: str = "jericho") -> None:
        self._scaffold = scaffold
        self._command = command

    def configure(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("skill", help="имя навыка")
        parser.add_argument("tool", help="имя ручки, как её вызовет модель: например play_pause")

    def run(self, args: argparse.Namespace) -> None:
        _create(lambda: self._scaffold.tool(args.skill, args.tool))
        print("\nДальше: впиши ручку в `tools()` в skill.py — там её нужно собрать с зависимостями.")
        print(f"Забудешь — напомнит `{self._command} check`.")


class StartServiceCommand:
    name = "startservice"
    help = "создать заготовку службы: протокол, адаптер, service.py, подмена для тестов"

    def __init__(self, scaffold: Scaffold, services_package: str, command: str = "jericho") -> None:
        self._scaffold = scaffold
        self._services_package = services_package
        self._command = command

    def configure(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("service", help="имя службы: латинские строчные буквы, например windows")

    def run(self, args: argparse.Namespace) -> None:
        _create(lambda: self._scaffold.service(args.service))
        print(f'\nДальше: опиши протокол и адаптер и подключи службу — строка "{self._services_package}.{args.service}"')
        print("в INSTALLED_SERVICES (settings/base.py). Навык берёт её так: `requires = (Протокол,)` и")
        print(f"`core.shared.get(Протокол)` в `ready()`. Проверить: `{self._command} check`.")


class StartProjectCommand:
    """Команда самого каркаса: ей не нужен проект — она его создаёт."""

    name = "startproject"
    help = "создать проект ассистента: точка входа, настройки, роль, папки навыков и служб, AGENTS.md"

    def __init__(self, scaffold: ProjectScaffold, parent: Path) -> None:
        self._scaffold = scaffold
        self._parent = parent

    def configure(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("project", help="имя проекта и его папки: латинские строчные буквы, цифры и дефис")
        parser.add_argument(
            "directory", nargs="?", help="куда создать: «.» — в текущую пустую папку; не задано — в новую папку с именем проекта"
        )

    def run(self, args: argparse.Namespace) -> None:
        directory = (self._parent / args.directory).resolve() if args.directory else None
        _create(lambda: self._scaffold.project(args.project, self._parent, directory))
        command = args.project.replace("-", "_")
        place = "" if args.directory == "." else f"cd {args.directory or args.project} && "
        print(f"\nДальше: {place}uv sync && uv run pytest -q && uv run {command} ask \"привет\"")
        print("Как наполнять проект — в его AGENTS.md.")


def _create(make: Callable[[], list[Path]]) -> None:
    try:
        created = make()
    except ScaffoldError as error:
        sys.exit(f"jericho: {error}")
    print("Создано и изменено:")
    for file in created:
        print(f"  {file}")
