"""Команда `run`: сценарий по имени — из терминала, по кнопке в окне на панели, по горячей клавише."""

from __future__ import annotations

import argparse

from jericho.modules.scripts.runner import ScriptRunner
from jericho.modules.scripts.settings import Script


class RunCommand:
    name = "run"
    help = "быстрый сценарий по имени: шаги без модели (и фразы для модели, если они в нём есть); без имени — список"

    def __init__(self, scripts: dict[str, Script], runner: ScriptRunner) -> None:
        self._scripts = scripts
        self._runner = runner

    def configure(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("script", nargs="?", choices=sorted(self._scripts) or None, help="имя сценария из настроек scripts")

    def run(self, args: argparse.Namespace) -> None:
        if not args.script:
            for name, script in self._scripts.items():
                print(f"{name:<12} {script.title}{'  (с моделью)' if script.uses_model else ''}")
            return
        outcome = self._runner.run(args.script, self._scripts[args.script])
        print(outcome.summary())
        if not outcome.ok:
            raise SystemExit(1)
