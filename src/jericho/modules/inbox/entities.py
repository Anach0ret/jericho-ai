"""Запрос из ящика и ответ на него — то, о чём договорены ассистент и транспорт."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from jericho.core.agent.entities import AgentReply
from jericho.core.services.confirmation import PendingConfirmation


@dataclass(frozen=True, slots=True)
class Request:
    """Сообщение пользователя: `{"id", "user", "chat", "text"}` и, от кнопки, `answers`. Пришло снаружи — поля
    проверяются при разборе."""

    id: str
    user: str
    chat: str        # куда транспорт вернёт ответ; ассистенту он не нужен, только переносится в ответ
    text: str
    answers: str = ""    # id вопроса «да?» (`confirm_id`), под которым нажата кнопка: «да» засчитается только ему

    @classmethod
    def parse(cls, data: Mapping[str, object]) -> Request:
        """Не того вида — `ValueError`: такой запрос не выполняется, а откладывается в сторону."""
        id_, user, chat = (cls._identifier(data.get(name)) for name in ("id", "user", "chat"))
        text, answers = data.get("text"), data.get("answers", "")
        if not (id_ and user and chat) or not isinstance(text, str) or not isinstance(answers, str):
            raise ValueError("request needs id, user, chat and text as strings (answers, if given, too)")
        return cls(id_, user, chat, text, answers)

    @staticmethod
    def _identifier(value: object) -> str | None:
        """Идентификаторы Telegram — числа: принимаем и их, но дальше это строки."""
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return str(value)
        return value if isinstance(value, str) else None

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
