"""Команда терминала «голосовая команда» — её вызывает горячая клавиша."""

from __future__ import annotations

import argparse
import sys

from jericho.modules.voice.voice_command import VoiceCommand


class ListenCommand:
    name = "listen"
    help = "голосовая команда: записать, распознать, выполнить, показать уведомление"

    def __init__(self, voice_command: VoiceCommand) -> None:
        self._voice_command = voice_command

    def configure(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--answer", help="ответ из уведомления с вопросом: ключ кнопки (yes, no) или reply — текст тогда на stdin; так зовёт сам Jericho"
        )
        parser.add_argument("--replaces", type=int, help="номер уведомления с вопросом: итог встанет на его место")
        parser.add_argument("--question", default="", help="id вопроса «да?», под которым нажата кнопка: ответ засчитается только ему")
        parser.add_argument("--stop", action="store_true", help="закончить идущую запись — как отпущенная клавиша")

    def run(self, args: argparse.Namespace) -> None:
        if args.stop:
            self._voice_command.stop_listening()
            return
        if args.answer:
            text = sys.stdin.read() if args.answer == "reply" else ""
            reply = self._voice_command.answer(args.answer, args.replaces, text, args.question)
        else:
            reply = self._voice_command.execute()
        if reply is not None:
            print(f"[{reply.status.value}] {reply.message}")
