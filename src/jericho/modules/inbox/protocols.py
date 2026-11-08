"""Что модулю «входящие» нужно от внешнего мира: запустить поручение от имени пользователя."""

from __future__ import annotations

from collections.abc import Collection
from pathlib import Path
from typing import Protocol


class Answerer(Protocol):
    """Отвечает на один запрос отдельным процессом ассистента — у каждого поручения свой запуск."""

    def prepare(self, users: Collection[str]) -> None:
        """Собрать процессы заранее — чтобы ответ не ждал сборки ассистента."""
        ...

    def answer(self, user: str, request: Path) -> bool:
        """True — ответ положен в ящик ответов; False — процесс упал или не уложился в срок."""
        ...

    def close(self) -> None:
        """Приём остановлен: собранные заранее процессы больше не нужны."""
        ...
