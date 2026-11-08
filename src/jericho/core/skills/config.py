"""Что такое навык для ядра — аналог AppConfig в Django."""

from __future__ import annotations

import inspect
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

from jericho.core.conf.settings import SkillSettings
from jericho.core.management.base import Command
from jericho.core.prompting.protocols import PromptContext
from jericho.core.services.core_services import CoreServices
from jericho.core.tools.tool import Tool

if TYPE_CHECKING:   # проверки знают о навыках, поэтому навык знает о них только по имени типа
    from jericho.core.checks.base import Check


class SkillConfig[SettingsT: SkillSettings = SkillSettings]:
    """Навык: описывает себя и собирает свои объекты. Лежит в `skill.py` папки навыка.

    Наследник объявляет имя и описание и переопределяет то, что у него есть:

        name            как навык называется в списке навыков и в настройках
        description     одна строка для модели: когда этот навык нужен
        settings_class  свой раздел настроек; в `ready()` приходит уже собранным по всем уровням
        requires        протоколы служб, без которых навык не работает; берутся в `ready()` через `core.shared.get(…)`
        ready           собрать свои объекты из настроек и служб ядра
        tools           ручки, которые навык отдаёт модели, — явным списком
        contexts        живые данные для подстановок в SKILL.md
        commands        свои команды терминала
        checks          свои правила для `jericho check`

    Имя и описание — атрибуты класса: чтобы показать список навыков, собирать навык не нужно.
    """

    name: ClassVar[str]
    description: ClassVar[str]
    settings_class: ClassVar[type[SkillSettings]] = SkillSettings
    requires: ClassVar[tuple[type, ...]] = ()

    @property
    def directory(self) -> Path:
        """Папка навыка — та, где лежит его `skill.py`; рядом ядро ищет `SKILL.md`."""
        return Path(inspect.getfile(type(self))).parent

    def ready(self, settings: SettingsT, core: CoreServices) -> None:
        """Вызывается один раз, до `tools`, `contexts` и `commands`."""

    def tools(self) -> Sequence[Tool[Any]]:
        return ()

    def contexts(self) -> Sequence[PromptContext]:
        return ()

    def commands(self) -> Sequence[Command]:
        return ()

    def checks(self) -> Sequence[Check]:
        """Свои правила навыка для `jericho check` — обычно из его `checks.py`."""
        return ()
