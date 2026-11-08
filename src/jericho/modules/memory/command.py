"""Команда `<проект> memory`: что Jericho запомнил; `--forget ID` — забыть."""

from __future__ import annotations

import argparse

from jericho.modules.memory.book import MemoryBook


class MemoryCommand:
    name = "memory"
    help = "память: что запомнено со слов пользователя (теги, сколько раз вспоминалось); --forget ID — забыть"

    def __init__(self, book: MemoryBook) -> None:
        self._book = book

    def configure(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--forget", metavar="ID", help="забыть запись")

    def run(self, args: argparse.Namespace) -> None:
        if args.forget:
            gone = self._book.forget(args.forget)
            print(f"забыл: {gone.text}" if gone else f"записи {args.forget} нет")
            return
        for m in self._book.all():
            print(f"{m.id}  [{', '.join(m.tags)}]  {m.text}  (вспоминалась {m.used})")
