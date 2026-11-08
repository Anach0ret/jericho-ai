"""Где Jericho и его навыки хранят свои файлы."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar


@dataclass(frozen=True, slots=True)
class Paths:
    """Папки для файлов: навык берёт место здесь, а не выдумывает своё."""

    PRIVATE_DIR: ClassVar[int] = 0o700
    USERS: ClassVar[str] = "users"

    state_dir: Path      # то, что живёт долго: журнал, токены, кэш
    runtime_dir: Path    # то, что живёт до выхода из системы: разговор, ожидающий вопрос
    sessions_dir: Path | None = None    # сеансы всех пользователей (`for_user`); пусто — сеанс один, это `runtime_dir`

    @classmethod
    def under_xdg(cls, name: str, environment: Mapping[str, str], home: Path) -> Paths:
        """Стандартные места по правилам XDG; `name` — имя папки в каждом из них."""
        state = Path(environment.get("XDG_STATE_HOME") or home / ".local/state") / name
        session = environment.get("XDG_RUNTIME_DIR")      # нет папки сеанса (запуск без входа в систему) — рядом с долгими
        runtime = Path(session) / name if session else state / "run"
        return cls(state, runtime)

    @property
    def all_sessions(self) -> Path:
        """Папка, где лежат сеансы всех пользователей: защищать надо её, а не только свой сеанс (ревью 02.11.2026)."""
        return self.sessions_dir or self.runtime_dir

    @property
    def confirmation(self) -> Path:
        """Вопрос, ждущий «да», — в папке сеанса: у каждого пользователя свой (`for_user`)."""
        return self.runtime_dir / "confirmation.json"

    def for_user(self, user: str) -> Paths:
        """Папки запуска от имени пользователя: долгое общее (журнал, заметки, поручения), сеанс — свой.

        В папке сеанса лежат вопрос, ждущий «да», разговор и замок фразы. Своя папка — и «да» одного пользователя
        не подтверждает вопрос другого, а ответ на уточнение не попадает в чужой разговор. Пусто — без изменений.
        """
        return Paths(self.state_dir, self.runtime_dir / self.USERS / user, self.all_sessions) if user else self

    def prepare(self) -> None:
        """Создаёт обе папки и закрывает их от других пользователей машины: в них разговор, заметки и журнал.

        Права выставляются и на уже существующие папки — раньше они создавались открытыми на чтение.
        """
        for directory in (self.state_dir, self.runtime_dir):
            directory.mkdir(mode=self.PRIVATE_DIR, parents=True, exist_ok=True)
            directory.chmod(self.PRIVATE_DIR)
