"""Ручка `job_continue`: выполнить продолжение, которое не пошло само (прошёл срок, ассистент был занят)."""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import Field

from jericho.core.jobs.book import ContinuationBook
from jericho.core.services.program import Program
from jericho.core.services.runner import CommandError, CommandRunner
from jericho.core.tools.description import ToolDescription
from jericho.core.tools.request import ToolRequest
from jericho.core.tools.result import ToolRefusal, ToolResult
from jericho.core.tools.risk import Approval, Risk
from jericho.core.tools.tool import Tool


class ContinueJobRequest(ToolRequest):
    continuation: str = Field(pattern=r"^[0-9a-f]{12}$", description="id продолжения — из уведомления или раздела «Фоновые работы».")


class ContinueJob(Tool[ContinueJobRequest]):
    """После «да» запускает `<проект> jobs --continue ID`: фраза продолжения идёт с контекстом исходной фразы.

    «Да» спрашивает каркас (EFFECT): продолжение — давняя просьба, а id мог подсказать чужой текст. Это «да» не
    заменяет согласия на действия внутри: они спрашивают сами (план 110 §2.4). Цепочку и контекст берёт код из записи.
    """

    name = "job_continue"
    risk = Risk.EFFECT
    approval = Approval.ASK      # «да» спрашивает каркас перед вызовом — с текстом продолжения (`consent_summary`)
    request_type = ContinueJobRequest
    description = ToolDescription(
        when="пользователь согласен выполнить отложенное продолжение фоновой работы: «да, выполни продолжение», «давай отправь».",
        does="после «да» запускает в фоне отложенное продолжение; итог придёт уведомлением.",
        returns='{"ok": true, "started": id продолжения}.',
        refusals="needs_confirm — спроси «да» этим вопросом; continuation_not_found + waiting — такого не ждёт; not_started + detail.",
    )

    NOT_FOUND = "continuation_not_found"
    NOT_STARTED = "not_started"

    def __init__(self, book: ContinuationBook, user: str, runner: CommandRunner, program: Program) -> None:
        self._book = book
        self._user = user
        self._runner = runner
        self._program = program

    def consent_summary(self, arguments: Mapping[str, object]) -> str:
        item = next((item for item in self._book.asked(self._user) if item.id == arguments.get("continuation")), None)
        return f"выполнить отложенное: «{item.text}» (после «{item.title}»)" if item else super().consent_summary(arguments)

    def _run(self, request: ContinueJobRequest) -> ToolResult:
        waiting = [item.id for item in self._book.asked(self._user)]
        if request.continuation not in waiting:
            raise ToolRefusal(self.NOT_FOUND, waiting=waiting)
        try:
            self._runner.launch(self._program.detached("jobs", "--continue", request.continuation))
        except CommandError as error:
            raise ToolRefusal(self.NOT_STARTED, detail=str(error)) from error
        return ToolResult.success(started=request.continuation)
