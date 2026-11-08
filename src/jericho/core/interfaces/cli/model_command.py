"""Команда «модель»: какой моделью отвечает ассистент — показать, выбрать, вернуть по умолчанию."""

from __future__ import annotations

import argparse

from jericho.core.agent.model_choice import ModelChoiceFile, ModelChoices
from jericho.core.conf.settings import ModelChoice


class ModelCommand:
    name = "model"
    help = "модель ассистента: без имени — список; с именем — выбрать до «по умолчанию»; --reset — вернуть по умолчанию"

    def __init__(self, choices: ModelChoices, chosen: ModelChoiceFile) -> None:
        self._choices = choices
        self._chosen = chosen

    def configure(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("choice", nargs="?", choices=sorted(self._choices.choices) or None, help="имя модели из agent.models")
        parser.add_argument("--reset", action="store_true", help="вернуть модель по умолчанию — как в настройках")

    def run(self, args: argparse.Namespace) -> None:
        if not self._choices.choices:
            raise SystemExit("моделей на выбор нет: добавь их в agent.models настроек проекта")
        if args.reset:
            self._chosen.reset()
        elif args.choice:
            self._chosen.choose(args.choice)
        current, default = self.current(), self._choices.default()
        for name, choice in self._choices.choices.items():
            marks = " (по умолчанию)" if name == default else ""
            print(f"{'*' if name == current else ' '} {name:<10} {choice.label}{marks}")

    def choices(self) -> dict[str, ModelChoice]:
        return self._choices.choices

    def default(self) -> str | None:
        return self._choices.default()

    def current(self) -> str | None:
        """Выбранная вручную, если она есть в списке, иначе — по умолчанию."""
        chosen = self._chosen.current()
        return chosen if chosen in self._choices.choices else self._choices.default()
