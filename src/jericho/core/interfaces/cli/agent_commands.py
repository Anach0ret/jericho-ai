"""Команды разговора с Jericho: текстом и просмотр промпта."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from jericho.core.agent.handle_phrase import HandlePhrase
from jericho.core.prompting.builder import PromptBuilder
from jericho.core.services.output import Output
from jericho.core.services.stop import PhraseStopper
from jericho.core.skills.guide import SkillGuides


class AskCommand:
    name = "ask"
    help = "поручение текстом → модель → ручки → ответ туда, куда проект отдаёт ответы"

    def __init__(self, handle_phrase: HandlePhrase, output: Output) -> None:
        self._handle_phrase = handle_phrase
        self._output = output

    def configure(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("phrase", nargs="?", default="-", help="фраза, как её выдаст распознавание; «-» или пусто — со stdin")

    def run(self, args: argparse.Namespace) -> None:
        # Со stdin — для программ (окно на панели): строку команды видит любой процесс машины.
        phrase = sys.stdin.read().strip() if args.phrase == "-" else args.phrase
        if not phrase:
            raise SystemExit("пустая фраза: нечего поручить")
        self._output.deliver(phrase, self._handle_phrase.execute(phrase))


class PromptCommand:
    name = "prompt"
    help = "системный промпт, который сейчас уйдёт модели; с именем навыка — его руководство"

    def __init__(self, prompts: PromptBuilder, guides: SkillGuides, skills: Sequence[str]) -> None:
        self._prompts = prompts
        self._guides = guides
        self._skills = tuple(skills)

    def configure(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("skill", nargs="?", choices=self._skills, help="показать руководство навыка — ответ на load_skill")

    def run(self, args: argparse.Namespace) -> None:
        print(self._guides.guide(args.skill) if args.skill else self._prompts.build())


class StopCommand:
    name = "stop"
    help = "остановить поручение, которое выполняется сейчас (его можно повесить на клавишу)"

    def __init__(self, stopper: PhraseStopper) -> None:
        self._stopper = stopper

    def configure(self, parser: argparse.ArgumentParser) -> None:
        pass

    def run(self, args: argparse.Namespace) -> None:
        stopped = self._stopper.stop()
        print(f"Остановил поручение (процесс {stopped})" if stopped else "Сейчас ничего не выполняется")
