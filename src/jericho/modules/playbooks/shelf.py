"""Полка памяток: записать, предложить дополнение, принять или отклонить его, убрать."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime

from jericho.core.services.ids import short_id
from jericho.core.services.lock import ExclusiveLock, Unlocked
from jericho.core.services.locked_list import LockedList
from jericho.modules.playbooks.entities import Playbook, Suggestion
from jericho.modules.playbooks.protocols import PlaybookStore


class PlaybookLimit(Exception):
    """Полка не вмещает: слишком много памяток, предложений или текста. Сообщение — для человека и модели."""


class PlaybookShelf:
    """Свой замок нужен: окно на панели принимает и отклоняет дополнения, пока идёт фраза, а замок фразы его не
    охватывает. Каждое изменение — под замком списка и над свежими памятками по id (`LockedList`): раньше
    `mark_used` со старым объектом возвращал старый текст и уже принятое предложение (ревью 02.11.2026, П3a №8)."""

    def __init__(
        self, store: PlaybookStore, now: Callable[[], datetime], limit: int = 20, text_limit: int = 4000,
        suggestion_limit: int = 5, lock: ExclusiveLock | None = None,
    ) -> None:
        self._playbooks = LockedList(store, lock or Unlocked())
        self._now = now
        self._limit = limit
        self.text_limit = text_limit
        self._suggestion_limit = suggestion_limit

    def all(self) -> list[Playbook]:
        return self._playbooks.load()

    def find(self, playbook_id: str) -> Playbook | None:
        return self._by_id(self.all(), playbook_id)

    def write(self, title: str, site: str, text: str, playbook_id: str | None = None, append: bool = False) -> Playbook:
        """Новая памятка или правка: весь текст заново или дописать в конец (`append`)."""
        with self._playbooks.changing() as playbooks:
            old = self._by_id(playbooks, playbook_id) if playbook_id else None
            if old is None:
                self._room_for_one_more(playbooks)
                playbook = Playbook(short_id(self._taken(playbooks)), title, site, self._fitting(text), self._now())
            else:
                joined = f"{old.text}\n{text}" if append and old.text else text
                playbook = replace(old, title=title or old.title, site=site or old.site, text=self._fitting(joined))
            self._put(playbooks, playbook)
        return playbook

    def suggest(self, text: str, reason: str, playbook_id: str | None = None, title: str = "", site: str = "") -> Playbook:
        """Дополнение к памятке или новая памятка — до «Принять» человека модель её не видит."""
        with self._playbooks.changing() as playbooks:
            old = self._by_id(playbooks, playbook_id) if playbook_id else None
            if old is None:
                self._room_for_one_more(playbooks)
                old = Playbook(short_id(self._taken(playbooks)), title, site, "", self._now())
            if len(old.suggestions) >= self._suggestion_limit:
                raise PlaybookLimit(f"к памятке «{old.title}» уже {self._suggestion_limit} непринятых предложений")
            playbook = old.with_suggestion(Suggestion(short_id(self._taken(playbooks)), text, reason, self._now()))
            self._put(playbooks, playbook)
        return playbook

    def accept(self, suggestion_id: str) -> Playbook | None:
        """Принятое дописывается в конец памятки; у новой становится её текстом."""
        with self._playbooks.changing() as playbooks:
            found = self._holding(playbooks, suggestion_id)
            if found is None:
                return None
            playbook, suggestion = found
            text = f"{playbook.text}\n{suggestion.text}" if playbook.text else suggestion.text
            accepted = replace(playbook.without(suggestion_id), text=self._fitting(text))
            self._put(playbooks, accepted)
        return accepted

    def reject(self, suggestion_id: str) -> Playbook | None:
        """Отклонённая новая памятка — без текста и предложений — убирается целиком."""
        with self._playbooks.changing() as playbooks:
            found = self._holding(playbooks, suggestion_id)
            if found is None:
                return None
            playbook = found[0].without(suggestion_id)
            if playbook.accepted or playbook.suggestions:
                self._put(playbooks, playbook)
            else:
                playbooks[:] = [other for other in playbooks if other.id != playbook.id]
        return playbook

    def remove(self, playbook_id: str) -> Playbook | None:
        with self._playbooks.changing() as playbooks:
            removed = self._by_id(playbooks, playbook_id)
            playbooks[:] = [playbook for playbook in playbooks if playbook.id != playbook_id]
        return removed

    def mark_used(self, playbook: Playbook) -> None:
        """Когда памятку читали последний раз — по этому в окне видно, какая уже не нужна. Меняется только время,
        и у свежей записи: переданный объект мог устареть, пока его показывали."""
        with self._playbooks.changing() as playbooks:
            playbooks[:] = [replace(other, used=self._now()) if other.id == playbook.id else other for other in playbooks]

    @staticmethod
    def _by_id(playbooks: list[Playbook], playbook_id: str | None) -> Playbook | None:
        return next((playbook for playbook in playbooks if playbook.id == playbook_id), None)

    @staticmethod
    def _holding(playbooks: list[Playbook], suggestion_id: str) -> tuple[Playbook, Suggestion] | None:
        for playbook in playbooks:
            for suggestion in playbook.suggestions:
                if suggestion.id == suggestion_id:
                    return playbook, suggestion
        return None

    @staticmethod
    def _put(playbooks: list[Playbook], playbook: Playbook) -> None:
        if any(other.id == playbook.id for other in playbooks):
            playbooks[:] = [playbook if other.id == playbook.id else other for other in playbooks]
        else:
            playbooks.append(playbook)

    def _room_for_one_more(self, playbooks: list[Playbook]) -> None:
        if len(playbooks) >= self._limit:
            raise PlaybookLimit(f"памяток уже {self._limit}: сначала убери ненужную")

    def _fitting(self, text: str) -> str:
        if len(text) > self.text_limit:
            raise PlaybookLimit(f"памятка длиннее {self.text_limit} знаков: сократи её")
        return text

    @staticmethod
    def _taken(playbooks: list[Playbook]) -> set[str]:
        """У памяток и предложений id общие: «Принять 5359f9» не должно найти памятку."""
        return {playbook.id for playbook in playbooks} | {item.id for playbook in playbooks for item in playbook.suggestions}
