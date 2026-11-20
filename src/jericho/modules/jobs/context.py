"""Строка о фоновых работах в общем промпте: на «готово?» Jericho отвечает по ней, а не запускает дело заново."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import ClassVar

from jericho.core.jobs.book import ContinuationBook
from jericho.core.jobs.continuation import Continuation
from jericho.core.jobs.entities import JobStatus
from jericho.core.jobs.history import JobHistory, JobState


class JobsLine:
    """Подстановка `{{jobs}}`: недавние работы — вид, id, когда начата и чем кончилась.

    Заголовка и итога словами здесь нет: в них название ролика или файла — чужой текст сайта (ревью 110, №3).
    Их отдаёт `read_journal` (kind="jobs"), а он отмечает прочитанное как чужое.
    """

    WORDS: ClassVar[dict[JobStatus | None, str]] = {
        None: "идёт",
        JobStatus.SUCCEEDED: "готово",
        JobStatus.FAILED: "не вышло",
        JobStatus.WAITING_USER: "ждёт ответа пользователя",
        JobStatus.STOPPED: "остановлена",
        JobStatus.OUTCOME_UNKNOWN: "оборвалась, итог неизвестен — не повторяй без пользователя",
    }

    def __init__(self, history: JobHistory, book: ContinuationBook, user: str, now: Callable[[], datetime], hours: int, shown: int) -> None:
        self._history = history
        self._book = book
        self._user = user
        self._now = now
        self._window = timedelta(hours=hours)
        self._shown = shown

    def values(self) -> dict[str, str]:
        jobs = self._history.since(self._now() - self._window)[-self._shown :]
        lines = [*map(self._line, jobs), *map(self._asked, self._book.asked(self._user))]
        return {"jobs": "\n".join(lines) if lines else "Фоновых работ за последние часы не было."}

    @staticmethod
    def _asked(item: Continuation) -> str:
        """Текст продолжения — слова пользователя, но мог включать личное: в промпт — только id (ревью 110, №4)."""
        return f"- продолжение {item.id} после работы {item.job} ждёт решения пользователя: {item.reason} — выполнить можно job_continue"

    def _line(self, state: JobState) -> str:
        return f"- {state.ticket.kind} (работа {state.ticket.job}, начата {state.started:%d.%m %H:%M}): {self.WORDS[state.status]}"
