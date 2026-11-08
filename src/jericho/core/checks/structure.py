"""Правила структуры по умолчанию — то, что проверяет `<проект> check`. Сами правила разложены по предмету.

Новое правило — класс в файле своей темы и строка в этом списке.
"""

from __future__ import annotations

from jericho.core.checks.layers import CoreImports, ProgramsThroughRunner, PydanticOnTheEdges, ServiceImports, SkillImports
from jericho.core.checks.permissions import FilesArePrivate
from jericho.core.checks.prompt import ModuleSectionsAreListed, ReplyFormIsDescribed
from jericho.core.checks.risk import RiskIsDeclared
from jericho.core.checks.services import NoToolsInServices
from jericho.core.checks.skill_files import GuidePlaceholders, RequiredFiles, ToolsAreListed, ToolsAreTested

DEFAULT_CHECKS = (
    RequiredFiles(),
    SkillImports(),
    CoreImports(),
    PydanticOnTheEdges(),
    ProgramsThroughRunner(),
    ToolsAreListed(),
    GuidePlaceholders(),
    RiskIsDeclared(),
    ServiceImports(),
    ReplyFormIsDescribed(),
    ModuleSectionsAreListed(),
    ToolsAreTested(),
    NoToolsInServices(),
    FilesArePrivate(),
)
