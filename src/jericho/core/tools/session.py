"""Что ядро помнит в пределах одной фразы."""

from __future__ import annotations

from collections.abc import Iterable


class CallSession:
    """Состояние вызовов одной фразы. Сервер ручек живёт ровно одну фразу, поэтому это просто объект в памяти."""

    def __init__(self, loaded_skills: Iterable[str] = ()) -> None:
        self._loaded_skills = set(loaded_skills)
        self._private_read = False
        self._local_read = False

    def read_private(self) -> None:
        """В этой фразе ручка отдала личные данные (`Tool.private`): вынести их наружу теперь можно только с «да»."""
        self._private_read = True

    @property
    def private_read(self) -> bool:
        return self._private_read

    def read_local(self) -> None:
        """В этой фразе ручка отдала содержимое файлов с машины пользователя (`Tool.local`)."""
        self._local_read = True

    @property
    def local_read(self) -> bool:
        return self._local_read

    def load(self, skill: str) -> None:
        self._loaded_skills.add(skill)

    def is_loaded(self, skill: str) -> bool:
        return skill in self._loaded_skills
