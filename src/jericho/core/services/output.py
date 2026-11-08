"""Вывод: куда уходит ответ на поручение."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Protocol

from jericho.core.agent.entities import AgentReply
from jericho.core.conf.settings import OutputSettings
from jericho.core.services.adapters.notify_send import NotifySendNotifier
from jericho.core.services.mailbox import Mailbox
from jericho.core.services.notifications import Notification, Notifier, StatusLook
from jericho.core.services.runner import SubprocessRunner


class Output(Protocol):
    """Отдаёт ответ тому, кто его ждёт. Каким способом — решает проект; каркас знает только этот порт."""

    def deliver(self, task: str, reply: AgentReply) -> None: ...


class StdoutOutput:
    """Печатает ответ: статус и строка, ниже — подробности, если они есть."""

    def __init__(self, write: Callable[[str], object] = print) -> None:
        self._write = write

    def deliver(self, task: str, reply: AgentReply) -> None:
        self._write(f"[{reply.status.value}] {reply.message}")
        if reply.body:
            self._write(reply.body)


class FileOutput:
    """Дописывает ответ в файл: время, поручение, статус, строка и подробности. Для поручений без человека рядом."""

    def __init__(self, path: Path, now: Callable[[], datetime] = datetime.now) -> None:
        self._path = path
        self._now = now

    def deliver(self, task: str, reply: AgentReply) -> None:
        lines = [f"## {self._now():%Y-%m-%d %H:%M} · {reply.status.value} · {reply.message}", f"Поручение: {task}"]
        if reply.body:
            lines += ["", reply.body]
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as file:
            file.write("\n".join(lines) + "\n\n")


class NotifyOutput:
    """Уведомление на экране — для ассистента на рабочем столе: напоминание или итог задачи без человека рядом."""

    UNTIL_CLOSED = 0      # срок показа «пока не закроют» по спецификации уведомлений

    def __init__(self, notifier: Notifier, title: str, persistent: bool = False) -> None:
        self._notifier = notifier
        self._look = StatusLook(title)
        self._timeout = self.UNTIL_CLOSED if persistent else None

    def deliver(self, task: str, reply: AgentReply) -> None:
        body = f"{reply.message}\n\n{reply.body}" if reply.body else reply.message
        notification = Notification(self._look.title(reply.status), body, self._look.urgency(reply.status), self._timeout, transient=reply.private)
        self._notifier.show(notification)


class MailboxOutput:
    """Сообщение в ящик транспорта: бот отдаст его адресату. Для ассистента на сервере — сводки, итоги, напоминания."""

    def __init__(self, mailbox: Mailbox, to: str) -> None:
        self._mailbox = mailbox
        self._to = to

    def deliver(self, task: str, reply: AgentReply) -> None:
        self._mailbox.post({"to": self._to, "task": task, "status": reply.status.value, "title": reply.message, "text": reply.body})


def output_for(settings: OutputSettings, project: str) -> Output:
    """Вывод, названный в настройках. `project` — имя проекта: заголовок уведомлений по умолчанию."""
    match settings.kind:
        case "file":
            return FileOutput(settings.file)
        case "notify":
            return NotifyOutput(NotifySendNotifier(SubprocessRunner(), icon=settings.icon), settings.title or project, settings.persistent)
        case "mailbox":
            return MailboxOutput(Mailbox(settings.mailbox), settings.to)
        case _:
            return StdoutOutput()
