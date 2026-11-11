"""Службы, которые ядро выдаёт навыку при сборке."""

from __future__ import annotations

from dataclasses import dataclass, field

from jericho.core.services.clock import Clock
from jericho.core.services.confirmation import ConfirmationGate
from jericho.core.services.foreign import ForeignText
from jericho.core.services.own_paths import OwnPaths
from jericho.core.services.paths import Paths
from jericho.core.services.run_facts import RunFacts
from jericho.core.services.runner import CommandRunner
from jericho.core.services.secrets import NoSecretStore, SecretStore
from jericho.core.shared.registry import SharedServices


@dataclass(frozen=True, slots=True)
class CoreServices:
    """Всё, что навык получает от ядра в `ready()`. Поля названы и типизированы — службу не ищут по имени."""

    runner: CommandRunner              # запуск внешних программ
    confirmation: ConfirmationGate     # двухшаговое подтверждение действий с последствиями
    paths: Paths                       # где хранить свои файлы
    dry_run: bool = False              # «вхолостую»: адаптер, который действует не через runner, сам не меняет мир
    foreign: ForeignText = field(default_factory=ForeignText)   # чей текст модель уже прочитала в этой фразе
    clock: Clock = field(default_factory=Clock)                 # который час — в поясе из настроек
    shared: SharedServices = field(default_factory=SharedServices)   # службы, общие для навыков: `core.shared.get(Windows)`
    secrets: SecretStore = field(default_factory=NoSecretStore)      # ключи и сессии — в связке ключей, а не в файле
    user: str = ""                     # чьё поручение (`JERICHO_USER`, у серверного — Telegram ID); пусто — ассистент одного человека
    own_paths: OwnPaths = field(default_factory=OwnPaths)       # папки самого ассистента: файловые ручки их не трогают (после `user`: позиционный вызов не сдвигается)
    facts: RunFacts = field(default_factory=RunFacts)           # данные события для уведомления по итогам запуска (окно, фильтры)
