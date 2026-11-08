"""Секреты в системной связке ключей (Secret Service: gnome-keyring, KWallet) через стандартную библиотеку keyring."""

from __future__ import annotations

import keyring
from keyring.errors import KeyringError, PasswordDeleteError

from jericho.core.services.secrets import SecretError


class KeyringSecretStore:
    """Каждый секрет — запись связки с «службой» `jericho-<проект>` и именем секрета: видно, чьё это, в «Паролях»."""

    def __init__(self, project: str) -> None:
        self._service = f"jericho-{project}"

    def get(self, name: str) -> str | None:
        try:
            return keyring.get_password(self._service, name)
        except KeyringError as error:
            raise SecretError(f"связка ключей не ответила: {error}") from error

    def set(self, name: str, value: str) -> None:
        try:
            keyring.set_password(self._service, name, value)
        except KeyringError as error:
            raise SecretError(f"связка ключей не сохранила секрет: {error}") from error

    def delete(self, name: str) -> None:
        try:
            keyring.delete_password(self._service, name)
        except PasswordDeleteError:
            return                       # и так нет
        except KeyringError as error:
            raise SecretError(f"связка ключей не удалила секрет: {error}") from error
