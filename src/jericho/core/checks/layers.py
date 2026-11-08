"""Правила слоёв: кто кого может импортировать и кто запускает внешние программы."""

from __future__ import annotations

from jericho.core.checks.base import CORE, PROJECT, SERVICES, CheckMessage, Project, SkillSource, in_tests
from jericho.core.checks.imports import imported_modules, is_within, python_files


class SkillImports:
    """E002: навык импортирует только себя, открытые имена ядра (`from jericho.core import …`) и открытые имена служб.

    Чужой навык, глубина ядра, сборка и настройки проекта навыку недоступны. Общее для двух навыков переезжает
    в службу (`<проект>.services.<имя>`); из неё навык берёт то, что названо в её `__init__.py`, а до адаптера
    не дотягивается. Тестам навыка разрешено больше — подмены из `jericho.core.testing`, части ядра, которые
    они собирают, и подмена службы из её `testing.py`.
    """

    def run(self, project: Project) -> list[CheckMessage]:
        messages: list[CheckMessage] = []
        for skill in project.skill_sources():
            for file in python_files(skill.directory):
                for module in imported_modules(file, skill.package, skill.directory):
                    problem = self._problem(module, skill, in_tests=in_tests(file, skill.directory))
                    if problem:
                        messages.append(CheckMessage("jericho.E002", project.location(file), problem))
        return messages

    @staticmethod
    def _problem(module: str, skill: SkillSource, in_tests: bool) -> str:
        if is_within(module, skill.package) or module == CORE:
            return ""
        if is_within(module, skill.family):
            return f"импорт из другого навыка: `{module}`"
        services = f"{skill.family.rpartition('.')[0]}.{SERVICES}"
        if is_within(module, services):
            inside = module.removeprefix(f"{services}.").split(".")[1:]     # что после имени службы
            if not inside or (in_tests and inside == ["testing"]):
                return ""
            return f"импорт из глубины службы: `{module}` — бери имя из пакета службы"
        if is_within(module, CORE):
            return "" if in_tests else f"импорт из глубины ядра: `{module}` — бери имя из `jericho.core`"
        if is_within(module, PROJECT) or is_within(module, skill.family.rpartition(".")[0]):
            return f"навык не знает о проекте: `{module}`"
        return ""


class CoreImports:
    """E003: ядро не знает ни о модулях и бэкендах каркаса, ни о навыках, сборке и настройках проекта.

    Проект проверяется по имени его пакета: ядро, которое импортирует `home.settings`, тоже нарушение (ревью R12).
    Относительный импорт переводится в полное имя: `from ...backends import x` проходил мимо (ревью 02.11.2026, П1 №6).
    """

    def run(self, project: Project) -> list[CheckMessage]:
        own = project.package_dir.name
        return [
            CheckMessage("jericho.E003", project.location(file), f"ядро импортирует `{module}`")
            for file in python_files(project.core_dir)
            for module in imported_modules(file, CORE, project.core_dir)
            if (is_within(module, PROJECT) and not is_within(module, CORE))
            or (project.framework_dir is not None and own != PROJECT and is_within(module, own))
        ]


class ServiceImports:
    """E009: служба импортирует только себя и открытые имена ядра — о навыках и проекте она не знает.

    Служба — общий слой под навыками: зависимости идут от навыка к службе и никогда обратно.
    Службы ищутся в папке `services` пакета проекта.
    """

    def run(self, project: Project) -> list[CheckMessage]:
        messages: list[CheckMessage] = []
        for directory in project.service_dirs():
            for file in python_files(directory):
                testing = in_tests(file, directory)
                own = f"{project.package_dir.name}.{SERVICES}.{directory.name}"
                for module in imported_modules(file, own, directory):
                    problem = self._problem(module, directory.name, project.package_dir.name, testing)
                    if problem:
                        messages.append(CheckMessage("jericho.E009", project.location(file), problem))
        return messages

    @staticmethod
    def _problem(module: str, name: str, root: str, in_tests: bool) -> str:
        own = f"{root}.{SERVICES}.{name}"
        if module == CORE or is_within(module, own):
            return ""
        if is_within(module, CORE):
            return "" if in_tests else f"импорт из глубины ядра: `{module}` — бери имя из `jericho.core`"
        if is_within(module, PROJECT) or is_within(module, root):
            return f"служба не знает ни о навыках, ни о проекте: `{module}`"
        return ""


class PydanticOnTheEdges:
    """E004: `pydantic` — только на границах. В сущностях, протоколах и сценариях навыка его нет: там обычные `dataclass`.

    Сценарии — `application/` (прежнее имя папки — `services/`, оно тоже внутреннее).
    """

    _INNER = ("entities", "entities.py", "protocols.py", "application", "services", "services.py")

    def run(self, project: Project) -> list[CheckMessage]:
        messages: list[CheckMessage] = []
        for skill in project.skill_sources():
            for file in python_files(skill.directory):
                inner = file.relative_to(skill.directory).parts[0] in self._INNER
                if inner and any(is_within(module, "pydantic") for module in imported_modules(file)):
                    messages.append(CheckMessage("jericho.E004", project.location(file), "`pydantic` во внутреннем слое навыка"))
        return messages


class ProgramsThroughRunner:
    """E005: внешние программы навык запускает через `runner` ядра, а не сам.

    Так у запуска один таймаут, одна запись в журнал и один режим «вхолостую» на все навыки.
    """

    def run(self, project: Project) -> list[CheckMessage]:
        return [
            CheckMessage("jericho.E005", project.location(file), "`subprocess` в навыке — запускай программы через `core.runner`")
            for skill in project.skill_sources()
            for file in python_files(skill.directory)
            if not in_tests(file, skill.directory) and "subprocess" in imported_modules(file)
        ]
