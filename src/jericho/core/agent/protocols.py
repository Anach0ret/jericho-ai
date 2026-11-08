"""Разговор с моделью: то, что каркасу нужно от бэкенда."""

from __future__ import annotations

from typing import Protocol

from jericho.core.agent.entities import BackendAnswer


class AgentBackendError(Exception):
    """Модель недоступна, не уложилась во время или ответила ошибкой."""


class ModelTimeout(AgentBackendError):
    """Поручение не уложилось в срок фразы (`agent.timeout`): модель и ручки работали дольше. Что успело
    выполниться, видно в журнале; запасному бэкенду такое поручение не передаётся — часть его уже сделана."""


class ModelUnavailable(AgentBackendError):
    """Модель не взялась за поручение: исчерпан лимит или она перегружена. Другой бэкенд может справиться —
    если в настройках есть запасной (`agent.fallback_backends`), поручение уходит ему."""


class AgentBackend(Protocol):
    """Модель с подключёнными инструментами. Сама ведёт цикл «вызов → результат → следующий ход»."""

    def ask(self, system_prompt: str, phrase: str) -> BackendAnswer: ...
