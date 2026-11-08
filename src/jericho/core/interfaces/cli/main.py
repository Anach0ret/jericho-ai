"""Точка входа CLI: строит разбор аргументов из готовых команд и запускает выбранную."""

from __future__ import annotations

import argparse
import logging
from collections.abc import Sequence

from jericho.core.management.base import Command

logger = logging.getLogger(__name__)


def build_parser(available: Sequence[Command]) -> argparse.ArgumentParser:
    # Имя программы argparse берёт из запуска: `home`, `jericho`, `python -m jericho` у таймера — как набрано.
    parser = argparse.ArgumentParser(description="Jericho — ручной запуск для проверки")
    subparsers = parser.add_subparsers(dest="subcommand", required=True)
    for command in available:
        sub = subparsers.add_parser(command.name, help=command.help)
        command.configure(sub)
        sub.set_defaults(handler=command)
    return parser


def run(available: Sequence[Command]) -> None:
    args = build_parser(available).parse_args()
    try:
        args.handler.run(args)
    except Exception:
        logger.exception("error", extra={"data": {"command": args.subcommand}})
        raise
