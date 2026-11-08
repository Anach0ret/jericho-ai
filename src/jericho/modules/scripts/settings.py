"""Настройки модуля «сценарии»: именованные цепочки шагов, которые выполняются чётко и одинаково каждый раз."""

from __future__ import annotations

import re
from typing import Any, Self

from pydantic import Field, model_validator

from jericho.core.conf.settings import SettingsSection

NAME = r"^[\w-]{1,32}$"      # имя для `<проект> run <имя>` и для голоса: одно слово


class Step(SettingsSection):
    """Один шаг: вызов ручки с готовыми параметрами (без модели) — или фраза для модели, когда без неё не обойтись."""

    tool: str = ""                                          # имя ручки: open_project, open_url…
    arguments: dict[str, Any] = Field(default_factory=dict)  # параметры, как их прислала бы модель
    phrase: str = ""                                        # фраза для модели: «запиши меня на ближайшую лекцию курса»

    @model_validator(mode="after")
    def _one_kind(self) -> Self:
        if bool(self.tool) == bool(self.phrase):
            raise ValueError("step: exactly one of tool or phrase")
        if self.phrase and self.arguments:
            raise ValueError("step: arguments belong to a tool step, not to a phrase")
        return self

    @property
    def label(self) -> str:
        return self.tool or f"«{self.phrase}»"


class Script(SettingsSection):
    title: str = Field(min_length=1)                         # как сценарий видит человек: «Рабочее место»
    steps: tuple[Step, ...] = Field(min_length=1)

    @property
    def uses_model(self) -> bool:
        """Есть шаг-фраза: сценарий медленнее и может переспросить, зато умеет «найти актуальное»."""
        return any(step.phrase for step in self.steps)


class ScriptsSettings(SettingsSection):
    """Проект объявляет `scripts: ScriptsSettings = ScriptsSettings(items={...})` в своих настройках."""

    items: dict[str, Script] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _names_are_words(self) -> Self:
        for name in self.items:
            if not re.fullmatch(NAME, name):
                raise ValueError(f"scripts.items: name '{name}' must be one word (letters, digits, '-', '_')")
        return self
