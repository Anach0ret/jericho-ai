"""Что такое команда CLI."""

from __future__ import annotations

import argparse
from typing import Protocol


class Command(Protocol):
    """Одна подкоманда. Всё, с чем она работает, получает в конструкторе; навык отдаёт свои команды из `skill.py`."""

    name: str
    help: str

    def configure(self, parser: argparse.ArgumentParser) -> None: ...

    def run(self, args: argparse.Namespace) -> None: ...
