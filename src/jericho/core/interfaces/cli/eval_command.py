"""Команда прогона проверочных фраз."""

from __future__ import annotations

import argparse

from jericho.core.evals.protocols import RunStore
from jericho.core.evals.report import EvalReport
from jericho.core.evals.session import EvalSession


class EvalCommand:
    name = "eval"
    help = "прогнать проверочные фразы через модель вхолостую и сравнить с ожиданием"

    def __init__(self, session: EvalSession, store: RunStore) -> None:
        self._session = session
        self._store = store

    def configure(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("only", nargs="*", help="ключи фраз, например desktop:11; без них — весь набор")
        parser.add_argument("--list", action="store_true", help="показать фразы и не запускать модель")

    def run(self, args: argparse.Namespace) -> None:
        if args.list:
            for case in self._session.cases():
                print(f"{case.key:<12} {case.phrase}")
            return
        report = EvalReport(self._session.run(only=args.only))
        print("\n".join(report.lines()))
        if args.only:
            return   # часть набора с прошлым прогоном не сравнивается и точкой отсчёта не становится
        previous = self._store.previous()
        changes = report.changes(previous) if previous is not None else []
        if previous is not None:
            print("\nС прошлого прогона " + ("изменилось:" if changes else "ничего не изменилось."))
            print("\n".join(changes), end="\n" if changes else "")
        print(f"Сохранено: {self._store.save(report.record())}")
