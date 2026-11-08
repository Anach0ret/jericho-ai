"""Публичное каркаса записано в docs/stability.md — и совпадает с кодом: имя не появится и не пропадёт молча."""

import re
from pathlib import Path

import jericho.core
import jericho.core.testing
from jericho.core import Settings

STABILITY = Path(__file__).parents[2] / "docs" / "stability.md"


def section(title: str) -> str:
    """Текст раздела `### <title>` до следующего заголовка."""
    text = STABILITY.read_text(encoding="utf-8")
    start = text.index(f"### {title}")
    end = text.find("\n#", start + 1)
    return text[start:end if end != -1 else None]


def names(text: str) -> set[str]:
    return set(re.findall(r"`([A-Za-z_][A-Za-z0-9_]*)`", text))


class TestPublicApi:
    def test_core_names_are_exactly_those_in_the_document(self) -> None:
        assert names(section("Имена `jericho.core`")) - {"jericho"} == set(jericho.core.__all__)

    def test_testing_names_are_exactly_those_in_the_document(self) -> None:
        documented = names(section("Имена `jericho.core.testing`").split("\n", 2)[2]) - {"check"}
        assert documented == set(jericho.core.testing.__all__)

    def test_documented_settings_fields_exist(self) -> None:
        fields = names(section("Настройки").split("- Имена модулей")[0])
        assert fields - {"Settings"} <= set(Settings.model_fields)

    def test_check_codes_in_the_document_are_all_described(self) -> None:
        checks = (STABILITY.parent / "checks.md").read_text(encoding="utf-8")
        last = max(int(number) for number in re.findall(r"jericho\.E(\d{3})", section("Командная строка, проверки, обмен")))
        described = {int(number) for number in re.findall(r"`jericho\.E(\d{3})`", checks)}
        assert described == set(range(1, last + 1))


def test_core_services_keep_their_positional_order() -> None:
    """Ревью 07.11.2026, №3: `own_paths` встал перед `user`, и прежний позиционный вызов молча терял пользователя."""
    from jericho.core.services.core_services import CoreServices
    from jericho.core.services.paths import Paths

    services = CoreServices(None, None, Paths(Path("/s"), Path("/r")), False, None, None, None, None, "alice")  # pyright: ignore[reportArgumentType]

    assert services.user == "alice"
