"""Отправленные уведомления: что ассистент сам написал человеку через ящик транспорта — сводка, тревога, итог задачи.

Задача 102 серверного ассистента (11.11.2026): на «какая ошибка?» через полтора часа после сводки ассистент не знал, о какой
сводке речь, — уведомления не попадали никуда, кроме чата. Теперь вывод в ящик (`MailboxOutput`) записывает сюда, что
ушло, а модуль `notices` показывает это модели, когда тот же человек отвечает.

Что хранится — только то, что можно модели: заголовок, текст ответа модели или кода, данные события от ручек
(`facts`) и источники чужого текста (`foreign`). Ответ с пометкой `private` («показать — да, хранить — нет»: записи
как есть, личная переписка) хранится без текста. Срок — сутки, не больше `LIMIT` на адресата: это память разговора,
а не архив.

Транспорт сообщает, дошло ли (`confirm` по квитанции): поставить в ящик — ещё не доставить. Квитанция несёт и
номера сообщений у транспорта — по ним находится уведомление, на которое человек ответил (`by_message`).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from jericho.core.agent.entities import AgentReply
from jericho.core.services.adapters.file_lock import FileLock
from jericho.core.services.adapters.json_file import JsonStateFile
from jericho.core.services.clock import local_now
from jericho.core.services.locked_list import LockedList


@dataclass(frozen=True, slots=True)
class SentNotice:
    id: str
    to: str                     # адресат у транспорта (`OutputSettings.to`): «owner»
    time: datetime
    task: str                   # поручение, на которое это ответ, или имя ручки, которая написала сама
    status: str
    title: str
    text: str = ""              # пусто у `private`
    facts: Mapping[str, Any] = field(default_factory=dict)    # данные события от ручек запуска: окно, проект, фильтры
    foreign: tuple[str, ...] = ()
    delivered: bool | None = None          # None — квитанции ещё нет (или транспорт их не шлёт)
    messages: tuple[str, ...] = ()         # номера сообщений у транспорта: длинное уходит частями

    @classmethod
    def of(cls, id_: str, to: str, time: datetime, task: str, reply: AgentReply, facts: Mapping[str, Any], foreign: Sequence[str]) -> SentNotice:
        return cls(id_, to, time, task, reply.status.value, reply.message, "" if reply.private else reply.body, dict(facts), tuple(foreign))

    def as_record(self) -> dict[str, Any]:
        return {
            "id": self.id, "to": self.to, "time": self.time.isoformat(), "task": self.task, "status": self.status,
            "title": self.title, "text": self.text, "facts": dict(self.facts), "foreign": list(self.foreign),
            "delivered": self.delivered, "messages": list(self.messages),
        }

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> SentNotice:
        return cls(
            str(record["id"]), str(record["to"]), datetime.fromisoformat(record["time"]), str(record["task"]),
            str(record["status"]), str(record["title"]), str(record.get("text", "")), dict(record.get("facts", {})),
            tuple(record.get("foreign", ())), record.get("delivered"), tuple(str(m) for m in record.get("messages", ())),
        )


class _NoticeFile:
    """Файл уведомлений одного адресата: старше срока при чтении не возвращаются, при записи — не пишутся."""

    def __init__(self, path: Path, keep: timedelta, clock: Callable[[], datetime]) -> None:
        self._file = JsonStateFile(path, clock)
        self._keep = keep
        self._clock = clock

    def load(self) -> list[SentNotice]:
        oldest = self._clock() - self._keep
        notices = self._file.read(lambda records: [SentNotice.from_record(record) for record in records], [])
        return [notice for notice in notices if notice.time >= oldest]

    def save(self, items: Sequence[SentNotice]) -> None:
        self._file.write([notice.as_record() for notice in items])


class SentLog:
    """Файл на адресата в папке состояния: переживает перезапуск; пишут процессы задач и приём квитанций — под замком
    (`LockedList`), читает процесс ответа."""

    DIRECTORY = "sent"
    KEEP = timedelta(hours=24)
    LIMIT = 20
    _NAME = re.compile(r"[A-Za-z0-9_-]{1,64}")

    def __init__(self, directory: Path, clock: Callable[[], datetime] = local_now) -> None:
        self._directory = directory
        self._clock = clock

    @classmethod
    def at(cls, state_dir: Path, clock: Callable[[], datetime] = local_now) -> SentLog:
        return cls(state_dir / cls.DIRECTORY, clock)

    def record(self, notice: SentNotice) -> None:
        with self._list(notice.to).changing() as notices:
            notices[:] = [*notices, notice][-self.LIMIT :]

    def confirm(self, notice_id: str, delivered: bool, messages: Sequence[str] = ()) -> bool:
        """Квитанция транспорта. False — такого уведомления нет (истекло или чужое): квитанция ни к чему не относится."""
        for path in sorted(self._directory.glob("*.json")):
            with self._list(path.stem).changing() as notices:
                for index, notice in enumerate(notices):
                    if notice.id == notice_id:
                        notices[index] = replace(notice, delivered=delivered, messages=tuple(map(str, messages)))
                        return True
        return False

    def recent(self, to: str) -> tuple[SentNotice, ...]:
        """Не старше суток, новые первыми; не дошедшие (`delivered is False`) — нет: человек их не видел."""
        return tuple(notice for notice in reversed(self._list(to).load()) if notice.delivered is not False)

    def by_message(self, to: str, message: str) -> SentNotice | None:
        return next((notice for notice in self._list(to).load() if message in notice.messages), None)

    def _list(self, to: str) -> LockedList[SentNotice]:
        if not self._NAME.fullmatch(to):
            raise ValueError(f"output 'to' must be latin letters, digits, '-' or '_': {to!r}")
        store = _NoticeFile(self._directory / f"{to}.json", self.KEEP, self._clock)
        return LockedList(store, FileLock(self._directory / f"{to}.lock", wait=5.0))
