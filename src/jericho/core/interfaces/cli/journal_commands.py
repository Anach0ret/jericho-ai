"""Команда «что Jericho делал»: журнал."""

from __future__ import annotations

import argparse
import json

from jericho.core.journal.entities import JournalEntry
from jericho.core.journal.protocols import JournalReader


class LogCommand:
    name = "log"
    help = "последние записи журнала"

    def __init__(self, journal: JournalReader) -> None:
        self._journal = journal

    def configure(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("-n", "--limit", type=int, default=20, help="сколько записей показать (по умолчанию 20)")

    def run(self, args: argparse.Namespace) -> None:
        entries = self._journal.tail(args.limit)
        if not entries:
            print("Журнал пуст.")
        for entry in entries:
            print(self._describe(entry))

    @staticmethod
    def _describe(entry: JournalEntry) -> str:
        details = "  ".join(
            f"{key}={json.dumps(value, ensure_ascii=False)}" for key, value in entry.details.items() if value is not None
        )
        who = f"user={entry.user}  " if entry.user else ""      # чьё поручение — у ассистента нескольких пользователей
        return f"{entry.time:%d.%m %H:%M:%S}  {entry.level:<7} {entry.event:<8} {who}{details}"
