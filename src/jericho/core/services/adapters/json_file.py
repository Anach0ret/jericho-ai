"""Небольшой файл состояния в JSON: запись без оборванных файлов и бережное обращение с испорченным."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from jericho.core.services.clock import local_now

logger = logging.getLogger(__name__)


class JsonStateFile:
    """Один файл состояния, который читают и пишут разные процессы Jericho.

    Запись идёт во временный файл рядом и подменяет прежний одним действием: читатель видит либо старое,
    либо новое, но не половину. Файл доступен только владельцу.

    Файл, который есть, но не разбирается, не считается пустым молча: он уходит в сторону под именем
    с пометкой `.corrupt-<время>`, в журнал пишется ошибка, и только тогда вызывающий получает «пусто».
    Следующая запись создаёт новый файл и не затирает то, что можно восстановить руками.
    """

    def __init__(self, path: Path, clock: Callable[[], datetime] = local_now) -> None:
        self._path = path
        self._clock = clock

    def read[ContentT](self, parse: Callable[[Any], ContentT], empty: ContentT) -> ContentT:
        """Содержимое, разобранное `parse`; `empty` — файла нет или он испорчен."""
        try:
            text = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return empty
        except OSError as error:
            self._report("state_file_unreadable", error)
            return empty
        try:
            return parse(json.loads(text))
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            self._set_aside(error)
            return empty

    def write(self, content: object, indent: int | None = None) -> None:
        self._path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)     # папки ассистента — только владельцу (E015)
        descriptor, temporary = tempfile.mkstemp(dir=self._path.parent, prefix=f"{self._path.name}.", suffix=".tmp")
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(content, stream, ensure_ascii=False, indent=indent)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self._path)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise

    def remove(self) -> None:
        self._path.unlink(missing_ok=True)

    def _set_aside(self, error: Exception) -> None:
        aside = self._path.with_name(f"{self._path.name}.corrupt-{self._clock():%Y%m%dT%H%M%S}")
        try:
            os.replace(self._path, aside)
        except OSError as failure:
            self._report("state_file_corrupt", error, not_moved=str(failure))
            return
        self._report("state_file_corrupt", error, moved_to=str(aside))

    def _report(self, event: str, error: Exception, **details: str) -> None:
        logger.error(event, extra={"data": {"file": str(self._path), "error": f"{type(error).__name__}: {error}", **details}})
