from pathlib import Path

from pydantic import Field

from jericho.backends.claude_cli.settings import ClaudeSettings
from jericho.core.conf.settings import AgentSettings, Settings, SkillSettings
from jericho.core.conf.types import CommandLine
from jericho.modules.tasks.settings import DeferredSettings, ScheduledTask, TasksSettings


class NotesSettings(SkillSettings):
    folder: Path = Path("~/notes")
    editor: CommandLine = ("nano",)
    tags: dict[str, str] = Field(default_factory=dict)


class Base(Settings):
    INSTALLED_SKILLS: tuple[str, ...] = ("tests.core.sample_skills.notes",)
    agent: AgentSettings = AgentSettings(backend="jericho.backends.claude_cli")
    claude_cli: ClaudeSettings = ClaudeSettings(model="sonnet")
    notes: NotesSettings = NotesSettings(tags={"work": "работа"})


class Live(Base):
    pass


class Quiet(Base):
    agent: AgentSettings = AgentSettings(backend="jericho.backends.claude_cli", timeout=10)
    claude_cli: ClaudeSettings = ClaudeSettings(model="haiku")
    tool_timeout: float = 5.0      # короткой фразе — короткий срок ручки: он обязан быть меньше срока фразы


class Rehearsal(Base):
    """Вхолостую со своей папкой состояния."""

    dry_run: bool = True
    state_name: str = "jericho-rehearsal"


class SharedRehearsal(Base):
    """Вхолостую, но папку состояния себе не завёл — такой вариант собраться не должен."""

    dry_run: bool = True


class WithMemory(Base):
    """Тот же проект с модулями ядра: диалог, чтение журнала, заметки и задачи."""

    INSTALLED_MODULES: tuple[str, ...] = (
        "jericho.modules.dialogue", "jericho.modules.journal_reader", "jericho.modules.notes", "jericho.modules.tasks",
    )
    TASK_MIDDLEWARE: tuple[str, ...] = ("jericho.modules.dialogue", "jericho.modules.notes")
    tasks: TasksSettings = TasksSettings(
        items={"morning": ScheduledTask(text="что в заметках на сегодня")}, deferred=DeferredSettings(enabled=True)
    )


class WithCodexFallback(Base):
    """Два бэкенда через программу модели: оба приносят сервер ручек `mcp`, команда должна быть одна."""

    agent: AgentSettings = AgentSettings(backend="jericho.backends.claude_cli", fallback_backends=("jericho.backends.codex_cli",))
