from pathlib import Path
from typing import Protocol

import pytest

from jericho.core import ConfirmationGate, CoreServices, Paths, ServiceError, SharedServices, SkillConfig
from jericho.core.conf.settings import Settings
from jericho.core.shared.config import ServiceLoader
from jericho.core.skills.registry import InstalledSkills
from jericho.core.testing import Confirmations


class Clipboard(Protocol):
    def text(self) -> str: ...


class Memory:
    def text(self) -> str:
        return "скопировано"


class Paste(SkillConfig):
    name = "paste"
    description = "Вставить скопированное."
    requires = (Clipboard,)


def core(shared: SharedServices) -> CoreServices:
    gate = ConfirmationGate(Confirmations(), "run-1")
    return CoreServices(None, gate, Paths(Path("/state"), Path("/run")), shared=shared)  # pyright: ignore[reportArgumentType]


class TestSharedServices:
    def test_skill_gets_a_service_by_its_protocol_not_by_its_class(self) -> None:
        shared = SharedServices()
        shared.provide(Clipboard, Memory(), "clipboard")

        assert shared.get(Clipboard).text() == "скопировано"

    def test_asking_for_a_service_nobody_provides_says_what_to_add(self) -> None:
        with pytest.raises(ServiceError, match="no service provides Clipboard — add its package to INSTALLED_SERVICES"):
            SharedServices().get(Clipboard)

    def test_two_services_cannot_provide_the_same_thing(self) -> None:
        shared = SharedServices()
        shared.provide(Clipboard, Memory(), "clipboard")

        with pytest.raises(ServiceError, match="other: Clipboard is already provided"):
            shared.provide(Clipboard, Memory(), "other")

    def test_skill_whose_service_is_not_installed_is_not_assembled(self) -> None:
        with pytest.raises(ServiceError, match="skill paste: requires service Clipboard"):
            InstalledSkills([Paste()]).ready(Settings(), core(SharedServices()))

    def test_skill_with_its_service_is_assembled(self) -> None:
        shared = SharedServices()
        shared.provide(Clipboard, Memory(), "clipboard")

        InstalledSkills([Paste()]).ready(Settings(), core(shared))


class TestServiceLoader:
    def test_service_is_found_by_its_package(self) -> None:
        assert [service.name for service in ServiceLoader().load(["tests.core.sample_services.clipboard"])] == ["clipboard"]

    def test_package_without_a_service_is_named(self) -> None:
        with pytest.raises(ServiceError, match="tests.core.sample_services.nothing.service: module not found"):
            ServiceLoader().load(["tests.core.sample_services.nothing"])
