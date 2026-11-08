"""Что такое бэкенд модели для каркаса.

Бэкенд — способ дойти до модели и провести с ней цикл «модель → ручка → модель». Каркас знает о нём один
порт — `AgentBackend` — и выбирает бэкенд по имени пакета из настроек (`agent.backend`), как Django выбирает
движок базы. Бэкенд может принести и свои команды: программа `claude`, например, сама поднимает сервер ручек.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, ClassVar

from jericho.core.agent.entities import BackendAnswer
from jericho.core.agent.protocols import AgentBackend, AgentBackendError
from jericho.core.conf.settings import Settings, SettingsSection
from jericho.core.discovery import PartLoader
from jericho.core.management.base import Command
from jericho.core.services.foreign import ForeignText
from jericho.core.services.phrase_deadline import PhraseDeadline
from jericho.core.tools.dispatcher import ToolDispatcher
from jericho.core.tools.tool import Tool


class BackendError(Exception):
    """Бэкенд из настроек не удалось подключить."""


@dataclass(frozen=True, slots=True)
class BackendServices:
    """Всё, что бэкенд получает от каркаса в `ready()`."""

    settings: Settings
    tools: tuple[Tool[Any], ...]              # всё, что можно отдать модели
    dispatcher: ToolDispatcher                # вызов ручки идёт только через него — со всеми слоями
    reply_schema: Mapping[str, object]        # в каком виде модель обязана ответить
    launch: tuple[str, ...]                   # как запустить Jericho ещё раз — для бэкенда, который поднимает процесс
    child_environment: Mapping[str, str]      # что такой процесс должен унаследовать: проект, вариант настроек, запуск
    check_reply: Callable[[Mapping[str, object]], object] = field(default=lambda reply: None)   # форма ответа: не по ней — ValueError
    foreign: ForeignText = field(default_factory=ForeignText)   # учёт чужого текста этого запуска: бэкенд может сам его читать
    deadline: PhraseDeadline = field(default_factory=PhraseDeadline)   # срок фразы: остаток — модели, момент — серверу ручек


class BackendConfig:
    """Бэкенд: описывает себя и собирает свои объекты. Лежит в `backend.py` своего пакета."""

    name: ClassVar[str]
    settings_class: ClassVar[type[SettingsSection] | None] = None    # свой раздел настроек (под именем `name`); None — нет

    def ready(self, services: BackendServices) -> None:
        """Вызывается один раз, до `backend` и `commands`."""

    def backend(self) -> AgentBackend:
        raise NotImplementedError

    def commands(self) -> Sequence[Command]:
        return ()


class _NotChosen:
    def ask(self, system_prompt: str, phrase: str) -> BackendAnswer:
        raise AgentBackendError("no model backend: set agent.backend in the settings, for example jericho.backends.claude_cli")


class NoBackend(BackendConfig):
    """Бэкенд не выбран: ассистент собирается, ручки работают из терминала, но на поручение отвечает сбоем."""

    name = "none"

    def backend(self) -> AgentBackend:
        return _NotChosen()


class BackendLoader:
    """Находит бэкенд по имени пакета: в нём `backend.py` с одним классом бэкенда. Пустое имя — бэкенд не выбран."""

    _PARTS = PartLoader(BackendConfig, "backend", BackendError, setting="agent.backend", required=())

    def load(self, package: str) -> BackendConfig:
        return self._PARTS.load(package) if package else NoBackend()
