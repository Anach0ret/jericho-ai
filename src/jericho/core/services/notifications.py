"""Уведомление — то, что пользователь видит на экране: ответ на голосовую фразу, напоминание, итог задачи."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import ClassVar, Protocol

from jericho.core.agent.entities import ReplyStatus


class Urgency(StrEnum):
    LOW = "low"              # мелькнуло и пропало
    NORMAL = "normal"
    CRITICAL = "critical"    # висит, пока не закроют


@dataclass(frozen=True, slots=True)
class Action:
    """Кнопка в уведомлении: `label` видит человек, `key` возвращается, когда её нажали."""

    key: str
    label: str


@dataclass(frozen=True, slots=True)
class Notification:
    title: str
    body: str = ""
    urgency: Urgency = Urgency.NORMAL
    timeout_ms: int | None = None    # None — как решит панель уведомлений
    actions: tuple[Action, ...] = ()
    reply: str | None = None         # поле для ответа текстом: подсказка в нём; None — поля нет
    transient: bool = False          # не хранить в истории уведомлений панели: в тексте может быть личная переписка


@dataclass(frozen=True, slots=True)
class Answer:
    """Чем кончилось уведомление с кнопками. `action` — ключ нажатой кнопки; None — закрыли, не дождались, не показалось.

    Ответ текстом из поля — `action` = `REPLY`, сам текст — в `text`.
    """

    REPLY: ClassVar[str] = "reply"

    id: int | None      # номер показанного уведомления: на его место встанет итог
    action: str | None
    text: str = ""


class Notifier(Protocol):
    """Показывает уведомления. Сбой показа не должен ломать команду, поэтому ошибок не бросает."""

    def show(self, notification: Notification, replaces: int | None = None) -> int | None:
        """Показать уведомление, при `replaces` — на месте прежнего. Возвращает номер для замены."""
        ...


class AskingNotifier(Notifier, Protocol):
    """Показывает уведомление с кнопками и ждёт нажатия. Умеет не всякий адаптер: `notify-send` у Noctalia — нет."""

    def ask(self, notification: Notification, wait: float, replaces: int | None = None) -> Answer:
        """Показать и ждать нажатия не дольше `wait` секунд. Сбой показа — `Answer(None, None)`, ошибок не бросает."""
        ...


class StatusLook:
    """Как исход поручения выглядит в уведомлении: приписка к заголовку и срочность. Одно правило на голос и расписание.

    Сколько уведомление висит, здесь не решается: ответ на голосовую фразу человек ждёт и читает сразу,
    а напоминание по расписанию может прийти, когда его нет у экрана.
    """

    SUFFIXES: Mapping[ReplyStatus, str] = {
        ReplyStatus.CLARIFY: " · вопрос",
        ReplyStatus.REFUSED: " · не сделано",
        ReplyStatus.IGNORED: " · не команда",
        ReplyStatus.FAILED: " · сбой",
        ReplyStatus.STOPPED: " · остановлено",
    }
    URGENCY: Mapping[ReplyStatus, Urgency] = {ReplyStatus.FAILED: Urgency.CRITICAL, ReplyStatus.IGNORED: Urgency.LOW}

    def __init__(self, app: str) -> None:
        self._app = app      # заголовок уведомлений: имя ассистента

    def title(self, status: ReplyStatus) -> str:
        return self._app + self.SUFFIXES.get(status, "")

    def urgency(self, status: ReplyStatus) -> Urgency:
        return self.URGENCY.get(status, Urgency.NORMAL)
