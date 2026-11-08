"""Состояние голоса в файле JSON в папке времени выполнения: его читает виджет панели, сколько угодно часто."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping
from pathlib import Path

from jericho.core.services.adapters.json_file import JsonStateFile
from jericho.modules.voice.protocols import VoiceState

logger = logging.getLogger(__name__)


class StatusFile:
    """`{"state", "detail", "since", "until"}`; время — секунды Unix.

    `until` — когда состояние перестаёт быть правдой, даже если его никто не сменил: процесс фразы упал,
    машину усыпили. Читатель после этого срока показывает «свободен». У «свободен» срока нет (`null`).
    """

    def __init__(self, path: Path, lasts: Mapping[VoiceState, float], clock: Callable[[], float] = time.time) -> None:
        self._file = JsonStateFile(path)
        self._lasts = dict(lasts)      # сколько секунд длится каждое состояние самое большее
        self._clock = clock

    def current(self) -> dict[str, object]:
        """Что сейчас правда: состояние с вышедшим сроком — уже «свободен». Файла нет — голосом не пользовались."""
        content = self._file.read(lambda raw: raw if isinstance(raw, dict) else {}, {})
        until = content.get("until")
        if not content or (isinstance(until, int | float) and self._clock() > until):
            return {"state": VoiceState.IDLE.value, "detail": ""}
        return {"state": content.get("state", VoiceState.IDLE.value), "detail": content.get("detail", "")}

    def set(self, state: VoiceState, detail: str = "") -> None:
        now = self._clock()
        lasts = self._lasts.get(state)
        content = {"state": state.value, "detail": detail, "since": now, "until": now + lasts if lasts else None}
        try:
            self._file.write(content)
        except OSError as error:
            logger.warning("voice_status_failed", extra={"data": {"error": str(error), "state": state.value}})
