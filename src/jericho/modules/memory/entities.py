"""Запись памяти: что пользователь сказал Jericho о себе, людях и делах — его словами, с тегами для поиска."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class Memory:
    """Одна запись. Текст — слова пользователя как есть; теги — по ним запись находят и приносят навыку.

    Тег, совпадающий с именем навыка (`telegram`), привязывает запись к навыку: она приходит с его руководством.
    """

    id: str                 # короткий, для «забыть»: a3f9c2
    text: str
    tags: tuple[str, ...]
    added: datetime
    used: int = 0           # сколько раз вспоминалась — видно, что давно не нужно
    last_used: datetime | None = None
