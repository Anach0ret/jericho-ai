import asyncio
from collections.abc import Callable

from jericho.core.services.adapters.dbus_notify import BY_SERVER, FOREVER, DBusNotifier
from jericho.core.services.notifications import Action, Answer, Notification, Urgency

YES_NO = (Action("yes", "Да"), Action("no", "Нет"))


class Bus:
    """Служба уведомлений на подмене: запоминает показанное и по желанию «нажимает» кнопку сразу после показа."""

    def __init__(self, press: str | None = None, close: bool = False, other_first: bool = False) -> None:
        self.notified: list[tuple[object, ...]] = []
        self.disconnected = False
        self.closed: list[int] = []
        self._press = press
        self._close = close
        self._other_first = other_first
        self._on_action: Callable[[int, str], None] = lambda _id, _key: None
        self._on_closed: Callable[[int, int], None] = lambda _id, _reason: None

    async def notify(
        self, app: str, replaces: int, icon: str, title: str, body: str, actions: list[str], urgency: int, timeout: int, placeholder: str = "",
        transient: bool = False,
    ) -> int:
        self.notified.append((app, replaces, icon, title, body, actions, urgency, timeout, placeholder, transient))
        shown = 40 + len(self.notified)
        loop = asyncio.get_running_loop()
        if self._other_first:
            loop.call_soon(self._on_action, 7, "yes")      # чужое уведомление: на ответ влиять не должно
        if self._press is not None:
            loop.call_soon(self._on_action, shown, self._press)
        if self._close:
            loop.call_soon(self._on_closed, shown, 2)
        return shown

    def on_action(self, handler: Callable[[int, str], None]) -> None:
        self._on_action = handler

    def on_closed(self, handler: Callable[[int, int], None]) -> None:
        self._on_closed = handler

    async def close(self, notification_id: int) -> None:
        self.closed.append(notification_id)

    def disconnect(self) -> None:
        self.disconnected = True


def notifier(bus: Bus, icon: str = "jericho") -> DBusNotifier:
    async def connect() -> Bus:
        return bus

    return DBusNotifier(icon=icon, connect=connect)


class TestShow:
    def test_shows_with_icon_and_returns_the_id(self) -> None:
        bus = Bus()

        shown = notifier(bus).show(Notification("Jericho", "готово", Urgency.LOW, timeout_ms=5000), replaces=7)

        assert shown == 41
        assert bus.notified == [("Jericho", 7, "jericho", "Jericho", "готово", [], 0, 5000, "", False)]
        assert bus.disconnected

    def test_private_reply_is_kept_out_of_the_panel_history(self) -> None:
        bus = Bus()

        notifier(bus).show(Notification("Jericho", "Марина пишет: …", transient=True))

        assert bus.notified[0][9] is True

    def test_without_timeout_the_panel_decides(self) -> None:
        bus = Bus()

        notifier(bus).show(Notification("Jericho"))

        assert bus.notified[0][1] == 0
        assert bus.notified[0][7] == BY_SERVER

    def test_no_bus_does_not_raise(self) -> None:
        async def connect() -> Bus:
            raise OSError("no session bus")

        assert DBusNotifier(connect=connect).show(Notification("Jericho")) is None


class TestAsk:
    def test_pressed_button_comes_back(self) -> None:
        bus = Bus(press="yes")

        answer = notifier(bus).ask(Notification("Jericho · вопрос", "Закрыть 3 окна?", actions=YES_NO), wait=1)

        assert answer == Answer(41, "yes")
        assert bus.notified[0][5] == ["yes", "Да", "no", "Нет"]
        assert bus.notified[0][7] == FOREVER      # вопрос висит, пока не ответят
        assert bus.disconnected

    def test_closed_without_a_button_is_no_answer(self) -> None:
        assert notifier(Bus(close=True)).ask(Notification("Jericho", actions=YES_NO), wait=1) == Answer(41, None)

    def test_nobody_pressed_in_time_and_the_buttons_are_taken_away(self) -> None:
        bus = Bus()

        assert notifier(bus).ask(Notification("Jericho", actions=YES_NO), wait=0.01) == Answer(41, None)
        assert bus.closed == [41]

    def test_buttons_of_another_notification_are_ignored(self) -> None:
        assert notifier(Bus(press="no", other_first=True)).ask(Notification("Jericho", actions=YES_NO), wait=1) == Answer(41, "no")

    def test_typed_reply_comes_back_as_text(self) -> None:
        """Noctalia присылает набранное через ActionInvoked: «inline-reply::<текст>» (проба 23.10.2026)."""
        bus = Bus(press="inline-reply::Иванова")

        answer = notifier(bus).ask(Notification("Jericho · вопрос", "Какую Марину?", reply="Ответить…"), wait=1)

        assert answer == Answer(41, Answer.REPLY, "Иванова")
        assert bus.notified[0][5] == ["inline-reply", "Ответить"]
        assert bus.notified[0][8] == "Ответить…"

    def test_no_bus_is_no_answer(self) -> None:
        async def connect() -> Bus:
            raise OSError("no session bus")

        assert DBusNotifier(connect=connect).ask(Notification("Jericho", actions=YES_NO), wait=1) == Answer(None, None)
