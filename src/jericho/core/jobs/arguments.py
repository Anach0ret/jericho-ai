"""Id работы в командной строке: ручка запускает работу с `--job ID` — по нему её итог находится в журнале."""

from __future__ import annotations

import argparse

from jericho.core.jobs.entities import new_job_id


def add_job_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--job", metavar="ID", default="", help="id работы — его даёт ручка, запустившая работу; без него — новый")
    parser.add_argument("--continuation", metavar="ID", default="", help="id продолжения (then) — его записала ручка")


def job_id(args: argparse.Namespace) -> str:
    """Id из `--job` или новый: работу запустили не из ручки — таймером или рукой в терминале."""
    given = getattr(args, "job", "")
    return given if isinstance(given, str) and given else new_job_id()


def continuation_id(args: argparse.Namespace) -> str:
    given = getattr(args, "continuation", "")
    return given if isinstance(given, str) else ""
