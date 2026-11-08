"""Облако тегов памяти в общем промпте: по нему модель понимает, что можно вспомнить."""

from __future__ import annotations

from jericho.modules.memory.book import MemoryBook


class MemoryTags:
    """Подстановка `{{memory_tags}}`: только теги с числом записей — сами записи приходят через recall или с навыком."""

    def __init__(self, book: MemoryBook) -> None:
        self._book = book

    def values(self) -> dict[str, str]:
        cloud = self._book.cloud()
        return {"memory_tags": " · ".join(f"{name} {count}" for name, count in cloud) if cloud else "Память пока пуста."}
