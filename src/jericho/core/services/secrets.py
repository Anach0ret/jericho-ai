"""Секреты — ключи и сессии, которым не место в файле: системная связка ключей вместо файла на диске."""

from __future__ import annotations

from typing import Protocol

from jericho.core.errors import PortError


class SecretError(PortError):
    """Хранилище секретов недоступно: нет службы Secret Service, связка ключей заперта, отказ в доступе."""

    code = "secret_store_unavailable"


class SecretStore(Protocol):
    """Секреты ассистента по имени («telegram_session»). Любая неудача — SecretError; нет секрета — None.

    Против чего: файл с ключом утекает сам — в резервную копию, синхронизацию папки, архив домашнего каталога,
    случайный коммит; связка ключей зашифрована на диске и открывается вместе с входом в систему. Против программы,
    запущенной от того же пользователя, пока сеанс открыт, — не защищает: она спросит связку так же, как ассистент.
    """

    def get(self, name: str) -> str | None: ...
    def set(self, name: str, value: str) -> None: ...
    def delete(self, name: str) -> None: ...


class NoSecretStore:
    """Хранилища нет (`secret_store = "none"`, сервер в контейнере): кто его спросит — узнает, как включить."""

    def get(self, name: str) -> str | None:
        raise SecretError("хранилище секретов не включено: secret_store = \"keyring\" в настройках проекта")

    def set(self, name: str, value: str) -> None:
        self.get(name)

    def delete(self, name: str) -> None:
        self.get(name)


class MemorySecretStore:
    """Секреты в памяти: для тестов и прогона проверочных фраз — системную связку ключей не трогает."""

    def __init__(self, secrets: dict[str, str] | None = None) -> None:
        self.secrets = dict(secrets or {})

    def get(self, name: str) -> str | None:
        return self.secrets.get(name)

    def set(self, name: str, value: str) -> None:
        self.secrets[name] = value

    def delete(self, name: str) -> None:
        self.secrets.pop(name, None)
