from collections.abc import Iterator

import keyring
import pytest
from keyring.backend import KeyringBackend
from keyring.errors import KeyringLocked, PasswordDeleteError

from jericho.core import MemorySecretStore, SecretError
from jericho.core.services.adapters.keyring_store import KeyringSecretStore
from jericho.core.services.secrets import NoSecretStore


class Backend(KeyringBackend):
    """Связка ключей в памяти — настоящую системную тесты не трогают."""

    priority = 1  # pyright: ignore[reportAssignmentType]

    def __init__(self) -> None:
        super().__init__()
        self.items: dict[tuple[str, str], str] = {}
        self.locked = False

    def get_password(self, service: str, username: str) -> str | None:
        if self.locked:
            raise KeyringLocked("связка заперта")
        return self.items.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.items[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        if (service, username) not in self.items:
            raise PasswordDeleteError("нет")
        del self.items[(service, username)]


@pytest.fixture
def backend() -> Iterator[Backend]:
    previous, fake = keyring.get_keyring(), Backend()
    keyring.set_keyring(fake)
    yield fake
    keyring.set_keyring(previous)


class TestKeyringSecretStore:
    def test_secret_lives_under_the_assistant_name(self, backend: Backend) -> None:
        store = KeyringSecretStore("assistant")

        store.set("telegram_session", "1BVts…")

        assert backend.items == {("jericho-assistant", "telegram_session"): "1BVts…"}
        assert store.get("telegram_session") == "1BVts…"

    def test_delete_of_a_missing_secret_is_quiet(self, backend: Backend) -> None:
        KeyringSecretStore("home").delete("telegram_session")

    def test_locked_keyring_is_a_port_error(self, backend: Backend) -> None:
        backend.locked = True

        with pytest.raises(SecretError):
            KeyringSecretStore("home").get("telegram_session")


class TestOtherStores:
    def test_no_store_says_how_to_switch_it_on(self) -> None:
        with pytest.raises(SecretError, match="secret_store"):
            NoSecretStore().get("telegram_session")

    def test_memory_store(self) -> None:
        store = MemorySecretStore()
        store.set("a", "1")
        store.delete("a")

        assert store.get("a") is None
