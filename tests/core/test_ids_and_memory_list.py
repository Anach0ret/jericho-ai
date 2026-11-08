import secrets

import pytest

from jericho.core.services.adapters.memory_list import MemoryList
from jericho.core.services.ids import short_id


def test_short_id_skips_what_is_taken(monkeypatch: pytest.MonkeyPatch) -> None:
    drawn = iter(["aaaaaa", "aaaaaa", "bbbbbb"])
    monkeypatch.setattr(secrets, "token_hex", lambda size: next(drawn))

    assert short_id({"aaaaaa"}) == "bbbbbb"


def test_memory_list_hands_out_copies() -> None:
    store = MemoryList[str](["раз"])
    store.load().append("чужое")
    store.save(["раз", "два"])

    assert store.load() == ["раз", "два"]
