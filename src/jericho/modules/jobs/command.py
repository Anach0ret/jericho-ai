"""Команда `<проект> jobs --continue ID`: выполнить отложенное продолжение (её запускает `job_continue` после «да»)."""

from __future__ import annotations

import argparse

from jericho.core.jobs.book import ContinuationBook
from jericho.core.jobs.run import ContinuationRun


class JobsCommand:
    name = "jobs"
    help = "фоновые работы: --continue ID — выполнить отложенное продолжение (then); его запускает ручка job_continue"

    def __init__(self, book: ContinuationBook, run: ContinuationRun, user: str) -> None:
        self._book = book
        self._run = run
        self._user = user

    def configure(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--continue", dest="continuation", metavar="ID", required=True, help="id продолжения, которое ждёт решения")

    def run(self, args: argparse.Namespace) -> None:
        item = self._book.take_asked(args.continuation, self._user)     # взять — атомарно: дважды не выполнится
        if item is None:
            raise SystemExit(f"продолжение {args.continuation} не ждёт решения: выполнено, брошено или его нет")
        self._run.proceed(item)
