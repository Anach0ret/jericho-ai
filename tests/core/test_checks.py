from pathlib import Path

from jericho.core.checks.base import CheckMessage, Project
from jericho.core.checks.layers import CoreImports, ProgramsThroughRunner, PydanticOnTheEdges, ServiceImports, SkillImports
from jericho.core.checks.prompt import ModuleSectionsAreListed, ReplyFormIsDescribed
from jericho.core.checks.risk import RiskIsDeclared
from jericho.core.checks.services import NoToolsInServices
from jericho.core.checks.skill_files import GuidePlaceholders, RequiredFiles, ToolsAreListed, ToolsAreTested
from jericho.core.checks.structure import DEFAULT_CHECKS
from jericho.core.skills.registry import InstalledSkills
from tests.core.sample_skills.messy.skill import MessySkill

HERE = Path(__file__).parent


def project() -> Project:
    return Project(HERE, InstalledSkills([MessySkill()]))


def texts(messages: list[CheckMessage]) -> list[str]:
    return [f"{message.where}: {message.text}" for message in messages]


class TestStructureChecks:
    def test_required_files(self) -> None:
        assert texts(RequiredFiles().run(project())) == ["messy: нет обязательного `tests`"]

    def test_skill_imports_only_itself_and_public_core_names(self) -> None:
        found = texts(SkillImports().run(project()))

        assert found == [
            "sample_skills/messy/services.py: навык не знает о проекте: `jericho.bootstrap`",
            "sample_skills/messy/services.py: импорт из глубины ядра: `jericho.core.tools.tool` — бери имя из `jericho.core`",
            "sample_skills/messy/services.py: импорт из другого навыка: `tests.core.sample_skills.notes.skill`",
        ]

    def test_core_does_not_import_skills_or_the_project(self, tmp_path: Path) -> None:
        (tmp_path / "core" / "tools").mkdir(parents=True)
        (tmp_path / "core" / "tools" / "bad.py").write_text(
            "from jericho.skills.desktop.entities import Window\nimport jericho.bootstrap\nfrom jericho.core import Tool\n", encoding="utf-8"
        )

        found = texts(CoreImports().run(Project(tmp_path, InstalledSkills([]))))

        assert found == [
            "core/tools/bad.py: ядро импортирует `jericho.skills.desktop.entities`",
            "core/tools/bad.py: ядро импортирует `jericho.bootstrap`",
        ]

    def test_relative_imports_out_of_the_core_are_caught_too(self, tmp_path: Path) -> None:
        """Без пакета и папки ядра относительный импорт не переводился в полное имя и проходил (ревью 02.11.2026, П1 №6)."""
        (tmp_path / "core" / "assembly").mkdir(parents=True)
        (tmp_path / "core" / "assembly" / "agent.py").write_text("from ...backends import scripted\nfrom ..tools import tool\n", encoding="utf-8")

        found = texts(CoreImports().run(Project(tmp_path, InstalledSkills([]))))

        assert found == ["core/assembly/agent.py: ядро импортирует `jericho.backends`"]

    def test_pydantic_stays_out_of_entities_ports_and_services(self) -> None:
        assert texts(PydanticOnTheEdges().run(project())) == [
            "sample_skills/messy/application/plan.py: `pydantic` во внутреннем слое навыка",
            "sample_skills/messy/entities.py: `pydantic` во внутреннем слое навыка",
        ]

    def test_skill_runs_programs_through_the_core_runner(self) -> None:
        assert [message.where for message in ProgramsThroughRunner().run(project())] == ["sample_skills/messy/adapters/shell.py"]

    def test_forgotten_tool_and_forgotten_allowlist_are_found(self) -> None:
        assert texts(ToolsAreListed().run(project())) == [
            "messy: ручка `Forgotten` не вписана в `tools()`",
            "messy: белый список `PLAYER` не вписан в `tools()`",
        ]

    def test_placeholder_without_a_source_is_found(self) -> None:
        assert texts(GuidePlaceholders().run(project())) == [
            "messy: в `SKILL.md` подстановка `{{folder}}`, а источника нет"
        ]

    def test_tool_without_a_declared_risk_is_found(self) -> None:
        assert texts(RiskIsDeclared().run(project())) == [
            "messy: ручка `listed` не объявила класс риска: добавь `risk = Risk.…` в её класс"
        ]

    def test_service_that_reaches_for_a_skill_or_the_project_is_found(self, tmp_path: Path) -> None:
        service = tmp_path / "home" / "services" / "windows"
        service.mkdir(parents=True)
        (service / "service.py").write_text(
            "from jericho.core import ServiceConfig\nfrom home.services.windows.entities import Window\n"
            "from home.skills.desktop.entities import Editor\nfrom jericho.core.tools.tool import Tool\n"
            "from jericho.modules.notes.notebook import Notebook\n", encoding="utf-8"
        )

        found = texts(ServiceImports().run(Project(tmp_path / "home", InstalledSkills([]))))

        assert found == [
            "services/windows/service.py: служба не знает ни о навыках, ни о проекте: `home.skills.desktop.entities`",
            "services/windows/service.py: импорт из глубины ядра: `jericho.core.tools.tool` — бери имя из `jericho.core`",
            "services/windows/service.py: служба не знает ни о навыках, ни о проекте: `jericho.modules.notes.notebook`",
        ]

    def test_skill_takes_from_a_service_only_what_its_package_names(self) -> None:
        from jericho.core.checks.base import SkillSource

        skill = SkillSource("browser", "home.skills.browser", Path("/nowhere"))
        problem = SkillImports._problem  # pyright: ignore[reportPrivateUsage]

        assert problem("home.services.windows", skill, in_tests=False) == ""
        assert problem("home.services.windows.testing", skill, in_tests=True) == ""
        assert "из глубины службы" in problem("home.services.windows.adapters.hyprland", skill, in_tests=False)
        assert "из глубины службы" in problem("home.services.windows.testing", skill, in_tests=False)
        assert "не знает о проекте" in problem("home.settings", skill, in_tests=False)

    def test_core_of_the_framework_itself_is_clean(self) -> None:
        """Каркас проверяет сам себя: ни модулей, ни бэкендов, ни проекта ядро не импортирует."""
        import jericho

        assert CoreImports().run(Project(Path(jericho.__file__).parent, InstalledSkills([]))) == []

    def test_reply_form_must_be_described_in_the_prompt(self) -> None:
        """Форма и раздел о формате называются в настройках отдельно — и могут разойтись."""
        from jericho.core.conf.settings import AgentSettings, Settings

        class Reporting(Settings):
            agent: AgentSettings = AgentSettings(reply_form="report")

        brief = 'Ответ: {"status": "…", "message": "…"}; у вопроса — "options"'
        report = 'Ответ: {"status": "…", "title": "…", "text": "…"}; у вопроса — "options"'

        def findings(settings: Settings, prompt: str) -> list[str]:
            project = Project(HERE, InstalledSkills([]), settings=settings, prompt=prompt)
            return [message.text for message in ReplyFormIsDescribed().run(project)]

        assert findings(Settings(), brief) == [] and findings(Reporting(), report) == []
        assert "не описаны её поля: title, text" in findings(Reporting(), brief)[0]
        assert findings(Reporting(), "") == []      # промпт не передан — проверять нечего

    def test_section_of_a_module_follows_the_module(self) -> None:
        from jericho.core.conf.settings import Settings
        from jericho.core.modules.loader import ModuleLoader

        class Forgot(Settings):
            INSTALLED_MODULES: tuple[str, ...] = ("jericho.modules.journal_reader",)

        class Orphan(Settings):
            PROMPT_SECTIONS: tuple[str, ...] = ("jericho.modules.dialogue:prompt.md",)

        def findings(settings: Settings) -> list[str]:
            modules = ModuleLoader().load(settings.INSTALLED_MODULES)
            project = Project(HERE, InstalledSkills([]), modules=modules, settings=settings)
            return [message.text for message in ModuleSectionsAreListed().run(project)]

        assert "добавь `jericho.modules.journal_reader:prompt.md` в PROMPT_SECTIONS" in findings(Forgot())[0]
        assert "раздел `jericho.modules.dialogue:prompt.md` назван, а модуль не подключён" in findings(Orphan())[0]
        assert findings(Settings()) == []

    def test_tool_of_a_module_must_declare_its_risk_too(self) -> None:
        from jericho.core.modules.config import ModuleConfig
        from jericho.core.modules.registry import InstalledModules
        from tests.core.sample_skills.messy.tools.listed import Listed

        class Careless(ModuleConfig):
            name = "careless"

            def tools(self) -> list[Listed]:
                return [Listed()]

        project = Project(HERE, InstalledSkills([]), modules=InstalledModules([("pkg.careless", Careless())]))

        assert texts(RiskIsDeclared().run(project)) == [
            "модуль careless: ручка `listed` не объявила класс риска: добавь `risk = Risk.…` в её класс"
        ]

    def test_effect_tool_must_say_who_asks_for_consent(self) -> None:
        from jericho.core import Risk
        from jericho.core.modules.config import ModuleConfig
        from jericho.core.modules.registry import InstalledModules
        from tests.core.sample_skills.messy.tools.listed import Listed

        class Sender(Listed):
            name = "sender"
            risk = Risk.EFFECT

        class Careless(ModuleConfig):
            name = "careless"

            def tools(self) -> list[Listed]:
                return [Sender()]

        project = Project(HERE, InstalledSkills([]), modules=InstalledModules([("pkg.careless", Careless())]))

        assert "ручка `sender` — EFFECT, но не сказала, кто спрашивает «да»" in texts(RiskIsDeclared().run(project))[0]

    def test_tool_without_a_test_is_found(self) -> None:
        assert any("ручку `listed` не проверяет ни один тест" in text for text in texts(ToolsAreTested().run(project())))

    def test_tool_inside_a_service_is_found(self, tmp_path: Path) -> None:
        service = tmp_path / "home" / "services" / "mail"
        service.mkdir(parents=True)
        (service / "service.py").write_text("class Send(Tool[Request]):\n    pass\nrules = Allowlist('x')\n", encoding="utf-8")

        found = texts(NoToolsInServices().run(Project(tmp_path / "home", InstalledSkills([]))))

        assert [text.split(": ")[1] for text in found] == ["в службе ручка `Send`", "в службе ручка `Allowlist`"]

    def test_relative_import_from_another_skill_is_found(self, tmp_path: Path) -> None:
        """Ревью R12: `from ..other import x` раньше не проверялся вовсе."""
        from jericho.core.checks.imports import imported_modules

        skill = tmp_path / "skills" / "mail"
        (skill / "tools").mkdir(parents=True)
        (skill / "tools" / "send.py").write_text("from ...diary import notes\nfrom ..adapters import smtp\nfrom . import helpers\n", encoding="utf-8")

        modules = imported_modules(skill / "tools" / "send.py", "home.skills.mail", skill)

        assert modules == ["home.skills.diary", "home.skills.mail.adapters", "home.skills.mail.tools.helpers"]

    def test_core_importing_the_project_is_found(self, tmp_path: Path) -> None:
        """Ревью R12: E003 смотрел только на `jericho.*` и не видел импорт ядром `home.settings`."""
        core = tmp_path / "framework" / "core"
        core.mkdir(parents=True)
        (core / "leak.py").write_text("from home.settings import Base\n", encoding="utf-8")
        project = Project(tmp_path / "home", InstalledSkills([]), framework_dir=core)

        assert [message.text for message in CoreImports().run(project)] == ["ядро импортирует `home.settings`"]

    def test_tool_named_only_in_a_comment_is_not_tested(self, tmp_path: Path) -> None:
        from jericho.core.checks.skill_files import ToolsAreTested

        tests = tmp_path / "tests"
        tests.mkdir()
        (tests / "test_x.py").write_text("from pkg.tools import Listed  # Listed проверим потом\n", encoding="utf-8")

        assert ToolsAreTested._used_names(tests) == set()  # pyright: ignore[reportPrivateUsage]

    def test_every_finding_carries_its_rule_code(self) -> None:
        messages = [message for check in DEFAULT_CHECKS for message in check.run(project())]

        assert {message.code for message in messages} == {f"jericho.E0{number:02}" for number in (1, 2, 4, 5, 6, 7, 8, 12)}
