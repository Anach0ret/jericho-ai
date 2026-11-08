"""Настройки бэкенда «программа codex» — раздел `codex_cli`."""

from __future__ import annotations

from pathlib import Path

from jericho.core.conf.settings import SettingsSection
from jericho.core.conf.types import ExpandedPath


class CodexSettings(SettingsSection):
    """Проект объявляет раздел у себя, если хочет менять значения: `codex_cli: CodexSettings = CodexSettings(...)`."""

    # Полный путь к программе задаёт файл машины: у процессов графической среды и таймеров в PATH может не быть ~/.local/bin.
    codex: ExpandedPath = Path("codex")
    model: str = "gpt-6.1-sol"
    reasoning_effort: str = "low"            # разбор команд: быстрее и дешевле по лимиту подписки; сложное — "medium"
    # Встроенные возможности codex, которые действуют мимо ручек Jericho: оболочка, браузер, управление компьютером,
    # подагенты, плагины. Выключаются поимённо — общего «только наши инструменты», как у `claude --tools ""`, у codex нет.
    # Что осталось (выполнение кода `exec`, `apply_patch`), держит песочница: `exec` видит только ручки (без файлов и
    # сети), запись запрещена (`read-only`, одобрений нет). Проверено пробами 02.11.2026 на codex-cli 0.166.
    disabled_features: tuple[str, ...] = (
        "shell_tool", "unified_exec", "view_image", "image_generation", "multi_agent", "plugins", "apps",
        "browser_use", "computer_use", "in_app_browser", "sleep_tool", "tool_suggest", "skill_search", "goals",
    )
