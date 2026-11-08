"""Правила промпта: форма ответа описана, разделы модулей названы под стать подключённым."""

from __future__ import annotations

from jericho.core.agent.forms import REPLY_FORMS
from jericho.core.checks.base import CheckMessage, Project
from jericho.core.conf.resources import ResourceError, package_file


class ReplyFormIsDescribed:
    """E010: общий промпт описывает каждое поле выбранной формы ответа.

    Форму ответа задаёт настройка `agent.reply_form`, а раздел о формате в `PROMPT_SECTIONS` называется отдельно.
    Разойдись они — модель получит схему с одними полями и объяснение про другие.
    """

    def run(self, project: Project) -> list[CheckMessage]:
        if project.settings is None or not project.prompt:
            return []
        name = project.settings.agent.reply_form
        properties = REPLY_FORMS[name]().schema().get("properties", {})
        missing = [field for field in properties if f'"{field}"' not in project.prompt]
        if not missing:
            return []
        text = (
            f"форма ответа `{name}`, а в промпте не описаны её поля: {', '.join(missing)} — "
            "назови в PROMPT_SECTIONS раздел о формате под эту форму"
        )
        return [CheckMessage("jericho.E010", "settings", text)]


class ModuleSectionsAreListed:
    """E011: раздел промпта подключённого модуля назван в `PROMPT_SECTIONS`, а неподключённого — не назван.

    Модуль кладёт свой раздел рядом с собой (`prompt.md`). Забытый раздел — модель не знает, как пользоваться
    ручками модуля; раздел без модуля — модель читает про ручки, которых нет.
    """

    _SECTION = "prompt.md"
    _MODULE = "module.py"

    def run(self, project: Project) -> list[CheckMessage]:
        if project.settings is None:
            return []
        listed = project.settings.PROMPT_SECTIONS
        installed = project.modules.packages
        messages = [
            CheckMessage("jericho.E011", "settings", f"модуль `{package}` подключён, а его раздел не назван: добавь `{package}:{self._SECTION}` в PROMPT_SECTIONS")
            for package, module in zip(installed, project.modules, strict=True)
            if (module.directory / self._SECTION).exists() and f"{package}:{self._SECTION}" not in listed
        ]
        for reference in listed:
            package, _, path = reference.partition(":")
            if path == self._SECTION and package not in installed and self._is_module(reference):
                text = f"раздел `{reference}` назван, а модуль не подключён: добавь `{package}` в INSTALLED_MODULES или убери раздел"
                messages.append(CheckMessage("jericho.E011", "settings", text))
        return messages

    def _is_module(self, reference: str) -> bool:
        try:
            return (package_file(reference, "PROMPT_SECTIONS").parent / self._MODULE).exists()
        except ResourceError:
            return False
