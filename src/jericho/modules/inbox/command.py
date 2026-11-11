"""Команды модуля: `inbox` — постоянный приём сообщений, `answer` — ответ на одно (его зовёт `inbox`)."""

from __future__ import annotations

import argparse
import signal
import sys
import threading
import time
from pathlib import Path
from types import FrameType
from typing import TYPE_CHECKING

from jericho.core.services.confirmation import ConfirmationGate
from jericho.core.services.mailbox import Mailbox
from jericho.modules.inbox.entities import Request
from jericho.modules.inbox.questions import QuestionWatch
from jericho.modules.inbox.reception import Reception

if TYPE_CHECKING:
    from jericho.core.agent.handle_phrase import HandlePhrase


class InboxCommand:
    """Смотрит в ящик раз в `poll` секунд, пока процесс не остановят (`docker stop` — SIGTERM)."""

    name = "inbox"
    help = "принимать сообщения из ящика транспорта (бота) и отвечать на них — постоянный процесс"

    def __init__(self, reception: Reception, poll: float, questions: QuestionWatch | None = None) -> None:
        self._reception = reception
        self._poll = poll
        self._questions = questions      # ждущие «да»: напомнить, сказать «истёк»
        self._stop = threading.Event()

    def configure(self, parser: argparse.ArgumentParser) -> None:
        pass

    def run(self, args: argparse.Namespace) -> None:
        signal.signal(signal.SIGTERM, self._stopped)    # процесс 1 в контейнере без своего обработчика SIGTERM не слышит
        self._reception.start()
        watched = 0.0
        try:
            while not self._stop.is_set():
                if self._questions is not None and time.monotonic() - watched >= QuestionWatch.EVERY:
                    self._questions.tick()
                    watched = time.monotonic()
                if not self._reception.tick():
                    self._stop.wait(self._poll)
        finally:
            self._reception.stop()

    def stop(self) -> None:
        self._stop.set()

    def _stopped(self, signum: int, frame: FrameType | None) -> None:
        self.stop()


class AnswerCommand:
    """Ответ на один запрос из ящика. Процесс собран с `JERICHO_USER` этого пользователя: «да» и разговор — его."""

    name = "answer"
    help = "ответить на запрос из ящика (файл JSON) — так поручение запускает команда inbox"

    def __init__(self, handle_phrase: HandlePhrase, outbox: Mailbox, gate: ConfirmationGate) -> None:
        self._handle_phrase = handle_phrase
        self._outbox = outbox
        self._gate = gate

    def configure(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("request", type=Path, nargs="?", help="файл запроса: {id, user, chat, text}")
        parser.add_argument("--wait", action="store_true", help="собраться и ждать путь к запросу на stdin — так держит процесс inbox")

    def run(self, args: argparse.Namespace) -> None:
        path = args.request or (self._read_path() if args.wait else None)
        if path is None:
            return              # запросов не будет: приём остановлен
        request = Request.parse(Mailbox.read(path))
        reply = self._handle_phrase.execute(request.text, request.answers, request.reply_to)
        self._outbox.post(request.reply(reply, self._gate.waiting()))

    @staticmethod
    def _read_path() -> Path | None:
        line = sys.stdin.readline().strip()
        return Path(line) if line else None
