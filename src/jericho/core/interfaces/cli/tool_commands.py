"""Команды инструментов: вызвать инструмент руками, как его вызовет модель."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from types import NoneType, UnionType
from typing import Annotated, Any, Literal, Union, get_args, get_origin

from pydantic.fields import FieldInfo

from jericho.core.tools.dispatcher import ToolDispatcher
from jericho.core.tools.tool import Tool


class ToolCommand:
    """Команда для одной ручки. Аргументы строятся из полей её запроса — отдельно их описывать не нужно.

    Обязательное поле — позиционный аргумент, остальные — флаги: `open-app telegram --workspace 7`.
    Проверку значений делает диспетчер, тот же, что и при вызове от модели.
    """

    def __init__(self, tool: Tool[Any], dispatcher: ToolDispatcher) -> None:
        self._tool = tool
        self._dispatcher = dispatcher
        self.name = tool.name.replace("_", "-")
        self.help = f"инструмент {tool.name}, как его вызовет модель"

    def configure(self, parser: argparse.ArgumentParser) -> None:
        parser.description = self._plain(self._tool.description.render())
        parser.formatter_class = argparse.RawDescriptionHelpFormatter
        for name, field in self._tool.request_type.model_fields.items():
            self._add_argument(parser, name, field)

    def run(self, args: argparse.Namespace) -> None:
        given = {name: getattr(args, name) for name in self._tool.request_type.model_fields}
        arguments = {name: value for name, value in given.items() if value is not None}   # не названо — значит, умолчание
        print(json.dumps(self._dispatcher.call(self._tool, arguments).to_dict(), ensure_ascii=False))

    def _add_argument(self, parser: argparse.ArgumentParser, name: str, field: FieldInfo) -> None:
        """Логическое — `--x`/`--no-x` (обязательное — `да`/`нет`), список — несколько значений, сложное — JSON.

        Раньше обязательное логическое шло через `bool(строка)` — «false» становилось True, а `list[int]` получал
        одно число вместо списка (ревью 02.11.2026, П1 №8).
        """
        required, annotation = field.is_required(), self._value(field.annotation)
        options: dict[str, Any] = {} if required else {"dest": name, "default": None}
        if annotation is bool:
            options |= {"type": self._boolean, "metavar": "да|нет"} if required else {"action": argparse.BooleanOptionalAction}
        elif get_origin(annotation) in (list, tuple, set, frozenset):
            options |= {"nargs": "+", "type": self._scalar(self._value(next(iter(get_args(annotation)), str)))}
        else:
            options |= {"type": self._scalar(annotation)}
        names = (name,) if required else (f"--{name.replace('_', '-')}",)
        parser.add_argument(*names, help=self._plain(field.description or ""), **options)

    @staticmethod
    def _plain(text: str) -> str:
        """Текст для справки как он есть: `argparse` читает «%» как начало подстановки («10%+» ломало весь разбор)."""
        return text.replace("%", "%%")

    @staticmethod
    def _value(annotation: Any) -> Any:
        """Сам тип значения: у `int | None` это `int`, у `Literal["a", "b"]` — тип его вариантов, у
        `Annotated[str, Field(...)]` — `str` (шаги `plan_create`: без этого строка уходила в `json.loads`)."""
        if get_origin(annotation) is Annotated:
            return ToolCommand._value(get_args(annotation)[0])
        if get_origin(annotation) is Literal:
            return type(get_args(annotation)[0])
        if get_origin(annotation) in (Union, UnionType):
            kinds = [kind for kind in get_args(annotation) if kind is not NoneType]
            return kinds[0] if kinds else annotation
        return annotation

    @staticmethod
    def _scalar(annotation: Any) -> Callable[[str], object]:
        """Как разобрать одно значение: строка, число — как есть; словарь, модель и прочее — JSON (проверит диспетчер)."""
        return annotation if annotation in (str, int, float) else json.loads

    @staticmethod
    def _boolean(text: str) -> bool:
        said = text.strip().casefold()
        if said in {"да", "yes", "true", "1", "on"}:
            return True
        if said in {"нет", "no", "false", "0", "off"}:
            return False
        raise argparse.ArgumentTypeError(f"«{text}»: нужно да или нет")
