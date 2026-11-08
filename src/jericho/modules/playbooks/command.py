"""Команда терминала «памятки» — для человека и для окна на панели."""

from __future__ import annotations

import argparse
import logging

from jericho.modules.playbooks.shelf import PlaybookLimit, PlaybookShelf

logger = logging.getLogger(__name__)


class PlaybooksCommand:
    name = "playbooks"
    help = "памятки: без аргументов — список; --accept ID / --reject ID — предложение модели; --remove ID — убрать памятку"

    def __init__(self, shelf: PlaybookShelf) -> None:
        self._shelf = shelf

    def configure(self, parser: argparse.ArgumentParser) -> None:
        actions = parser.add_mutually_exclusive_group()
        actions.add_argument("--accept", metavar="ID", help="id предложения — дописать его в памятку")
        actions.add_argument("--reject", metavar="ID", help="id предложения — отклонить")
        actions.add_argument("--remove", metavar="ID", help="id памятки — убрать целиком")

    def run(self, args: argparse.Namespace) -> None:
        if args.accept:
            self._accept(args.accept)
        elif args.reject:
            rejected = self._shelf.reject(args.reject)
            if rejected is None:
                raise SystemExit(f"предложения {args.reject} нет")
            logger.info("playbook_rejected", extra={"data": {"id": rejected.id, "suggestion": args.reject}})
            print(f"Отклонено предложение к памятке «{rejected.title}»")
        elif args.remove:
            removed = self._shelf.remove(args.remove)
            if removed is None:
                raise SystemExit(f"памятки {args.remove} нет")
            logger.info("playbook_removed", extra={"data": {"id": removed.id, "title": removed.title, "by": "command"}})
            print(f"Убрана памятка: {removed.title}")
        else:
            self._list()

    def _accept(self, suggestion_id: str) -> None:
        try:
            accepted = self._shelf.accept(suggestion_id)
        except PlaybookLimit as error:
            raise SystemExit(str(error)) from error
        if accepted is None:
            raise SystemExit(f"предложения {suggestion_id} нет")
        logger.info("playbook_accepted", extra={"data": {"id": accepted.id, "suggestion": suggestion_id}})
        print(f"Дописано в памятку «{accepted.title}»")

    def _list(self) -> None:
        for playbook in self._shelf.all():
            where = f" — {playbook.site}" if playbook.site else ""
            print(f"{playbook.id}  {playbook.title}{where}{'' if playbook.accepted else ' (предложена, не принята)'}")
            for line in playbook.text.splitlines():
                print(f"    {line}")
            for suggestion in playbook.suggestions:
                print(f"  ? {suggestion.id}: {suggestion.text} — {suggestion.reason}")
