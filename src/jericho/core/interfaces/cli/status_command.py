"""Снимок ассистента одной командой — для внешних программ: окна на панели, виджета, скрипта.

Внешняя программа читает только этот снимок, а не внутренние файлы каркаса: их формат — дело каркаса.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from typing import TypedDict

from jericho.core.interfaces.cli.model_command import ModelCommand
from jericho.core.journal.entities import JournalEntry, PhraseRecord
from jericho.core.journal.protocols import JournalReader
from jericho.core.journal.reply_vault import ReplyVault
from jericho.core.modules.registry import InstalledModules
from jericho.core.services.confirmation import ConfirmationGate


class Exchange(TypedDict):
    time: str
    phrase: str
    status: str
    message: str
    body: str
    model: str | None     # имя бэкенда; «» — ответ собран без модели (кнопка, «да»); None — журнал этого не знает
    options: list[str]    # варианты ответа на вопрос — кнопками в окне


class Choice(TypedDict):
    name: str
    label: str


class Models(TypedDict):
    choices: list[Choice]
    current: str | None     # какая сейчас отвечает: выбранная вручную или по умолчанию; None — выбора нет
    default: str | None
    chosen: bool            # выбрана вручную, а не по умолчанию — окно подсвечивает, чтобы не забыть


class Action(TypedDict):
    time: str
    tool: str
    params: str       # параметры одной строкой, обрезанные: окну — чтобы узнать вызов, а не разобрать его
    ok: bool
    error: str        # код отказа; пусто — получилось
    detail: str


class Snapshot(TypedDict):
    assistant: str
    question: str | None
    model: str | None       # кто ответил на последнюю фразу (бэкенд); выбор на будущее — в `models`
    models: Models
    conversation: list[Exchange]
    actions: list[Action]   # последние вызовы ручек «по делу» (без служебных: load_skill, remember…), новые внизу
    modules: dict[str, Mapping[str, object]]


class StatusCommand:
    name = "status"
    help = "снимок для внешних программ (JSON): последние фразы и ответы, ждущий вопрос, данные модулей"

    PHRASES = 10        # сколько последних фраз отдать
    SHOWN = frozenset({PhraseRecord.EVENT, "script"})     # фразы и запуски сценариев (кнопкой в окне) — то, что видит человек
    ACTIONS = 12        # сколько последних действий отдать
    PARAMS = 80         # знаков у строки параметров
    RECENT = 1000       # сколько последних записей журнала просмотреть: между фразами — вызовы ручек

    def __init__(
        self, program: str, gate: ConfirmationGate, journal: JournalReader, modules: InstalledModules, model: ModelCommand,
        service: frozenset[str] = frozenset(), vault: ReplyVault | None = None,
    ) -> None:
        self._service = service      # служебные ручки: в «что сделал» не попадают
        self._vault = vault          # полные ответы о переписке — пока жив сеанс; в журнале фраз у них только memo
        self._program = program
        self._gate = gate
        self._journal = journal
        self._modules = modules
        self._model = model

    def configure(self, parser: argparse.ArgumentParser) -> None:
        pass

    def run(self, args: argparse.Namespace) -> None:
        print(json.dumps(self.snapshot(), ensure_ascii=False, default=str))

    def snapshot(self) -> Snapshot:
        """`conversation` — по порядку, последняя фраза внизу. Берётся из журнала: память разговора живёт минуты."""
        recent = self._journal.tail(self.RECENT)
        phrases = [entry for entry in recent if entry.event in self.SHOWN][-self.PHRASES:]
        calls = [entry for entry in recent if entry.event == "tool" and entry.details.get("tool") not in self._service][-self.ACTIONS:]
        conversation = [self._revealed(entry, self._exchange(entry)) for entry in phrases]
        return {
            "assistant": self._program,
            "question": self._gate.question(),
            "model": conversation[-1]["model"] if conversation else None,
            "models": self._models(),
            "conversation": conversation,
            "actions": [self._action(entry) for entry in calls],
            "modules": self._modules.statuses(),
        }

    def _models(self) -> Models:
        choices, current, default = self._model.choices(), self._model.current(), self._model.default()
        return Models(
            choices=[Choice(name=name, label=choice.label) for name, choice in choices.items()],
            current=current, default=default, chosen=current is not None and current != default,
        )

    def _action(self, entry: JournalEntry) -> Action:
        details, result = entry.details, entry.result or {}
        params = details.get("params")
        shown = ", ".join(f"{key}={value}" for key, value in params.items()) if isinstance(params, Mapping) else ""
        if len(shown) > self.PARAMS:
            shown = shown[: self.PARAMS - 1] + "…"
        detail = result.get("detail")
        return Action(
            time=entry.time.isoformat(timespec="seconds"), tool=str(details.get("tool", "")), params=shown,
            ok=result.get("ok") is True, error=str(result.get("error") or ""), detail=detail if isinstance(detail, str) else "",
        )

    def _revealed(self, entry: JournalEntry, exchange: Exchange) -> Exchange:
        """Ответ о личной переписке человеку показывается целиком — из папки сеанса, пока она жива."""
        record = PhraseRecord.of(entry)
        kept = self._vault.get(entry.run) if self._vault is not None and record is not None and record.private else None
        if kept is None:
            return exchange
        return Exchange(**{**exchange, "message": kept[0], "body": kept[1]})

    @staticmethod
    def _exchange(entry: JournalEntry) -> Exchange:
        details = entry.details
        if entry.event == "script":      # сценарий без модели: «фраза» — его название, ответ — итог
            return Exchange(
                time=entry.time.isoformat(timespec="seconds"), phrase=f"▶ {details.get('title', details.get('script', ''))}",
                status="done" if details.get("ok") else "clarify" if details.get("waiting") else "failed",
                message=str(details.get("summary", "")), body="", model="", options=[],
            )
        record = PhraseRecord.of(entry) or PhraseRecord("", "")
        return Exchange(
            time=entry.time.isoformat(timespec="seconds"), phrase=record.phrase, status=record.status, message=record.message,
            body=record.body, model=record.backend if record.backend is not None else "" if record.without_model else None,
            options=list(record.options),
        )
