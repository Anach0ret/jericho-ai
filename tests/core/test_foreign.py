import logging

import pytest

from jericho.core import ForeignText


class TestForeignText:
    def test_first_read_goes_to_the_journal_once(self, caplog: pytest.LogCaptureFixture) -> None:
        foreign = ForeignText()

        with caplog.at_level(logging.INFO, logger="jericho"):
            foreign.read_from("Evil.example")
            foreign.read_from("evil.example")

        assert [record.msg for record in caplog.records] == ["foreign"]
        assert foreign.sources == frozenset({"evil.example"})

    def test_restored_source_counts_but_is_not_journaled_again(self, caplog: pytest.LogCaptureFixture) -> None:
        """Журнал 23.10.2026: окно на панели собирало ассистента раз в 2 с — и каждый раз писало `foreign` заново."""
        foreign = ForeignText()

        with caplog.at_level(logging.INFO, logger="jericho"):
            foreign.restore("telegram:мама")

        assert caplog.records == [] and foreign.sources == frozenset({"telegram:мама"})
