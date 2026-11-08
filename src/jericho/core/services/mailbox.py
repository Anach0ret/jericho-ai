"""Почтовый ящик: сообщения JSON в папке, по образцу Maildir — так ассистент обменивается с транспортом.

Транспорт (бот Telegram, почта) и ассистент живут в разных процессах, а часто и в разных контейнерах. Общая у них
только папка. Сообщение пишется в `tmp/` и переносится в `new/` одним `rename`: читатель видит либо всё сообщение,
либо ничего. Читатель забирает его к себе (`cur/`), а сделав дело, удаляет. Испорченное откладывается в `rejected/`.
Сеть, порты и общая база не нужны.

    ящик/
    ├── tmp/        пишется сейчас — не читать
    ├── new/        пришло, ждёт
    ├── cur/        взято в работу
    └── rejected/   испорчено или не от того отправителя
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import tempfile
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class MailboxError(ValueError):
    """Сообщение не читается: не JSON, не объект или пропало."""


class Mailbox:
    """Одна папка-ящик. Имена сообщений растут со временем: по имени видно, что пришло раньше."""

    PRIVATE_DIR = 0o700
    SUFFIX = ".json"

    def __init__(self, root: Path) -> None:
        self._root = root

    @property
    def root(self) -> Path:
        return self._root

    def post(self, message: Mapping[str, object]) -> Path:
        """Положить сообщение: целиком и сразу видимым в `new/`. Возвращает, где оно лежит."""
        tmp, new = self._dir("tmp"), self._dir("new")
        name = f"{time.time_ns()}.{os.getpid()}.{secrets.token_hex(4)}{self.SUFFIX}"
        descriptor, temporary = tempfile.mkstemp(dir=tmp, prefix=f"{name}.", suffix=".tmp")
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(dict(message), stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            target = new / name
            os.replace(temporary, target)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise
        return target

    def waiting(self) -> list[Path]:
        """Пришедшие и ещё не взятые сообщения, от старых к новым."""
        return self._sorted("new")

    def taken(self) -> list[Path]:
        """Взятые в работу и не законченные — например, работу оборвал перезапуск."""
        return self._sorted("cur")

    def take(self, message: Path) -> Path | None:
        """Взять сообщение в работу; None — его успел взять другой читатель."""
        target = self._dir("cur") / message.name
        try:
            os.replace(message, target)
        except FileNotFoundError:
            return None
        return target

    @staticmethod
    def read(message: Path) -> dict[str, Any]:
        try:
            data = json.loads(message.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise MailboxError(f"{message.name}: {error}") from error
        if not isinstance(data, dict):
            raise MailboxError(f"{message.name}: not a JSON object")
        return data  # pyright: ignore[reportUnknownVariableType]

    @staticmethod
    def done(message: Path) -> None:
        message.unlink(missing_ok=True)

    def reject(self, message: Path, reason: str) -> None:
        """Отложить сообщение в сторону: его не выполнят, но и не потеряют — можно посмотреть руками."""
        target = self._dir("rejected") / message.name
        try:
            os.replace(message, target)
        except FileNotFoundError:
            return
        logger.warning("mailbox_rejected", extra={"data": {"message": str(target), "reason": reason}})

    def _sorted(self, part: str) -> list[Path]:
        directory = self._root / part
        if not directory.is_dir():
            return []
        return sorted(path for path in directory.iterdir() if path.name.endswith(self.SUFFIX))

    def _dir(self, part: str) -> Path:
        directory = self._root / part
        directory.mkdir(mode=self.PRIVATE_DIR, parents=True, exist_ok=True)
        return directory
