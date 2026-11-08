"""Настройка стандартного `logging` и чтение того, что он записал.

Код пишет события обычным способом — `logging.getLogger(__name__).info("tool", extra={"data": {...}})`.
Здесь решается только, куда и в каком виде они попадают: файл JSON Lines (одна запись — одна
строка JSON). В журнал пишут сразу два процесса — принявший фразу и сервер ручек, — поэтому пишущий
файл не сменяет: смену делает `JournalRotation`, один раз в начале фразы.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from logging.handlers import RotatingFileHandler, WatchedFileHandler
from pathlib import Path

from jericho.core.journal.entities import JournalEntry


class JsonLinesFormatter(logging.Formatter):
    """Превращает запись logging в строку JSON; поля события берутся из `extra={"data": {...}}`.

    Каждая строка несёт идентификатор запуска: по нему вызовы ручек связываются со своей фразой.
    """

    def __init__(self, run_id: str, user: str = "") -> None:
        super().__init__()
        self._run_id = run_id
        self._user = user

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, object] = {
            "time": datetime.fromtimestamp(record.created).astimezone().isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "run": self._run_id,
            **({"user": self._user} if self._user else {}),
            "event": record.getMessage(),
            **getattr(record, "data", {}),
        }
        if record.exc_info:
            entry["traceback"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False, default=str)


class LoggingConfigurator:
    """Подключает к логгеру файл журнала. Повторный вызов не дублирует записи.

    Журнал читает и пишет только владелец: в нём фразы пользователя и параметры вызовов.
    """

    PRIVATE_FILE = 0o600

    def __init__(
        self,
        path: Path,
        run_id: str,
        logger_name: str = "jericho",
        level: int = logging.INFO,
        user: str = "",
    ) -> None:
        self._path = path
        self._run_id = run_id
        self._user = user
        self._logger_name = logger_name
        self._level = level

    def configure(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.touch(mode=self.PRIVATE_FILE)
        self._path.chmod(self.PRIVATE_FILE)      # и у журнала, созданного до этого правила
        logger = logging.getLogger(self._logger_name)
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()
        # Дописывает в конец и замечает, что файл сменили: после смены пишет уже в новый.
        handler = WatchedFileHandler(self._path, encoding="utf-8")
        handler.setFormatter(JsonLinesFormatter(self._run_id, self._user))
        logger.addHandler(handler)
        logger.setLevel(self._level)
        logger.propagate = False   # журнал — единственный получатель, в консоль события не дублируются


class JournalRotation:
    """Смена переполненного журнала: текущий файл становится `.1`, прежние сдвигаются, лишний удаляется.

    Вызывается одним процессом — тем, что принял фразу, до запуска сервера ручек. Когда файл сменяли оба
    пишущих процесса, один из них продолжал писать в уже переименованный файл.
    """

    def __init__(self, path: Path, max_bytes: int = 1_000_000, backups: int = 3) -> None:
        self._path = path
        self._max_bytes = max_bytes
        self._backups = backups

    def rotate_if_full(self) -> None:
        try:
            if self._path.stat().st_size < self._max_bytes:
                return
        except OSError:
            return
        handler = RotatingFileHandler(self._path, backupCount=self._backups, encoding="utf-8", delay=True)
        try:
            handler.doRollover()
        except PermissionError:
            # Windows не переименует файл, открытый другим процессом (таймер, ответ из ящика): журнал сменится в
            # следующий раз, а фраза не падает из-за того, что он немного длиннее. Сказать об этом некуда — журнал
            # ещё не настроен (смена идёт до него), а консоль у запуска по расписанию — не человек.
            pass
        finally:
            handler.close()


class JsonLinesLogReader:
    """Читает последние записи журнала, от старых к новым."""

    _SERVICE_KEYS = ("time", "event", "level", "logger", "run", "user")

    def __init__(self, path: Path) -> None:
        self._path = path

    def tail(self, limit: int) -> list[JournalEntry]:
        if not self._path.exists():
            return []
        lines = self._path.read_text(encoding="utf-8").splitlines()[-limit:]
        return [entry for entry in map(self._parse, lines) if entry is not None]

    def _parse(self, line: str) -> JournalEntry | None:
        try:
            data = json.loads(line)
            return JournalEntry(
                time=datetime.fromisoformat(data["time"]),
                event=data["event"],
                level=data.get("level", "INFO"),
                source=data.get("logger", ""),
                run=data.get("run", ""),
                user=data.get("user", ""),
                details={key: value for key, value in data.items() if key not in self._SERVICE_KEYS},
            )
        except (ValueError, KeyError, AttributeError, TypeError):
            return None  # оборванная или чужая строка не должна ломать чтение журнала
