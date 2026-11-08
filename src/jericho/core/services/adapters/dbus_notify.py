"""Уведомления прямо по D-Bus (спецификация freedesktop): с кнопками и ожиданием ответа.

Почему не `notify-send`: libnotify 0.8 у Noctalia кнопки не показывает («Actions are not supported»), хотя панель
их объявляет. Почему не `desktop-notifier`: у него нет замены уведомления на месте (`replaces_id` всегда 0),
а голос показывает «слышу…» и на его месте — ответ. `dbus-fast` — библиотека, на которой стоит и он.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Protocol

from dbus_fast import Variant
from dbus_fast.aio import MessageBus
from dbus_fast.errors import DBusError

from jericho.core.services.notifications import Answer, Notification, Urgency

logger = logging.getLogger(__name__)

SERVICE = "org.freedesktop.Notifications"
PATH = "/org/freedesktop/Notifications"
URGENCY: dict[Urgency, int] = {Urgency.LOW: 0, Urgency.NORMAL: 1, Urgency.CRITICAL: 2}
# Поле ответа (возможность «inline-reply»): кнопка с этим ключом и подсказка в поле — как у KDE. Noctalia присылает
# набранный текст через ActionInvoked с ключом «inline-reply::<текст>», а не отдельным сигналом NotificationReplied.
INLINE_REPLY = "inline-reply"
REPLY_PREFIX = INLINE_REPLY + "::"
REPLY_BUTTON = "Ответить"
FOREVER = 0       # срок показа по спецификации: 0 — висит, пока не ответят; -1 — как решит панель
BY_SERVER = -1


class NotificationsBus(Protocol):
    """То, что адаптеру нужно от службы уведомлений. Настоящая — `DBusNotifications`, в тестах — подмена."""

    async def notify(
        self, app: str, replaces: int, icon: str, title: str, body: str, actions: list[str], urgency: int, timeout: int, placeholder: str = "",
        transient: bool = False,
    ) -> int: ...
    def on_action(self, handler: Callable[[int, str], None]) -> None: ...
    def on_closed(self, handler: Callable[[int, int], None]) -> None: ...
    async def close(self, notification_id: int) -> None: ...
    def disconnect(self) -> None: ...


class DBusNotifications:
    """Служба уведомлений сеанса через `dbus-fast`."""

    def __init__(self, bus: MessageBus, interface: object) -> None:
        self._bus = bus
        self._interface = interface    # у прокси dbus-fast методы появляются при разборе описания службы

    @classmethod
    async def connect(cls) -> DBusNotifications:
        bus = await MessageBus().connect()
        proxy = bus.get_proxy_object(SERVICE, PATH, await bus.introspect(SERVICE, PATH))
        return cls(bus, proxy.get_interface(SERVICE))

    async def notify(
        self, app: str, replaces: int, icon: str, title: str, body: str, actions: list[str], urgency: int, timeout: int, placeholder: str = "",
        transient: bool = False,
    ) -> int:
        hints = {"urgency": Variant("y", urgency)}
        if transient:
            hints["transient"] = Variant("b", True)       # спецификация: панель не кладёт уведомление в историю
        if placeholder:
            hints["x-kde-reply-placeholder-text"] = Variant("s", placeholder)
        return await self._interface.call_notify(app, replaces, icon, title, body, actions, hints, timeout)  # pyright: ignore[reportAttributeAccessIssue]

    def on_action(self, handler: Callable[[int, str], None]) -> None:
        self._interface.on_action_invoked(handler)  # pyright: ignore[reportAttributeAccessIssue]

    def on_closed(self, handler: Callable[[int, int], None]) -> None:
        self._interface.on_notification_closed(handler)  # pyright: ignore[reportAttributeAccessIssue]

    async def close(self, notification_id: int) -> None:
        await self._interface.call_close_notification(notification_id)  # pyright: ignore[reportAttributeAccessIssue]

    def disconnect(self) -> None:
        self._bus.disconnect()


class DBusNotifier:
    """Показывает уведомления и ждёт нажатия кнопки. Каждый вызов — своё короткое соединение с шиной сеанса."""

    def __init__(
        self, app_name: str = "Jericho", icon: str = "", connect: Callable[[], Awaitable[NotificationsBus]] = DBusNotifications.connect
    ) -> None:
        self._app_name = app_name
        self._icon = icon      # имя из темы значков («jericho») или путь к файлу; пусто — значок решает панель
        self._connect = connect

    def show(self, notification: Notification, replaces: int | None = None) -> int | None:
        try:
            return asyncio.run(self._show(notification, replaces))
        except (DBusError, OSError, ValueError) as error:
            logger.warning("notify_failed", extra={"data": {"error": str(error), "title": notification.title}})
            return None

    def ask(self, notification: Notification, wait: float, replaces: int | None = None) -> Answer:
        """Не дождались нажатия — уведомление убирается: висеть с кнопками, которые ничего не сделают, ему незачем."""
        try:
            return asyncio.run(self._ask(notification, wait, replaces))
        except (DBusError, OSError, ValueError) as error:
            logger.warning("notify_failed", extra={"data": {"error": str(error), "title": notification.title}})
            return Answer(None, None)

    async def _show(self, notification: Notification, replaces: int | None) -> int:
        bus = await self._connect()
        try:
            return await self._notify(bus, notification, replaces, self._timeout(notification))
        finally:
            bus.disconnect()

    async def _ask(self, notification: Notification, wait: float, replaces: int | None) -> Answer:
        bus = await self._connect()
        try:
            shown: list[int] = []     # номер узнаём после показа, а сигналы шины приходят про все уведомления сразу
            answer: asyncio.Future[str | None] = asyncio.get_running_loop().create_future()

            def settle(notification_id: int, action: str | None) -> None:
                if notification_id in shown and not answer.done():
                    answer.set_result(action)

            bus.on_action(settle)
            bus.on_closed(lambda notification_id, _reason: settle(notification_id, None))
            shown.append(await self._notify(bus, notification, replaces, FOREVER))
            try:
                return self._answer(shown[0], await asyncio.wait_for(answer, wait))
            except TimeoutError:
                await bus.close(shown[0])      # кнопки уже ничего не сделают: вопрос истёк вместе со сроком
                return Answer(shown[0], None)
        finally:
            bus.disconnect()

    async def _notify(self, bus: NotificationsBus, notification: Notification, replaces: int | None, timeout: int) -> int:
        actions = [part for action in notification.actions for part in (action.key, action.label)]
        if notification.reply is not None:
            actions += [INLINE_REPLY, REPLY_BUTTON]
        return await bus.notify(
            self._app_name, replaces or 0, self._icon, notification.title, notification.body, actions, URGENCY[notification.urgency], timeout,
            notification.reply or "", notification.transient,
        )

    @staticmethod
    def _answer(notification_id: int, action: str | None) -> Answer:
        if action is not None and action.startswith(REPLY_PREFIX):
            return Answer(notification_id, Answer.REPLY, action.removeprefix(REPLY_PREFIX))
        return Answer(notification_id, action)

    @staticmethod
    def _timeout(notification: Notification) -> int:
        return BY_SERVER if notification.timeout_ms is None else notification.timeout_ms
