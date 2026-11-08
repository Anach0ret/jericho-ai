"""Где Jericho и его навыки хранят свои файлы."""

from __future__ import annotations

import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

import platformdirs


@dataclass(frozen=True, slots=True)
class UserDirs:
    """Где по правилам ОС лежат файлы пользователя: долгие, до выхода из системы и настройки машины.

    Явно заданные переменные XDG главнее на любой ОС — так их задают тесты и те, кто хочет свои места. Без них на
    macOS и Windows — правила этих ОС (`platformdirs`), на Linux и прочих — умолчания XDG. Умолчания XDG — свои, а не
    `platformdirs`: тот читает только окружение процесса, а сборке ядра окружение передаётся (и на Linux пути те же).
    """

    NATIVE: ClassVar[tuple[str, ...]] = ("darwin", "win32")

    state: Path             # то, что живёт долго
    runtime: Path | None    # то, что живёт до выхода из системы; None — такой папки нет (запуск без входа в систему)
    config: Path            # файлы машины

    @classmethod
    def find(cls, environment: Mapping[str, str], home: Path, system: str = sys.platform) -> UserDirs:
        default = cls.native() if system in cls.NATIVE else cls(home / ".local/state", None, home / ".config")
        return cls(
            cls._named(environment, "XDG_STATE_HOME") or default.state,
            cls._named(environment, "XDG_RUNTIME_DIR") or default.runtime,
            cls._named(environment, "XDG_CONFIG_HOME") or default.config,
        )

    @classmethod
    def native(cls) -> UserDirs:
        return cls(
            Path(platformdirs.user_state_dir()), Path(platformdirs.user_runtime_dir()), Path(platformdirs.user_config_dir())
        )

    @staticmethod
    def _named(environment: Mapping[str, str], variable: str) -> Path | None:
        value = environment.get(variable)
        return Path(value) if value else None


@dataclass(frozen=True, slots=True)
class Paths:
    """Папки для файлов: навык берёт место здесь, а не выдумывает своё."""

    PRIVATE_DIR: ClassVar[int] = 0o700
    USERS: ClassVar[str] = "users"

    state_dir: Path      # то, что живёт долго: журнал, токены, кэш
    runtime_dir: Path    # то, что живёт до выхода из системы: разговор, ожидающий вопрос
    sessions_dir: Path | None = None    # сеансы всех пользователей (`for_user`); пусто — сеанс один, это `runtime_dir`

    @classmethod
    def under(cls, name: str, dirs: UserDirs) -> Paths:
        """Стандартные места ОС (`UserDirs`); `name` — имя папки в каждом из них."""
        state = dirs.state / name
        runtime = dirs.runtime / name if dirs.runtime else state / "run"      # нет папки сеанса — рядом с долгими
        return cls(state, runtime)

    @classmethod
    def under_xdg(cls, name: str, environment: Mapping[str, str], home: Path) -> Paths:
        """Места по правилам XDG — как `under` на Linux при любой ОС: для тестов и инструментов с явным окружением."""
        return cls.under(name, UserDirs.find(environment, home, system="linux"))

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
