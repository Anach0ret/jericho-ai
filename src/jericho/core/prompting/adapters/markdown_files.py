"""Тексты промпта из файлов: разделы общего промпта и SKILL.md в папке каждого навыка."""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

import yaml

from jericho.core.conf.resources import ResourceError, package_file
from jericho.core.prompting.entities import Skill
from jericho.core.skills.config import SkillConfig


class PromptSectionError(ResourceError):
    """Раздел промпта назван в настройках, но его файла нет."""


def section_file(reference: str) -> Path:
    """Файл раздела по записи из `PROMPT_SECTIONS`: «пакет:путь внутри пакета», например `home.settings:prompt/role.md`.

    Раздел лежит рядом со своим владельцем — в пакете каркаса, модуля или проекта.
    """
    try:
        return package_file(reference, "PROMPT_SECTIONS")
    except ResourceError as error:
        raise PromptSectionError(str(error)) from error


class MarkdownPromptSource:
    """Читает разделы общего промпта и навыки. Карточка-комментарий в начале файла и шапка YAML в промпт не попадают.

    Общий промпт складывается из разделов в том порядке, в каком они названы: порядок — часть текста для модели.
    Имя и описание навыка берутся из его класса, из `SKILL.md` — список ручек в шапке и сам текст.
    """

    _FILE = "SKILL.md"
    _LEADING_COMMENT = re.compile(r"\A\s*<!--.*?-->\s*", re.DOTALL)
    _FRONT_MATTER = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.DOTALL)

    def __init__(self, sections: Sequence[Path], skills: Iterable[SkillConfig[Any]]) -> None:
        self._sections = tuple(sections)
        self._skills = {skill.name: skill for skill in skills}

    def core(self) -> str:
        texts = (self._LEADING_COMMENT.sub("", file.read_text(encoding="utf-8")).strip() for file in self._sections)
        return "\n\n".join(text for text in texts if text)

    def skill(self, name: str) -> Skill:
        config = self._skills[name]
        file = config.directory / self._FILE
        match = self._FRONT_MATTER.match(file.read_text(encoding="utf-8"))
        if match is None:
            raise ValueError(f"{file}: no front matter with tools")
        header = yaml.safe_load(match.group(1))
        return Skill(
            name=config.name,
            description=config.description,
            tools=tuple(str(tool) for tool in header.get("tools", [])),
            body=match.group(2).strip(),
        )
