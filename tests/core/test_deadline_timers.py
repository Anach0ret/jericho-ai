"""Таймеры срока ручки. `InterruptTimer` — механизм Windows; здесь он проверяется на своём сигнале (`SIGUSR1`),
потому что `SIGBREAK` есть только на Windows. Договор — `docs/security.md`, «Чего каркас не обещает»."""

import signal
import sys
import time

import pytest

from jericho.core.tools.deadline import AlarmTimer, Deadline, InterruptTimer, Timer, ToolTimeout, system_timer

TEST_SIGNAL = getattr(signal, "SIGUSR1", None) or signal.SIGBREAK  # pyright: ignore[reportAttributeAccessIssue]


def busy(seconds: float) -> None:
    """Исполняющийся Python-код: его прерывает любой таймер."""
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        pass


class TestInterruptTimer:
    def test_running_python_code_is_cut_off(self) -> None:
        started = time.monotonic()

        with pytest.raises(ToolTimeout), Deadline(0.05, InterruptTimer(TEST_SIGNAL)).limit():
            busy(2)

        assert time.monotonic() - started < 1

    def test_work_in_time_is_not_disturbed_and_the_handler_comes_back(self) -> None:
        before = signal.getsignal(TEST_SIGNAL)

        with Deadline(2, InterruptTimer(TEST_SIGNAL)).limit():
            busy(0.01)
        time.sleep(0.05)      # таймер отменён: позже прерывание не придёт

        assert signal.getsignal(TEST_SIGNAL) is before

    def test_blocking_wait_delays_the_cut_off_until_it_ends(self) -> None:
        """Договор Windows: блокирующее ожидание прерывание задерживает — ему нужен свой конечный таймаут."""
        started = time.monotonic()

        with pytest.raises(ToolTimeout), Deadline(0.05, InterruptTimer(TEST_SIGNAL)).limit():
            time.sleep(0.3)
            busy(2)

        assert 0.3 <= time.monotonic() - started < 1

    def test_ctrl_c_stays_a_stop_not_a_deadline(self) -> None:
        with pytest.raises(KeyboardInterrupt), Deadline(2, InterruptTimer(TEST_SIGNAL)).limit():
            raise KeyboardInterrupt


@pytest.mark.skipif(not hasattr(signal, "setitimer"), reason="таймер процесса — Linux и macOS")
class TestAlarmTimer:
    def test_blocking_wait_is_cut_off_too(self) -> None:
        started = time.monotonic()

        with pytest.raises(ToolTimeout), Deadline(0.05, AlarmTimer()).limit():
            time.sleep(2)

        assert time.monotonic() - started < 1


def test_system_timer_matches_the_os() -> None:
    timer: Timer = system_timer()

    assert isinstance(timer, AlarmTimer if sys.platform != "win32" else InterruptTimer)
