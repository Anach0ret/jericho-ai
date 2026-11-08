"""Подстановки `{{имя}}` в текстах для модели."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

from jericho.core.prompting.protocols import PromptContext

_PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")


def render(text: str, values: Mapping[str, str]) -> str:
    """Заменяет каждое `{{имя}}` значением; неизвестное имя — пустой строкой."""
    return _PLACEHOLDER.sub(lambda match: values.get(match.group(1), ""), text)


def placeholders(text: str) -> set[str]:
    """Имена всех подстановок в тексте."""
    return set(_PLACEHOLDER.findall(text))


def values_of(contexts: Iterable[PromptContext]) -> dict[str, str]:
    """Подстановки всех источников вместе; одно имя у двух источников — побеждает последний."""
    values: dict[str, str] = {}
    for context in contexts:
        values.update(context.values())
    return values
