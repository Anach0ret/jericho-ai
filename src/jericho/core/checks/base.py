"""Что такое проверка и что она сообщает."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from jericho.core.conf.settings import Settings
from jericho.core.modules.registry import InstalledModules
from jericho.core.skills.registry import InstalledSkills

PROJECT = "jericho"           # пакет каркаса
CORE = "jericho.core"         # ядро: навыкам и службам — только его открытые имена
TESTS = "tests"
SERVICES = "services"         # папка служб в пакете проекта


def in_tests(file: Path, root: Path) -> bool:
    """Файл из тестов: им разрешено больше, чем коду навыка или службы."""
    return TESTS in file.relative_to(root).parts


@dataclass(frozen=True, slots=True)
class CheckMessage:
    """Одна находка: что не так, где и по какому правилу."""

    code: str         # «jericho.E003» — по нему правило ищется в docs/checks.md
    where: str        # файл или навык
    text: str


@dataclass(frozen=True, slots=True)
class SkillSource:
    """Где лежит код навыка."""

    name: str
    package: str          # «home.skills.desktop»
    directory: Path

    @property
    def family(self) -> str:
        """Пакет, в котором навыки лежат рядом: его остальные части — чужие навыки."""
        return self.package.rpartition(".")[0]


@dataclass(frozen=True, slots=True)
class Project:
    """То, что проверяется: код пакета на диске и уже собранные навыки."""

    package_dir: Path             # папка пакета проекта: от неё пишутся пути в сообщениях
    skills: InstalledSkills
    framework_dir: Path | None = None    # папка ядра каркаса; не названа — ядро лежит в пакете проекта
    modules: InstalledModules = field(default_factory=InstalledModules)     # подключённые модули ядра
    settings: Settings | None = None     # настройки проекта; без них проверки настроек пропускаются
    prompt: str = ""                     # общий промпт как текст, до подстановок
    private_dirs: tuple[Path, ...] = ()  # папки ассистента с ключами, журналом и сессиями: файлы машины, состояние, сеанс

    @property
    def core_dir(self) -> Path:
        return self.framework_dir or self.package_dir / "core"

    def skill_sources(self) -> list[SkillSource]:
        return [
            SkillSource(skill.name, type(skill).__module__.rpartition(".")[0], skill.directory) for skill in self.skills
        ]

    def service_dirs(self) -> list[Path]:
        """Папки служб проекта: в `services/` — те, где лежит `service.py`."""
        root = self.package_dir / SERVICES
        if not root.is_dir():
            return []
        return sorted(path for path in root.iterdir() if (path / "service.py").exists())

    def location(self, file: Path) -> str:
        """Путь для сообщения: от папки пакета, если файл в ней, иначе как есть. С «/» на любой ОС: сообщение одно и то
        же для человека и модели, и Windows такой путь понимает."""
        return file.relative_to(self.package_dir).as_posix() if file.is_relative_to(self.package_dir) else file.as_posix()


class Check(Protocol):
    """Одно правило. Новое правило — новый класс и строка в списке проверок."""

    def run(self, project: Project) -> list[CheckMessage]: ...
