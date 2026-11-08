"""Что такое служба для каркаса и как она подключается."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import ClassVar

from jericho.core.conf.settings import Settings
from jericho.core.discovery import PartLoader
from jericho.core.services.core_services import CoreServices
from jericho.core.shared.registry import ServiceError, SharedServices


class ServiceConfig:
    """Служба: описывает себя и собирает свои объекты. Лежит в `service.py` своего пакета.

    Наследник объявляет имя и два метода:

        name       как служба называется; под этим же именем — её раздел настроек
        ready      собрать свои объекты из настроек и служб ядра
        provides   что она даёт навыкам: протокол → объект, который его выполняет

    Что наружу выдаётся только по протоколу, держит правило: навык импортирует из службы её открытые имена
    (то, что названо в `__init__.py` пакета), а до адаптера не дотягивается.
    """

    name: ClassVar[str]

    def ready(self, settings: Settings, core: CoreServices) -> None:
        """Вызывается один раз, до `provides`. `core` — службы ядра, те же, что получает навык."""

    def provides(self) -> Mapping[type, object]:
        return {}


class ServiceLoader:
    """Превращает список пакетов из `INSTALLED_SERVICES` в службы: в каждом — `service.py` с одним классом службы."""

    _PARTS = PartLoader(ServiceConfig, "service", ServiceError, setting="INSTALLED_SERVICES")

    def load(self, installed: Sequence[str]) -> tuple[ServiceConfig, ...]:
        return tuple(self._PARTS.load(package) for package in installed)


def provide_all(services: Sequence[ServiceConfig], settings: Settings, core: CoreServices, shared: SharedServices) -> None:
    """Собирает службы по порядку списка и складывает то, что они дают, в общий реестр."""
    for service in services:
        service.ready(settings, core)
        for protocol, instance in service.provides().items():
            shared.provide(protocol, instance, service.name)
