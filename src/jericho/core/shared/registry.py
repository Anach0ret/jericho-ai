"""Службы, которыми навыки пользуются сообща."""

from __future__ import annotations

from typing import Any, cast


class ServiceError(Exception):
    """Служба не подключена или подключена так, что работать не может."""


class SharedServices:
    """Службы по их протоколам: навык просит «окна», а не конкретный оконный менеджер.

    Служба — общий доступ к одной внешней системе: протокол, адаптер и ограничения, которые должны держаться
    всегда. Ручек и текста для модели у неё нет: модель о службе не знает, ею пользуется код навыков.
    Заполняется при сборке, до навыков.
    """

    def __init__(self) -> None:
        self._services: dict[type, object] = {}

    def provide(self, protocol: type, service: object, owner: str) -> None:
        if protocol in self._services:
            raise ServiceError(f"{owner}: {protocol.__name__} is already provided by another service")
        self._services[protocol] = service

    def has(self, protocol: type) -> bool:
        return protocol in self._services

    def get[ServiceT](self, protocol: type[ServiceT]) -> ServiceT:
        """Служба по протоколу. Не подключена — ошибка, которая говорит, что добавить."""
        if protocol not in self._services:
            raise ServiceError(
                f"no service provides {protocol.__name__} — add its package to INSTALLED_SERVICES "
                f"and name it in `requires` of the skill"
            )
        return cast(Any, self._services[protocol])
