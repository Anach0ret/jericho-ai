"""Список памяток в общем промпте: только названия и сайты, сам текст — через playbook_show."""

from __future__ import annotations

from jericho.modules.playbooks.entities import Playbook
from jericho.modules.playbooks.shelf import PlaybookShelf


class PlaybookList:
    """Подстановка `{{playbooks}}`. Непринятые (их предложила модель) не видны: их ещё не одобрил человек."""

    def __init__(self, shelf: PlaybookShelf) -> None:
        self._shelf = shelf

    def values(self) -> dict[str, str]:
        accepted = [playbook for playbook in self._shelf.all() if playbook.accepted]
        return {"playbooks": "\n".join(map(self._line, accepted)) if accepted else "Памяток нет."}

    @staticmethod
    def _line(playbook: Playbook) -> str:
        where = f" — {playbook.site}" if playbook.site else ""
        return f"- «{playbook.title}» (id {playbook.id}){where}"
