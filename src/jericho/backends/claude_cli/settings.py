"""Настройки бэкенда «программа claude» — раздел `claude_cli`."""

from __future__ import annotations

from pathlib import Path

from jericho.core.conf.settings import SettingsSection
from jericho.core.conf.types import ExpandedPath


class ClaudeSettings(SettingsSection):
    """Проект объявляет раздел у себя, если хочет менять значения: `claude_cli: ClaudeSettings = ClaudeSettings(...)`."""

    # Полный путь к программе задаёт файл машины: у процессов графической среды и таймеров в PATH может не быть ~/.local/bin.
    claude: ExpandedPath = Path("claude")
    model: str = "haiku"                    # быстрая модель для разбора команд
    # Встроенные инструменты claude, разрешённые модели сверх наших ручек. По умолчанию ни одного: всё, что модель
    # может сделать, идёт через ручки Jericho. Проект включает поимённо то, что только читает (`WebSearch`).
    builtin_tools: tuple[str, ...] = ()
