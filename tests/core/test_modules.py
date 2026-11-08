import pytest

from jericho.core.agent.task import Outcome, Task, TaskHandler
from jericho.core.modules.config import ModuleConfig
from jericho.core.modules.loader import ModuleLoader
from jericho.core.modules.registry import InstalledModules, ModuleError
from jericho.core.tools.dispatcher import CallHandler, ToolMiddleware


class Layer:
    def __init__(self, owner: str = "") -> None:
        self.owner = owner      # чей слой: по нему видно порядок

    def handle(self, task: Task, proceed: TaskHandler) -> Outcome:
        return proceed(task)


class Memory(ModuleConfig):
    name = "memory"

    def task_layer(self) -> Layer:
        return Layer("memory")

    def guide_notes(self, skill: str) -> str:
        return f"помню о {skill}"


class Echo(ModuleConfig):
    name = "echo"
    requires = ("memory",)

    def task_layer(self) -> Layer:
        return Layer("echo")


class Quiet(ModuleConfig):
    name = "quiet"


def installed(*modules: ModuleConfig) -> InstalledModules:
    return InstalledModules([(f"pkg.{module.name}", module) for module in modules])


class TestInstalledModules:
    def test_layers_come_in_the_order_the_settings_name_not_in_the_order_of_modules(self) -> None:
        memory, echo = Memory(), Echo()
        modules = installed(memory, echo)

        layers = modules.layers(["pkg.echo", "pkg.memory"])

        assert [layer.owner for layer in layers if isinstance(layer, Layer)] == ["echo", "memory"]     # П4: [Layer, Layer] не видел порядка

    @pytest.mark.parametrize(("order", "problem"), [
        (["pkg.memory"], "pkg.echo: has a task layer — add it to TASK_MIDDLEWARE"),       # слой забыт в списке
        (["pkg.memory", "pkg.echo", "pkg.other"], "names pkg.other — not in INSTALLED_MODULES"),
    ])
    def test_layer_that_would_silently_not_run_is_an_error(self, order: list[str], problem: str) -> None:
        with pytest.raises(ModuleError, match=problem):
            installed(Memory(), Echo()).layers(order)

    def test_module_without_a_layer_cannot_be_named_among_the_layers(self) -> None:
        with pytest.raises(ModuleError, match="pkg.quiet — the module has no task layer"):
            installed(Quiet()).layers(["pkg.quiet"])

    def test_module_that_needs_another_says_which_one_to_install(self) -> None:
        with pytest.raises(ModuleError, match="pkg.echo: requires module memory — add it to INSTALLED_MODULES"):
            installed(Echo())

    def test_what_modules_know_about_a_skill_goes_into_its_guide(self) -> None:
        assert installed(Memory(), Quiet()).guide_notes("browser") == "помню о browser"

    def test_tool_layers_of_modules_are_collected_in_module_order(self) -> None:
        """Слой вокруг вызова ручки модуль собирает сам — со своими данными: имени в TOOL_MIDDLEWARE ему мало."""
        def first(handle: CallHandler) -> CallHandler:
            return handle

        def second(handle: CallHandler) -> CallHandler:
            return handle

        class Hinting(ModuleConfig):
            name = "hinting"

            def tool_layers(self) -> tuple[ToolMiddleware, ...]:
                return (first, second)

        assert installed(Memory(), Hinting()).tool_layers() == (first, second)

    def test_no_modules_is_a_whole_assistant_too(self) -> None:
        nothing = installed()

        assert (nothing.tools(), nothing.layers([]), nothing.contexts(), nothing.guide_notes("browser")) == ((), (), (), "")


class TestModuleLoader:
    def test_module_is_found_by_its_package(self) -> None:
        assert ModuleLoader().load(["jericho.modules.journal_reader", "jericho.modules.notes"]).names == ("journal_reader", "notes")

    def test_module_shipped_with_the_framework_names_what_it_cannot_work_without(self) -> None:
        with pytest.raises(ModuleError, match="jericho.modules.notes: requires module journal_reader"):
            ModuleLoader().load(["jericho.modules.notes"])

    def test_tools_of_shipped_modules_declare_their_own_risk(self) -> None:
        from jericho.modules.journal_reader.tool import ReadJournal
        from jericho.modules.notes.tools import Forget, Remember

        assert all("risk" in vars(tool) for tool in (ReadJournal, Remember, Forget))

    @pytest.mark.parametrize(("package", "problem"), [
        ("jericho.modules.nothing", "jericho.modules.nothing.module: module not found"),
        ("jericho.core.tools", "jericho.core.tools.module: module not found"),
    ])
    def test_package_without_a_module_is_named(self, package: str, problem: str) -> None:
        with pytest.raises(ModuleError, match=problem):
            ModuleLoader().load([package])
