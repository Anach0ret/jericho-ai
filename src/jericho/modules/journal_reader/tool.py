"""Ручка ядра `read_journal`: модель сама смотрит, что Jericho делал и чем это закончилось."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any, Literal

from pydantic import Field

from jericho.core.journal.entities import JournalEntry, PhraseRecord
from jericho.core.journal.protocols import JournalReader
from jericho.core.services.clock import local_now
from jericho.core.services.foreign import ForeignText
from jericho.core.tools.catalog import ToolCatalog
from jericho.core.tools.description import ToolDescription
from jericho.core.tools.request import ToolRequest
from jericho.core.tools.result import ToolResult
from jericho.core.tools.risk import Risk
from jericho.core.tools.tool import Tool
from jericho.modules.journal_reader.selection import Selection


def _failed(entry: JournalEntry) -> bool:
    """Фраза со сбоем или вызов ручки с отказом."""
    record = PhraseRecord.of(entry)
    return (record is not None and record.status == "failed") or (entry.result is not None and entry.result.get("ok") is False)


_KINDS: dict[str, Callable[[JournalEntry], bool]] = {
    "all": lambda entry: True,
    "phrases": lambda entry: entry.event == PhraseRecord.EVENT,
    "tools": lambda entry: entry.event == "tool",
    "errors": lambda entry: entry.level != "INFO" or _failed(entry),
}


class ReadJournalRequest(ToolRequest):
    kind: Literal["all", "phrases", "tools", "errors", "episodes"] = Field(
        default="all",
        description=(
            "Что показать: «phrases» — фразы и ответы на них, «tools» — вызовы ручек, «errors» — только неудачи, "
            "«all» — всё подряд, «episodes» — каждая фраза вместе с вызовами ручек, сделанными для неё: так видно, "
            "что было названо и что после этого сработало."
        ),
    )
    limit: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Сколько последних подходящих записей вернуть. Для вопроса «что было только что» хватит 10.",
    )
    tool: str | None = Field(
        default=None,
        pattern=r"^[a-z_]{2,40}$",
        description="Только вызовы этой ручки: «open_url», «page_click». Вместе с kind=errors — только её отказы.",
    )
    contains: str | None = Field(
        default=None,
        min_length=2,
        max_length=60,
        description=(
            "Только записи, где встречается этот текст — во фразе, параметрах или ответе, без учёта регистра: "
            "«курс», «lms.», «Anmelden»."
        ),
    )
    hours: int | None = Field(
        default=None, ge=1, le=24 * 60, description="Только записи за последние столько часов: 24 — сутки, 168 — неделя."
    )
    since: datetime | None = Field(
        default=None,
        description="Только записи не раньше этого времени: «2026-10-13» или «2026-10-13 09:00». Текущее время есть в ответе, поле now.",
    )


class ReadJournal(Tool[ReadJournalRequest]):
    """Отдаёт записи журнала в коротком виде: время, событие и главное из его подробностей.

    Фильтры складываются. Модель сама сужает выборку, пока не найдёт нужное: что называли, что сработало.

    Журнал — источник чужого текста: в нём лежат ответы ручек, а в них — куски страниц и писем. Отданные записи
    отмечаются в учёте чужого текста как источник `journal`, иначе путь «страница → журнал → модель» обходил бы
    проверки, которые ручки делают после чтения страницы.
    """

    FOREIGN_SOURCE = "journal"
    VEILED = "(ответ о переписке — без текста)"

    name = "read_journal"
    risk = Risk.READ
    request_type = ReadJournalRequest
    description = ToolDescription(
        when=(
            "спрашивают о прошлом: что ты делал, что было сказано раньше, почему что-то не получилось, какой "
            "была последняя команда; или нужно найти в прошлом повторяющееся — что пользователь называл и что "
            "в итоге сработало. Недавние реплики за две минуты уже есть в промпте — журнал нужен для того, "
            "что было раньше, и для подробностей вызовов."
        ),
        does=(
            "читает журнал событий Jericho и отбирает записи по виду, ручке, тексту и времени — фильтры "
            "складываются. Ничего не меняет; load_skill не нужен. Ищи фильтрами, а не читай всё подряд: сначала "
            "узко, не нашёл — расширь."
        ),
        returns=(
            '{"ok": true, "now": текущее время, "entries": [...] — от старых к новым, "found": сколько записей '
            'подошло всего}; found больше, чем пришло, — сузь фильтр или подними limit. У записи: time; event — '
            "phrase (фраза и ответ), tool (вызов ручки: tool, params, result), voice (что услышано или сбой записи), "
            "dry_run (команда вхолостую), error; остальные поля — подробности события. При kind=episodes запись — "
            "это фраза: time, phrase, status, message и calls — её вызовы по порядку (tool, params, ok или error)."
        ),
        refusals="invalid_parameters + problems.",
    )

    _SCAN = 5000             # сколько последних записей просматривать: журнал за несколько недель
    _TEXT_LIMIT = 200

    def __init__(
        self,
        journal: JournalReader,
        tools: ToolCatalog | None = None,
        now: Callable[[], datetime] | None = None,
        foreign: ForeignText | None = None,
    ) -> None:
        self._journal = journal
        self._foreign = foreign or ForeignText()
        self._tools = tools or ToolCatalog()
        self._now = now or local_now

    @classmethod
    def _veiled(cls, entries: list[JournalEntry]) -> list[JournalEntry]:
        """Ответ на фразу, в которой ручка отдала личный текст (`Tool.private`), модели из журнала не показывается:
        это та же чужая переписка, только пересказанная. Человеку — показывается (окно на панели, `log`).

        Вход поручения и так пишет вместо такого ответа memo (`PhraseJournal`); это вторая линия — для записей,
        где memo почему-либо не сработал."""
        private = {entry.run for entry in entries if entry.event == "tool" and entry.details.get("private") and entry.run}
        return [
            replace(entry, details={**entry.details, **record.veiled(cls.VEILED).details()})
            if (record := PhraseRecord.of(entry)) is not None and entry.run in private else entry
            for entry in entries
        ]

    def _run(self, request: ReadJournalRequest) -> ToolResult:
        now = self._now()
        selection = Selection(self._earliest(request, now), request.tool, request.contains)
        entries = self._veiled(self._journal.tail(self._SCAN))
        found = self._episodes(entries, selection) if request.kind == "episodes" else self._entries(entries, request.kind, selection)
        if found:
            self._foreign.read_from(self.FOREIGN_SOURCE)
        return ToolResult.success(now=f"{now:%Y-%m-%d %H:%M}", entries=self._short(found[-request.limit :]), found=len(found))

    def _entries(self, entries: list[JournalEntry], kind: str, selection: Selection) -> list[dict[str, object]]:
        fits = _KINDS[kind]
        return [
            {"time": f"{entry.time:%d.%m %H:%M:%S}", "event": entry.event, **self._present(entry.details)}
            for entry in entries
            if fits(entry) and selection.passes(entry.time, [entry.details.get("tool")], self._text(entry.details))
        ]

    def _episodes(self, entries: list[JournalEntry], selection: Selection) -> list[dict[str, object]]:
        """Фраза и вызовы ручек одного запуска — один эпизод. Служебные вызовы не в счёт.

        У записей старше 13.10.2026 запуска нет: они связываются по порядку — вызовы перед фразой сделаны для неё.
        Вызовы запуска, который оборвался без записи о фразе, ни к кому не попадают.
        """
        episodes: list[dict[str, object]] = []
        calls: defaultdict[str, list[dict[str, object]]] = defaultdict(list)
        aside = {self.name, *self._tools.service}     # в эпизоде они заслоняют дело; как и само чтение журнала
        for entry in entries:
            if entry.event == "tool" and entry.details.get("tool") not in aside:
                calls[entry.run].append(self._call(entry))
            elif (record := PhraseRecord.of(entry)) is not None:
                made = calls.pop(entry.run, [])
                episode = {
                    "time": f"{entry.time:%d.%m %H:%M}", "phrase": record.phrase, "status": record.status, "message": record.message,
                    "calls": made,
                }
                if selection.passes(entry.time, [call["tool"] for call in made], self._text(episode)):
                    episodes.append(episode)
        return episodes

    @staticmethod
    def _call(entry: JournalEntry) -> dict[str, object]:
        call: dict[str, object] = {"tool": entry.details.get("tool"), "params": entry.details.get("params")}
        if _failed(entry):
            return {**call, "error": (entry.result or {}).get("error", "failed")}
        return {**call, "ok": True}

    @staticmethod
    def _earliest(request: ReadJournalRequest, now: datetime) -> datetime | None:
        """Самая поздняя из двух границ: «за последние N часов» и «не раньше такого-то времени»."""
        since = request.since
        if since is not None and since.tzinfo is None:
            since = since.replace(tzinfo=now.tzinfo)       # время без пояса — местное
        bounds = [bound for bound in (since, now - timedelta(hours=request.hours) if request.hours else None) if bound]
        return max(bounds) if bounds else None

    @staticmethod
    def _text(content: Mapping[str, object]) -> str:
        return json.dumps(dict(content), ensure_ascii=False, default=str)

    @staticmethod
    def _present(details: Mapping[str, object]) -> dict[str, object]:
        return {name: value for name, value in details.items() if value is not None}

    def _short(self, value: object) -> Any:
        if isinstance(value, str) and len(value) > self._TEXT_LIMIT:
            return f"{value[: self._TEXT_LIMIT]}…"
        if isinstance(value, dict):
            return {name: self._short(item) for name, item in value.items()}  # pyright: ignore[reportUnknownVariableType]
        if isinstance(value, list):
            return [self._short(item) for item in value]  # pyright: ignore[reportUnknownVariableType]
        return value
