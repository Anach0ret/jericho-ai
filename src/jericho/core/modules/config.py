"""Что такое модуль ядра для каркаса.

Модуль — необязательная часть, которая меняет сам путь поручения: откуда оно приходит, что к нему прикладывается,
что помнится между поручениями, куда уходит ответ. Навык добавляет модели действия; модуль встаёт в путь.
Поэтому модулю выдаётся больше, чем навыку: журнал, сеанс вызовов, список навыков — и список модулей короткий.
"""

from __future__ import annotations

import inspect
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

from jericho.core.agent.task import TaskLayer
from jericho.core.conf.settings import Settings
from jericho.core.journal.protocols import JournalReader
from jericho.core.management.base import Command
from jericho.core.prompting.protocols import PromptContext
from jericho.core.services.core_services import CoreServices
from jericho.core.services.paths import Paths
from jericho.core.services.program import Program
from jericho.core.services.relaunch import Relaunch
from jericho.core.skills.registry import InstalledSkills
from jericho.core.tools.catalog import ToolCatalog
from jericho.core.tools.dispatcher import ToolMiddleware
from jericho.core.tools.session import CallSession
from jericho.core.tools.tool import Tool

if TYPE_CHECKING:   # сценарий знает о слоях модулей, поэтому модуль знает о нём только по имени типа
    from jericho.core.agent.handle_phrase import HandlePhrase
    from jericho.core.checks.base import Check  # правила проверяют модули — и модуль знает о них только по имени


@dataclass(frozen=True, slots=True)
class ModuleServices:
    """Всё, что модуль получает от каркаса в `ready()`."""

    settings: Settings
    core: CoreServices           # то же, что получает навык: запуск программ, подтверждение, пути, чужой текст
    journal: JournalReader       # что уже происходило
    session: CallSession         # что произошло в этом поручении: какие навыки загружены
    skills: InstalledSkills      # подключённые навыки и их ручки
    tools: ToolCatalog           # все ручки ассистента; заполняется после сборки, спрашивать — во время вызова
    relaunch: Relaunch           # запустить команду ещё раз без человека рядом: так работают задачи по расписанию
    program: Program             # как запустить ассистента внешнему планировщику: таймеру systemd
    run_id: str = ""             # запуск этого поручения: им помечены его записи в журнале


class ModuleConfig:
    """Модуль ядра: описывает себя и собирает свои объекты. Лежит в `module.py` папки модуля.

    Наследник объявляет имя и переопределяет то, что у него есть:

        name          как модуль называется
        requires      имена модулей, без которых он не работает
        ready         собрать свои объекты из служб каркаса
        tools         ручки модуля: доступны модели сразу, без `load_skill`
        task_layer    слой вокруг поручения; работает, только если модуль назван в `TASK_MIDDLEWARE`
        tool_layers   слои вокруг вызова ручки — уже собранные со своими данными; встают после `TOOL_MIDDLEWARE`, ближе к ручке
        contexts      живые данные для подстановок в его разделе общего промпта
        guide_notes   что дописать в руководство навыка
        commands      свои команды терминала
        checks        свои правила для `<проект> check`: объекты с `run(project) -> list[CheckMessage]`
        status        что модуль показывает в снимке `<проект> status` (окно на панели и другие внешние программы)
        eval_files    свои файлы в названных папках: прогон проверочных фраз стирает их перед каждой фразой

    Раздел общего промпта модуль кладёт рядом с собой (`prompt.md`); проект называет его в `PROMPT_SECTIONS`.
    """

    name: ClassVar[str]
    requires: ClassVar[tuple[str, ...]] = ()

    @property
    def directory(self) -> Path:
        return Path(inspect.getfile(type(self))).parent

    def ready(self, services: ModuleServices) -> None:
        """Вызывается один раз, после сборки навыков и до всего остального."""

    def tools(self) -> Sequence[Tool[Any]]:
        return ()

    def task_layer(self) -> TaskLayer | None:
        return None

    def tool_layers(self) -> Sequence[ToolMiddleware]:
        return ()

    def contexts(self) -> Sequence[PromptContext]:
        return ()

    def guide_notes(self, skill: str) -> str:
        return ""

    def commands(self, handle_phrase: HandlePhrase) -> Sequence[Command]:
        return ()

    def checks(self) -> Sequence[Check]:
        return ()

    def status(self) -> Mapping[str, object]:
        """Часть снимка `status`: только данные, которые можно отдать в JSON. Пусто — модулю нечего показать."""
        return {}

    def eval_files(self, paths: Paths) -> Sequence[Path]:
        """Файлы модуля в **переданных** папках — папках варианта прогона, а не той сборки, в которой модуль живёт.

        Пути из `ready()` здесь не годятся: при обычном запуске это рабочие файлы, и прогон стёр бы их (ревью R01).
        """
        return ()
