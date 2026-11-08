"""Уведомления через `notify-send` — стандарт freedesktop, их показывает панель (Noctalia)."""

from __future__ import annotations

import logging
from pathlib import Path

from jericho.core.services.notifications import Notification
from jericho.core.services.runner import CommandError, CommandRunner

logger = logging.getLogger(__name__)


class NotifySendNotifier:
    """Показывает уведомление и возвращает его номер, чтобы следующее могло встать на его место."""

    def __init__(
        self, runner: CommandRunner, executable: Path = Path("/usr/bin/notify-send"), app_name: str = "Jericho", icon: str = ""
    ) -> None:
        self._runner = runner
        self._executable = str(executable)
        self._app_name = app_name
        self._icon = icon      # имя из темы значков («jericho») или путь к файлу; пусто — значок решает панель

    def show(self, notification: Notification, replaces: int | None = None) -> int | None:
        command = [self._executable, "--app-name", self._app_name, "--urgency", notification.urgency.value, "--print-id"]
        if self._icon:
            command += ["--icon", self._icon]
        if notification.transient:
            command += ["--transient"]         # не хранить в истории: в тексте может быть личная переписка
        if replaces is not None:
            command += ["--replace-id", str(replaces)]
        if notification.timeout_ms is not None:
            command += ["--expire-time", str(notification.timeout_ms)]
        command += ["--", notification.title, notification.body]   # после «--» текст не примут за флаг
        try:
            return int(self._runner.run(command))
        except (CommandError, ValueError) as error:
            logger.warning("notify_failed", extra={"data": {"error": str(error), "title": notification.title}})
            return None
