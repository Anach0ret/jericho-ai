"""Приём: что делать с каждым сообщением из ящика — проверить, выполнить от имени пользователя, ответить."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from pathlib import Path

from jericho.core.agent.entities import AgentReply, ReplyStatus
from jericho.core.services.mailbox import Mailbox
from jericho.modules.inbox.entities import Request
from jericho.modules.inbox.protocols import Answerer

logger = logging.getLogger(__name__)


class Reception:
    """Берёт сообщения по одному, от старых к новым. Поручение выполняет отдельный процесс (`Answerer`).

    Пользователь сверяется со своим списком, хотя транспорт уже сверил его со своим: взломанный транспорт не должен
    получить ассистента. Чужое и испорченное откладывается в сторону без ответа — отвечать неизвестно кому незачем.
    Если процесс поручения упал или не уложился в срок, ответ о сбое пишет приём: пользователь не ждёт впустую.
    """

    FAILED = AgentReply(ReplyStatus.FAILED, "Не получилось ответить — подробности в журнале ассистента")
    INTERRUPTED = AgentReply(ReplyStatus.FAILED, "Ответ прервался: ассистент перезапускался — повтори, если нужно")
    TOO_LONG = AgentReply(ReplyStatus.REFUSED, "Слишком длинное сообщение — скажи короче")

    def __init__(self, inbox: Mailbox, outbox: Mailbox, answerer: Answerer, users: Mapping[str, str], max_text: int) -> None:
        self._inbox = inbox
        self._outbox = outbox
        self._answerer = answerer
        self._users = dict(users)
        self._max_text = max_text

    def start(self) -> None:
        """Начало приёма: процессы ответа собираются заранее, недоделанное до перезапуска — сообщается."""
        self._answerer.prepare(self._users)
        self.recover()

    def stop(self) -> None:
        self._answerer.close()

    def recover(self) -> None:
        """Сообщения, взятые до перезапуска и не законченные: выполнялось ли поручение, неизвестно — не повторяем."""
        for taken in self._inbox.taken():
            request = self._request(taken)
            if request is not None:
                self._outbox.post(request.reply(self.INTERRUPTED))
                self._inbox.done(taken)

    def tick(self) -> int:
        """Обработать всё, что пришло. Возвращает, сколько сообщений взято."""
        handled = 0
        for message in self._inbox.waiting():
            taken = self._inbox.take(message)
            if taken is not None:
                self._handle(taken)
                handled += 1
        return handled

    def _handle(self, taken: Path) -> None:
        request = self._request(taken)
        if request is None:
            return
        if len(request.text) > self._max_text:
            self._outbox.post(request.reply(self.TOO_LONG))
        elif not self._answerer.answer(request.user, taken):
            self._outbox.post(request.reply(self.FAILED))
        logger.info("inbox", extra={"data": {"request": request.id, "user": request.user, "chars": len(request.text)}})
        self._inbox.done(taken)

    def _request(self, taken: Path) -> Request | None:
        """Запрос известного пользователя; иначе сообщение отложено в сторону и None."""
        try:
            request = Request.parse(self._inbox.read(taken))
        except ValueError as error:      # и `MailboxError`: файл не читается или не JSON-объект
            self._inbox.reject(taken, str(error))
            return None
        if request.user not in self._users:
            self._inbox.reject(taken, f"unknown user {request.user}")
            return None
        return request
