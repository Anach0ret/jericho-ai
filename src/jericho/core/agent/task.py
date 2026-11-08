"""Поручение и слои вокруг него — как слои вокруг вызова ручки, только вокруг всего пути «поручение → ответ»."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from functools import partial
from typing import Protocol

from jericho.core.agent.entities import AgentReply


@dataclass(frozen=True, slots=True)
class Task:
    """Одно поручение: что сказал пользователь и что из этого уйдёт модели."""

    text: str        # как пришло: фраза, строка из терминала, задача по расписанию
    message: str     # сообщение для модели; слой может дополнить его тем, что знает сам
    attended: bool = True   # есть ли рядом человек: без него нечего помнить для разговора и некого переспросить


@dataclass(frozen=True, slots=True)
class Outcome:
    """Итог поручения: ответ пользователю и сведения для журнала."""

    reply: AgentReply
    details: Mapping[str, object] = field(default_factory=dict)


type TaskHandler = Callable[[Task], Outcome]
"""Тот, кто доводит поручение до итога: следующий слой или сам разговор с моделью."""


class TaskLayer(Protocol):
    """Слой вокруг поручения: может дополнить его до модели и итог — после.

    Каркас о таких слоях ничего не знает: память разговора, заметки и всё, что помнится между поручениями,
    приходят сюда снаружи. Один метод вместо пары «до» и «после» — чтобы то, что слой запомнил до вызова,
    оставалось обычной локальной переменной.
    """

    def handle(self, task: Task, proceed: TaskHandler) -> Outcome: ...


def chain(layers: Sequence[TaskLayer], core: TaskHandler) -> TaskHandler:
    """Цепочка слоёв вокруг `core`. Первый в списке — самый внешний: видит поручение первым, а итог последним."""
    handler = core
    for layer in reversed(layers):
        handler = partial(layer.handle, proceed=handler)
    return handler
