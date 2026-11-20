"""Запуск фоновой работы из ручки: своя команда ассистента отдельным процессом, с id работы."""

from __future__ import annotations

from dataclasses import dataclass

from jericho.core.jobs.desk import ContinuationDesk
from jericho.core.jobs.entities import new_job_id
from jericho.core.services.program import Program
from jericho.core.services.runner import CommandError, CommandRunner
from jericho.core.tools.result import ToolRefusal


@dataclass(frozen=True, slots=True)
class JobStart:
    """Запущенная работа: её id и id продолжения (`then`), если оно записано."""

    job: str
    continuation: str = ""

    def fields(self) -> dict[str, str]:
        """Поля ответа ручки: `job`, а с продолжением — и `then` с его id (текст поручения в ответ не идёт)."""
        return {"job": self.job, **({"then": self.continuation} if self.continuation else {})}


class JobLauncher:
    """Ручка не ждёт работу: запускает `<проект> <команда> … --job ID` и отдаёт модели id — по нему итог найдётся
    в журнале (`job_finished`) и в строке `{{jobs}}`. Запуск — свой (`Program.detached`), не продолжение фразы."""

    NOT_STARTED = "not_started"
    NO_THEN = "then_unavailable"

    def __init__(self, runner: CommandRunner, program: Program, desk: ContinuationDesk | None = None) -> None:
        self._runner = runner
        self._program = program
        self._desk = desk           # нет — `then` этому ассистенту недоступно

    def start(self, command: str, *arguments: str, then: str = "") -> JobStart:
        """Запустить работу; `then` — что сделать после неё. Не запустилась — отказ `not_started` с причиной."""
        job = new_job_id()
        continuation = self._continuation(then, job)
        after = ("--continuation", continuation) if continuation else ()
        try:
            self._runner.launch(self._program.detached(command, *arguments, "--job", job, *after))
        except CommandError as error:
            raise ToolRefusal(self.NOT_STARTED, detail=str(error)) from error
        return JobStart(job, continuation if then else "")     # звено без текста модели не показывается: then не просили

    def _continuation(self, then: str, job: str) -> str:
        """Есть `then` — его запись; нет — звено цепочки, если работу запускает продолжение (`ContinuationDesk.link`)."""
        if self._desk is None:
            if then:
                raise ToolRefusal(self.NO_THEN, detail="продолжения здесь не включены: сделай работу без then, второй шаг — отдельной просьбой")
            return ""
        return self._desk.register(then, job) if then else self._desk.link(job)
