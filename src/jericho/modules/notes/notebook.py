"""Записная книжка: правила, по которым заметки появляются, заменяются и исчезают."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime

from jericho.modules.notes.entities import Note, NoteKind
from jericho.modules.notes.protocols import NoteStore


class Notebook:
    """Заметки всех навыков. Навык о них не знает: заметка привязана к его имени, а виды заметок общие.

    `limit` — сколько заметок может быть у одного навыка: они идут в каждое его руководство.
    """

    def __init__(
        self,
        store: NoteStore,
        skills: Sequence[str],
        kinds: Sequence[NoteKind],
        limit: int = 30,
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        self._store = store
        self._skills = tuple(skills)
        self._kinds = tuple(kinds)
        self._limit = limit
        self._now = now

    @property
    def skills(self) -> tuple[str, ...]:
        """Навыки, о которых можно что-то записать, — все подключённые."""
        return self._skills

    @property
    def limit(self) -> int:
        return self._limit

    @property
    def kinds(self) -> tuple[NoteKind, ...]:
        return self._kinds

    def kind(self, name: str) -> NoteKind | None:
        return next((kind for kind in self._kinds if kind.name == name), None)

    def all(self) -> list[Note]:
        return self._store.load()

    def of(self, skill: str) -> list[Note]:
        return [note for note in self.all() if note.skill == skill]

    def has_room(self, skill: str, name: str) -> bool:
        """Новая заметка помещается; замена уже записанной — всегда."""
        notes = self.of(skill)
        return len(notes) < self._limit or any(note.key == (skill, name.casefold()) for note in notes)

    def knows(self, skill: str, name: str, value: str) -> bool:
        """Такая заметка уже есть — то же имя и то же значение."""
        return any(note.key == (skill, name.casefold()) and note.value == value for note in self.of(skill))

    def remember(self, skill: str, kind: str, name: str, value: str) -> Note | None:
        """Записывает заметку и возвращает прежнюю с тем же именем, если она была."""
        fresh = Note(skill, kind, name, value, self._now())
        notes = self.all()
        replaced = next((note for note in notes if note.key == fresh.key), None)
        self._store.save([*(note for note in notes if note.key != fresh.key), fresh])
        return replaced

    def forget(self, skill: str, name: str) -> Note | None:
        """Убирает заметку и возвращает её; None — такой не было."""
        notes = self.all()
        gone = next((note for note in notes if note.key == (skill, name.casefold())), None)
        if gone is not None:
            self._store.save([note for note in notes if note is not gone])
        return gone
