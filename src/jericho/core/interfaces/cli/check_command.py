"""Команда проверки структуры проекта."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from jericho.core.checks.base import Check, Project


class CheckCommand:
    name = "check"
    help = "проверить правила структуры: файлы навыков, импорты, ручки, подстановки"

    def __init__(self, project: Project, checks: Sequence[Check]) -> None:
        self._project = project
        self._checks = tuple(checks)

    def configure(self, parser: argparse.ArgumentParser) -> None:
        pass

    def run(self, args: argparse.Namespace) -> None:
        messages = [message for check in self._checks for message in check.run(self._project)]
        for message in messages:
            print(f"{message.code}  {message.where}: {message.text}")
        print(f"Проверок: {len(self._checks)}, замечаний: {len(messages) or 'нет'}.")
        if messages:
            sys.exit(1)
