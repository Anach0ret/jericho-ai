"""Подмены ядра для тестов — ими пользуются и тесты ядра, и тесты навыков и модулей.

Здесь же — то, чем тест проекта проверяет навык так же, как `<проект> check`: `Project`, `InstalledSkills`,
`DEFAULT_CHECKS`, и службы ядра для сборки навыка в тесте — `fake_core`. Это публичные имена (docs/stability.md); их внутренние модули можно перекладывать.
"""

from jericho.core.checks.base import Project
from jericho.core.checks.structure import DEFAULT_CHECKS
from jericho.core.skills.registry import InstalledSkills
from jericho.core.testing.fakes import NOON, Confirmations, FakeBackend, Source, builder, execute, fake_core, say_yes

__all__ = ["DEFAULT_CHECKS", "NOON", "Confirmations", "FakeBackend", "InstalledSkills", "Project", "Source", "builder", "execute", "fake_core", "say_yes"]
