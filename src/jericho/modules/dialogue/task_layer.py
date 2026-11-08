"""Слой «разговор»: следующая фраза может быть ответом на вопрос Jericho."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace

from jericho.core.agent.entities import ReplyStatus
from jericho.core.agent.task import Outcome, Task, TaskHandler
from jericho.modules.dialogue.entities import Exchange
from jericho.modules.dialogue.protocols import ConversationMemory


class Conversation:
    """До модели — прикладывает к фразе вопрос, на который она, скорее всего, отвечает; после — запоминает обмен."""

    # «Не команда» и сбои не запоминаются: они не должны вытеснять из памяти заданный вопрос.
    _MEMORABLE = frozenset({ReplyStatus.DONE, ReplyStatus.CLARIFY, ReplyStatus.REFUSED})
    SHORT = 4       # слов: «только первый вопрос», «а второй?» — продолжение, а не новая команда

    def __init__(
        self, memory: ConversationMemory, foreign_read: Callable[[], Sequence[str]] = tuple, private: Callable[[], Sequence[str]] = tuple
    ) -> None:
        self._memory = memory
        self._foreign_read = foreign_read      # чей чужой текст читали в этой фразе — его пометка едет вместе с ответом
        self._private = private                # пометки личных ручек этой фразы: запоминаются они, а не ответ

    def handle(self, task: Task, proceed: TaskHandler) -> Outcome:
        if not task.attended:      # поручение по расписанию — не реплика разговора: его ответ не ждёт продолжения
            return proceed(task)
        outcome = proceed(replace(task, message=self._message(task.message)))
        if outcome.reply.status in self._MEMORABLE:
            memos = self._private()
            # Была чужая переписка — в памяти что сделано («прочитал чат с Мариной: 3 сообщения»), а не пересказ.
            hint = " (полный текст ответа — ручка last_reply)"
            reply = replace(outcome.reply, message="; ".join(memos) + hint, body="") if memos else outcome.reply
            self._memory.remember(task.text, reply, self._foreign_read())
        return outcome

    def _message(self, phrase: str) -> str:
        """Что уходит модели как сообщение пользователя.

        Если Jericho только что задал вопрос, новая фраза — скорее всего ответ на него. Тогда вместе с ней
        идут исходная фраза и вопрос: рядом с ответом модель их не теряет, а в промпте — теряла
        (журнал 11.10.2026: после уточнения проект открылся не на том столе).
        """
        recent = self._memory.recent()
        asked: list[Exchange] = []
        for exchange in reversed(recent):
            if exchange.status is not ReplyStatus.CLARIFY:
                break
            asked.insert(0, exchange)
        if not asked:
            return self._with_last(phrase, recent[-1]) if recent and len(phrase.split()) <= self.SHORT else phrase
        dialogue = "\n".join(f"— пользователь: «{exchange.phrase}»\n— ты спросил: «{exchange.said}»" for exchange in asked)
        return (
            f"{phrase}\n\n"
            f"[Перед этим шёл разговор:\n{dialogue}\n"
            "Новая фраза — скорее всего ответ на твой вопрос. Собери полную команду из всего разговора: то, что "
            "названо раньше (стол, редактор, приложение) и о чём ты не спрашивал, остаётся в силе. "
            "Если новая фраза — явно другая команда, выполняй её.]"
        )

    @staticmethod
    def _with_last(phrase: str, last: Exchange) -> str:
        """Короткая фраза после ответа — с этим ответом рядом. Журнал 29.10.2026: на «только первый вопрос» после отчёта
        о шаге модель ответила «вижу только эту фразу» — ответ был в промпте, но далеко от фразы."""
        return (
            f"{phrase}\n\n"
            f"[Перед этим: пользователь «{last.phrase}» → ты ({last.status.value}): «{last.said}». Короткая фраза — "
            "скорее всего продолжение этого: ответ, уточнение, поправка. Если это явно другая команда — выполняй её.]"
        )
