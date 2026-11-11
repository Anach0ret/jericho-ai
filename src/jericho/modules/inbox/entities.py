"""Запрос из ящика и ответ на него — то, о чём договорены ассистент и транспорт."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from jericho.core.agent.entities import AgentReply
from jericho.core.services.confirmation import PendingConfirmation


def identifier(value: object) -> str | None:
    """Идентификаторы Telegram — числа: принимаем и их, но дальше это строки."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    return value if isinstance(value, str) else None


@dataclass(frozen=True, slots=True)
class Request:
    """Сообщение пользователя: `{"id", "user", "chat", "text"}`, от кнопки — `answers`, ответом на сообщение —
    `reply_to` (его номер у транспорта). Пришло снаружи — поля проверяются при разборе."""

    id: str
    user: str
    chat: str        # куда транспорт вернёт ответ; ассистенту он не нужен, только переносится в ответ
    text: str
    answers: str = ""    # id вопроса «да?» (`confirm_id`), под которым нажата кнопка: «да» засчитается только ему
    reply_to: str = ""   # номер сообщения транспорта, на которое это ответ (Telegram reply); пусто — не ответом

    @classmethod
    def parse(cls, data: Mapping[str, object]) -> Request:
        """Не того вида — `ValueError`: такой запрос не выполняется, а откладывается в сторону."""
        id_, user, chat = (identifier(data.get(name)) for name in ("id", "user", "chat"))
        text, answers = data.get("text"), data.get("answers", "")
        reply_to = identifier(data.get("reply_to", ""))
        if not (id_ and user and chat) or not isinstance(text, str) or not isinstance(answers, str) or reply_to is None:
            raise ValueError("request needs id, user, chat and text as strings (answers and reply_to, if given, too)")
        return cls(id_, user, chat, text, answers, reply_to)

    def reply(self, reply: AgentReply, question: PendingConfirmation | None = None) -> dict[str, object]:
        """Ответ транспорту: на какой запрос, в какой чат, со статусом, строкой и подробностями.

        `question` — вопрос, который ждёт «да»: транспорт может показать к ответу кнопки «Да» и «Нет», а с нажатием
        вернуть `confirm_id` в поле `answers`.
        """
        return {
            "id": self.id, "user": self.user, "chat": self.chat,
            "status": reply.status.value, "title": reply.message, "text": reply.body,
            **({"confirm": question.summary, "confirm_id": question.id} if question is not None else {}),
        }


@dataclass(frozen=True, slots=True)
class Receipt:
    """Квитанция транспорта на сообщение без запроса: `{"receipt": notice, "delivered": bool, "messages": [номера]}`.

    `delivered: false` — не дошло (или дошло не целиком): повторить можно, считать доставленным — нет."""

    notice: str
    delivered: bool
    messages: tuple[str, ...] = ()

    @classmethod
    def parse(cls, data: Mapping[str, object]) -> Receipt | None:
        """Не квитанция — None; квитанция не того вида — `ValueError`."""
        if "receipt" not in data:
            return None
        notice, delivered, messages = data.get("receipt"), data.get("delivered"), data.get("messages", [])
        if not isinstance(notice, str) or not notice or not isinstance(delivered, bool) or not isinstance(messages, list):
            raise ValueError("receipt needs notice id, delivered as bool and messages as a list")
        numbers = tuple(identifier(message) for message in messages)
        if any(number is None for number in numbers):
            raise ValueError("receipt messages are ids: strings or numbers")
        return cls(notice, delivered, tuple(number for number in numbers if number is not None))
