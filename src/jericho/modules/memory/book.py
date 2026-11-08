"""Книга памяти: записать, найти, забыть. Поиск — по тегам точно и по началу слов в тексте."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import replace
from datetime import datetime

from jericho.core.journal.user_words import plain
from jericho.core.services.clock import local_now
from jericho.core.services.ids import short_id
from jericho.core.tools.result import ToolRefusal
from jericho.modules.memory.entities import Memory
from jericho.modules.memory.protocols import MemoryStore

TAG = re.compile(r"^[\w-]{2,24}$")


def tag(text: str) -> str:
    """Тег — одно слово строчными: «Маша» → «маша», «Portfolio» → «portfolio»."""
    return plain(text).replace(" ", "-")


class MemoryBook:
    """`limit` — сколько записей всего: память не должна расти без конца. Забывается только по просьбе: полная книга
    отказывает в новой записи и называет кандидатов на «забыть» — давно не нужные. Раньше старые записи молча
    вытеснялись, а забывать обещано только по явной просьбе (ревью 02.11.2026, П3b №3)."""

    FULL = "memory_full"
    CANDIDATES = 5

    def __init__(self, store: MemoryStore, now: Callable[[], datetime] = local_now, limit: int = 300) -> None:
        self._store = store
        self._now = now
        self._limit = limit

    def all(self) -> list[Memory]:
        return self._store.load()

    def add(self, text: str, tags: Iterable[str]) -> tuple[Memory, bool]:
        """Записать. Тот же текст уже есть — дополняются теги. Возвращает запись и была ли она новой."""
        memories = self._store.load()
        clean = tuple(dict.fromkeys(t for t in map(tag, tags) if TAG.match(t)))
        for i, m in enumerate(memories):
            if plain(m.text) == plain(text):
                merged = replace(m, tags=tuple(dict.fromkeys((*m.tags, *clean))))
                memories[i] = merged
                self._store.save(memories)
                return merged, False
        if len(memories) >= self._limit:
            raise ToolRefusal(
                self.FULL, limit=self._limit, candidates=[{"id": m.id, "text": m.text} for m in self._least_needed(memories)],
                detail="память полна: спроси пользователя, что из candidates забыть (forget_memory), и запиши снова",
            )
        memory = Memory(short_id({m.id for m in memories}), text.strip(), clean, self._now())
        self._store.save([*memories, memory])
        return memory, True

    def forget(self, memory_id: str) -> Memory | None:
        memories = self._store.load()
        gone = next((m for m in memories if m.id == memory_id), None)
        if gone is not None:
            self._store.save([m for m in memories if m.id != memory_id])
        return gone

    def search(self, words: Iterable[str], limit: int = 5) -> list[Memory]:
        """Лучшие совпадения: точный тег весит больше, чем начало слова в тексте («маш» — «Маша»). Нечёткого сравнения
        нет: облако тегов у модели в промпте, она передаёт точный тег, а похожие слова («маша» — «каша») дали бы ложные
        находки. Найденное отмечается использованным."""
        query = [w for text in words for w in plain(text).split() if len(w) > 1]
        scored: list[tuple[float, Memory]] = []
        for m in self._store.load():
            text_words = plain(m.text).split()
            score = 0.0
            for q in query:
                if q in m.tags:
                    score += 2
                elif any(w.startswith(q) for w in text_words):
                    score += 1
            if score:
                scored.append((score, m))
        found = [m for _, m in sorted(scored, key=lambda x: (-x[0], -x[1].added.timestamp()))[:limit]]
        self._touch({m.id for m in found})
        return found

    def of_skill(self, skill: str, limit: int = 15) -> list[Memory]:
        """Записи с тегом навыка — приходят с его руководством; сверх предела — самые свежие."""
        return [m for m in self._store.load() if skill in m.tags][-limit:]

    def cloud(self, limit: int = 40) -> list[tuple[str, int]]:
        """Самые частые теги — в промпт: по ним модель понимает, что спросить у памяти."""
        return Counter(t for m in self._store.load() for t in m.tags).most_common(limit)

    def _least_needed(self, memories: list[Memory]) -> list[Memory]:
        """Реже всех нужные, из них — дольше всех не вспоминавшиеся."""
        return sorted(memories, key=lambda m: (m.used, (m.last_used or m.added).timestamp()))[: self.CANDIDATES]

    def _touch(self, ids: set[str]) -> None:
        if not ids:
            return
        now = self._now()
        self._store.save([replace(m, used=m.used + 1, last_used=now) if m.id in ids else m for m in self._store.load()])
