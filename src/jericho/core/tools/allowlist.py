"""Ручка по белому списку: команду внешней программе пишет модель, границы держит ядро.

Навык описывает список как данные (`allowlist.py`) и даёт «консоль» — то, что выполнит уже проверенную
команду. Разбор, проверка и отказы с подсказкой — здесь, одинаково для всех таких ручек.
Правила, что можно вносить в список, — в docs/tool-rules.md.
"""

from __future__ import annotations

import shlex
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from pydantic import Field, create_model

from jericho.core.errors import PortError
from jericho.core.services.runner import CommandError, CommandRunner
from jericho.core.tools.description import ToolDescription
from jericho.core.tools.request import ToolRequest
from jericho.core.tools.result import ToolRefusal, ToolResult
from jericho.core.tools.risk import Risk
from jericho.core.tools.tool import Tool


@dataclass(frozen=True, slots=True)
class CommandRule:
    """Одна разрешённая команда: с чего она начинается и что о ней известно."""

    prefix: tuple[str, ...]                # начало команды: («clients»,) или («dispatch», «workspace»)
    reads: bool = False                    # только читает состояние; остальные что-то меняют
    takes_arguments: bool = True           # можно ли дописывать свои аргументы после начала
    flags: frozenset[str] = frozenset()    # что допустимо после начала, если своих аргументов нет

    @classmethod
    def reading(cls, *names: str, flags: Sequence[str] = ()) -> tuple[CommandRule, ...]:
        """Запросы состояния: одно слово и, возможно, флаги из списка."""
        return tuple(cls((name,), reads=True, takes_arguments=False, flags=frozenset(flags)) for name in names)

    @classmethod
    def changing(cls, command: str, *subcommands: str) -> tuple[CommandRule, ...]:
        """Действия: команда и её разрешённые подкоманды, дальше — аргументы модели."""
        return tuple(cls((command, subcommand)) for subcommand in subcommands)

    @classmethod
    def acting(cls, *prefix: str, takes_arguments: bool = True) -> CommandRule:
        """Действие с точным началом: `acting("next", takes_arguments=False)`, `acting("set-mute", "@SINK@")`."""
        return cls(tuple(prefix), takes_arguments=takes_arguments)

    def matches(self, arguments: Sequence[str]) -> bool:
        rest = arguments[len(self.prefix) :]
        fits = tuple(arguments[: len(self.prefix)]) == self.prefix
        return fits and (self.takes_arguments or all(argument in self.flags for argument in rest))

    @property
    def text(self) -> str:
        return " ".join(self.prefix)


@dataclass(frozen=True, slots=True)
class Allowlist:
    """Белый список одной программы. Всё, чего в нём нет, запрещено."""

    FORBIDDEN_CHARACTERS = (";", "\n", "\r")    # одна команда за вызов

    tool: str                          # имя ручки для модели
    program: str                       # слово, с которого модель может начать команду; оно отбрасывается
    description: ToolDescription
    command_description: str           # что модель читает о параметре `command`
    rules: tuple[CommandRule, ...]
    risk: Risk                         # класс риска ручки — по самой тяжёлой из разрешённых команд

    def parse(self, command: str) -> list[str]:
        """Строка от модели → аргументы. Разбор без shell: подстановки и «|» не работают."""
        try:
            arguments = shlex.split(command)
        except ValueError:
            raise ToolRefusal("unparsable_command") from None
        return arguments[1:] if arguments[:1] == [self.program] else arguments

    def rule_for(self, arguments: Sequence[str]) -> CommandRule:
        """Правило, под которое подходит команда; не подходит ни под одно — отказ с подсказкой."""
        if not arguments:
            raise ToolRefusal("empty_command", allowed=self._hint(""))
        if any(character in argument for argument in arguments for character in self.FORBIDDEN_CHARACTERS):
            raise ToolRefusal("forbidden_characters", detail="одна команда за вызов, без «;»")
        rule = next((rule for rule in self.rules if rule.matches(arguments)), None)
        if rule is None:
            raise ToolRefusal("command_not_allowed", allowed=self._hint(arguments[0]))
        return rule

    def _hint(self, first_word: str) -> list[str]:
        """Что разрешено: команды с тем же первым словом, а если таких нет — весь список."""
        related = [rule.text for rule in self.rules if rule.prefix[0] == first_word]
        return sorted(related or (rule.text for rule in self.rules))


class CommandConsole(Protocol):
    """Выполняет команду, уже проверенную по списку. Как именно — знает навык: это его программа."""

    def run(self, arguments: Sequence[str], rule: CommandRule) -> object:
        """Данные для модели, если команда читает состояние; для действия — ничего."""
        ...


class ProgramError(PortError):
    """Программа из белого списка не выполнила команду: не установлена, не ответила или завершилась с ошибкой."""

    code = "program_error"


class RunnerConsole:
    """Консоль для простой программы: запускает её с проверенными аргументами и возвращает вывод.

    Годится, когда вывод программы можно отдать модели как есть. Пометка «читает» из правила решает, выполнится
    ли команда вхолостую. Программе со своим форматом ответа (как `hyprctl`) навык пишет свою консоль.
    """

    def __init__(self, executable: Path, runner: CommandRunner) -> None:
        self._executable = str(executable)
        self._runner = runner

    def run(self, arguments: Sequence[str], rule: CommandRule) -> object:
        try:
            output = self._runner.run([self._executable, *arguments], reads=rule.reads)
        except CommandError as error:
            raise ProgramError(str(error)) from error
        return output if rule.reads else None


class AllowlistRequest(ToolRequest):
    command: str


class AllowlistTool(Tool[AllowlistRequest]):
    """Ручка, которую ядро строит по белому списку навыка."""

    def __init__(self, allowlist: Allowlist, console: CommandConsole) -> None:
        self.allowlist = allowlist
        self._console = console
        self.name = allowlist.tool
        self.risk = allowlist.risk
        self.description = allowlist.description
        self.request_type = create_model(
            f"{allowlist.tool.title()}Request",
            __base__=AllowlistRequest,
            command=(str, Field(description=allowlist.command_description)),
        )

    def _run(self, request: AllowlistRequest) -> ToolResult:
        arguments = self.allowlist.parse(request.command)
        rule = self.allowlist.rule_for(arguments)
        answer = self._console.run(arguments, rule)
        return ToolResult.success(result=answer) if rule.reads else ToolResult.success(done=" ".join(arguments))
