"""Участок «навыки»: подключить названные в настройках, дать им собраться и взять их тексты для модели."""

from __future__ import annotations

from dataclasses import dataclass

from jericho.core.assembly.state import State
from jericho.core.conf.settings import Settings
from jericho.core.modules.registry import InstalledModules
from jericho.core.prompting.adapters.markdown_files import MarkdownPromptSource, section_file
from jericho.core.prompting.protocols import PromptSource
from jericho.core.shared.config import ServiceLoader, provide_all
from jericho.core.skills.guide import SkillGuides
from jericho.core.skills.loader import SkillLoader, SkillLoadError
from jericho.core.skills.registry import InstalledSkills


@dataclass(frozen=True, slots=True)
class SkillSet:
    installed: InstalledSkills
    source: PromptSource        # тексты ядра и навыков
    guides: SkillGuides         # руководство навыка — то, что модель получает по load_skill


def preload_skills(installed: InstalledSkills, names: tuple[str, ...], state: State) -> None:
    """Навыки с руководством в общем промпте: загружены с начала фразы, их ручки модель видит целиком."""
    unknown = [name for name in names if name not in installed.names]
    if unknown:
        raise SkillLoadError(f"PRELOADED_SKILLS: {', '.join(unknown)} — not in INSTALLED_SKILLS (use skill names, not packages)")
    for name in names:
        state.session.load(name)
        for tool in installed.tools_of(name):
            tool.in_prompt = True


def build_skills(settings: Settings, state: State, modules: InstalledModules) -> SkillSet:
    # Службы собираются раньше навыков: навык берёт их в `ready()`.
    provide_all(ServiceLoader().load(settings.INSTALLED_SERVICES), settings, state.services, state.services.shared)
    installed = SkillLoader().load(settings.INSTALLED_SKILLS)
    installed.ready(settings, state.services)
    preload_skills(installed, settings.PRELOADED_SKILLS, state)
    source = MarkdownPromptSource([section_file(reference) for reference in settings.PROMPT_SECTIONS], installed)
    return SkillSet(installed, source, SkillGuides(source, installed, modules.guide_notes))
