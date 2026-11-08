"""Примеры кода в README и docs переносятся в проект как есть — и работают (ревью 02.11.2026, П5 №3, №6).

Строку `agent = AgentSettings(...)` без аннотации Pydantic не принимает: перенесённый пример ломал импорт настроек.
EFFECT-ручка без `approval` не проходит `check` (E008).
"""

import re
from pathlib import Path

import pytest

from jericho.core import AgentSettings, Settings

ROOT = Path(__file__).parents[2]
DOCUMENTS = sorted([*ROOT.glob("README*.md"), *(ROOT / "docs").glob("*.md")])
BLOCK = re.compile(r"^```python\n(.*?)^```", re.DOTALL | re.MULTILINE)
# Поле настроек без аннотации: `agent = AgentSettings(…)`, `INSTALLED_MODULES = (…)`.
BARE_FIELD = re.compile(r"^\s*(?:[a-z_]+ = [A-Z]\w*Settings\(|[A-Z][A-Z_]{2,} = \()", re.MULTILINE)   # с пробелами: не `x=…` аргумента


def blocks() -> list[tuple[str, str]]:
    return [(path.relative_to(ROOT).as_posix(), block) for path in DOCUMENTS for block in BLOCK.findall(path.read_text(encoding="utf-8"))]


def named(examples: list[tuple[str, str]]) -> list[object]:
    """Имя теста — документ и номер примера в нём, а не весь код."""
    return [pytest.param(document, code, id=f"{document}#{number}") for number, (document, code) in enumerate(examples, start=1)]


@pytest.mark.parametrize(("document", "code"), named(blocks()))
def test_settings_fields_are_annotated(document: str, code: str) -> None:
    bare = [line.strip() for line in BARE_FIELD.findall(code)]

    assert bare == [], f"{document}: поле настроек без аннотации — Pydantic его не примет"


@pytest.mark.parametrize(("document", "code"), named([(name, code) for name, code in blocks() if "Risk.EFFECT" in code and "(Tool[" in code]))
def test_effect_tools_say_who_asks_yes(document: str, code: str) -> None:
    assert "approval = Approval." in code, f"{document}: EFFECT-ручка без approval не пройдёт check (E008)"


@pytest.mark.parametrize(
    ("document", "code"), named([(name, code) for name, code in blocks() if "class Base(Settings)" in code and "..." not in code])
)
def test_whole_settings_examples_build(document: str, code: str) -> None:
    """Целый класс настроек из примера собирается — с настоящими `Settings` и разделами бэкендов."""
    namespace: dict[str, object] = {"Settings": Settings, "AgentSettings": AgentSettings}
    exec(compile(code, document, "exec"), namespace)

    settings = namespace["Base"]
    assert isinstance(settings, type) and issubclass(settings, Settings)
    settings()
