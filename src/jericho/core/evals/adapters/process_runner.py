"""Фраза через настоящий запуск ассистента: отдельный процесс на фразу, как у голосовой команды или задачи."""

from __future__ import annotations

import subprocess
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path

from jericho.core.evals.entities import ActualCall, PhraseOutcome
from jericho.core.journal.entities import PhraseRecord
from jericho.core.journal.protocols import JournalReader
from jericho.core.services.clock import local_now


class ProcessPhraseRunner:
    """Запускает `jericho ask` в отдельном варианте настроек и читает из его журнала, что произошло.

    У варианта свои папки состояния: прогон не трогает ни настоящую память разговора, ни настоящий журнал.
    """

    FAILED = "failed"
    _TAIL = 200           # с запасом: одна фраза — это несколько записей

    def __init__(
        self,
        command: Sequence[str],
        environment: Mapping[str, str],
        journal: JournalReader,
        conversation_files: Sequence[Path],
        roots: Sequence[Path],
        timeout: float = 150.0,
    ) -> None:
        outside = [file for file in conversation_files if not any(file.is_relative_to(root) for root in roots)]
        if outside:      # последний рубеж: даже ошибка сборки не должна дать прогону стереть чужой файл
            raise ValueError(f"eval would remove files outside its own folders: {', '.join(map(str, outside))}")
        self._command = list(command)
        self._environment = dict(environment)
        self._journal = journal
        self._conversation_files = tuple(conversation_files)
        self._timeout = timeout

    def forget(self) -> None:
        for file in self._conversation_files:
            file.unlink(missing_ok=True)

    def run(self, phrase: str) -> PhraseOutcome:
        started = local_now()
        try:
            subprocess.run(
                [*self._command, phrase], env=self._environment, capture_output=True, timeout=self._timeout, check=False
            )
        except (subprocess.TimeoutExpired, OSError) as error:
            return PhraseOutcome(status=self.FAILED, message=str(error))
        return self._outcome(started)

    def _outcome(self, started: datetime) -> PhraseOutcome:
        """Запись фразы — последняя после старта; вызовы — того же запуска (`run`), а не «все после времени»."""
        entries = [entry for entry in self._journal.tail(self._TAIL) if entry.time >= started]
        entry = next((entry for entry in reversed(entries) if entry.event == PhraseRecord.EVENT), None)
        record = PhraseRecord.of(entry) if entry is not None else None
        if entry is None or record is None:
            return PhraseOutcome(status=self.FAILED, message="в журнале нет записи о фразе")
        calls = tuple(
            ActualCall(str(item.details["tool"]), dict(item.details["params"]), dict(item.details["result"]))  # pyright: ignore[reportArgumentType, reportCallIssue]
            for item in entries
            if item.event == "tool" and item.run == entry.run
        )
        return PhraseOutcome(
            calls=calls, status=record.status, message=record.message, turns=record.turns, seconds=record.ms / 1000, cost_usd=record.cost_usd,
        )
