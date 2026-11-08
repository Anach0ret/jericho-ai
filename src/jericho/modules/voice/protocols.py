"""Голосовая команда: распознавание речи. Уведомления — служба ядра (`core/services/notifications.py`)."""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol


class SpeechRecognizerError(Exception):
    """Распознавание речи не запустилось или не ответило вовремя."""


class AnswerLauncher(Protocol):
    """Отдаёт нажатую кнопку новому запуску ассистента.

    Свой вопрос запуск подтвердить не может: «да» засчитывается только от другого запуска (`ConfirmationGate`),
    как голосовое «да» — следующей фразой. Поэтому кнопка — это следующая фраза, сказанная нажатием.
    """

    def answer(self, action: str, replaces: int, text: str = "", question: str = "") -> None:
        """`action` — ключ кнопки («yes», «no», «reply»); `replaces` — уведомление, на месте которого показать итог;
        `text` — набранное в поле ответа; `question` — id вопроса «да?», под которым нажато (пусто — вопроса не было)."""
        ...


class SpeechRecognizer(Protocol):
    """Слушает микрофон и возвращает распознанную фразу. Пустая строка — ничего не сказано."""

    def listen(self) -> str: ...

    def stop(self) -> None:
        """Закончить идущую запись — как отпущенная клавиша: `listen()` вернёт услышанное. Записи нет — ничего."""
        ...


class VoiceState(StrEnum):
    """Чем сейчас занят голос — то, что показывает значок на панели."""

    IDLE = "idle"              # свободен; рядом — последний ответ
    LISTENING = "listening"    # пишет микрофон
    THINKING = "thinking"      # фраза у модели или выполняется
    WAITING = "waiting"        # висит вопрос: ждёт «да», кнопку или ответ текстом


class StatusBoard(Protocol):
    """Куда сообщить, чем занят голос. Читает это кто-то снаружи — виджет панели; каркас о нём не знает.

    Сбой записи не должен ломать фразу, поэтому ошибок не бросает.
    """

    def set(self, state: VoiceState, detail: str = "") -> None:
        """`detail` — услышанная фраза, вопрос или последний ответ: для подсказки у значка."""
        ...
