import argparse
from datetime import timedelta

import pytest

from jericho.core.services.adapters.memory_list import MemoryList
from jericho.core.services.lock import Unlocked
from jericho.modules.tasks.command import DeferredCommand
from jericho.modules.tasks.entities import Deferred, DeferredKind
from jericho.modules.tasks.queue import DeferredQueue
from jericho.modules.tasks.tests.fakes import START, Clock


def run(queue: DeferredQueue, *argv: str) -> None:
    command = DeferredCommand(queue)
    parser = argparse.ArgumentParser()
    command.configure(parser)
    command.run(parser.parse_args(list(argv)))


class TestDeferredCommand:
    def setup_method(self) -> None:
        self.queue = DeferredQueue(MemoryList[Deferred](), Unlocked(), Clock())

    def test_lists_waiting_items(self, capsys: pytest.CaptureFixture[str]) -> None:
        item = self.queue.add(DeferredKind.REMIND, "выключить духовку", START + timedelta(minutes=30))

        run(self.queue)

        assert item.id in capsys.readouterr().out

    def test_cancel_by_id_without_confirmation(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Снимает человек сам кнопкой в окне: «да» спрашивают у модели, а не у человека."""
        item = self.queue.add(DeferredKind.DO, "сводка по почте", START + timedelta(hours=1))

        run(self.queue, "--cancel", item.id)

        assert self.queue.pending() == []
        assert "сводка по почте" in capsys.readouterr().out

    def test_unknown_id_is_an_error(self) -> None:
        with pytest.raises(SystemExit):
            run(self.queue, "--cancel", "nope")
