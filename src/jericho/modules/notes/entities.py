"""Понятия заметок: вид заметки, который объявляет навык, и сама заметка."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class NoteKind:
    """Что навык разрешает о себе запомнить. Значение проверяет код: свободный текст в заметки не попадает.

    Заметку пишет модель, а читает она же во всех следующих фразах. Если бы значением мог быть любой текст,
    фраза с чужой страницы стала бы постоянным указанием. Поэтому у каждого вида — образец, которому значение
    обязано соответствовать.
    """

    name: str            # как вид называется в ручке remember: «site», «app»
    description: str     # для модели: что это и когда записывать
    pattern: str         # чему соответствует значение целиком
    example: str         # «сайт курса» → https://lms.example.org

    def accepts(self, value: str) -> bool:
        return re.fullmatch(self.pattern, value) is not None


@dataclass(frozen=True, slots=True)
class Note:
    """Одно наблюдение: как пользователь что-то называет и что это на самом деле."""

    skill: str
    kind: str
    name: str            # слова пользователя: «сайт курса»
    value: str           # то, что стоит за ними: адрес, идентификатор, надпись
    added: datetime

    @property
    def key(self) -> tuple[str, str]:
        """Заметку узнают по навыку и имени: «сайт курса» у навыка browser — одна."""
        return self.skill, self.name.casefold()
