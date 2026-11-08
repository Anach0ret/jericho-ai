"""Общий срок поручения: один абсолютный момент на всю фразу — для запасных бэкендов, моделей и сервера ручек."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping


class PhraseDeadline:
    """До какого момента фраза может действовать. Момент — по `time.time()`: его понимает и сервер ручек, другой процесс.

    Раньше срок отсчитывал каждый бэкенд сам: запасной начинал полный срок заново, перебор моделей OpenAI давал каждой
    весь остаток, а сервер ручек срока не знал вовсе — после `agent.timeout` ручка ещё начиналась (ревью 02.11.2026,
    сводка №9; критика плана 07.11.2026, риск 1). Теперь срок ставит `HandlePhrase` в начале фразы, бэкенды берут
    остаток, а диспетчер не начинает ручку, если срок вышел. Серверу ручек срок приходит переменной `JERICHO_DEADLINE`.

    Срок не поставлен (`left()` — None) — вызов не из фразы: человек в терминале, проверка ручки.
    """

    VARIABLE = "JERICHO_DEADLINE"

    def __init__(self, seconds: float | None = None, until: float | None = None, clock: Callable[[], float] = time.time) -> None:
        self._seconds = seconds       # сколько живёт фраза (`agent.timeout`); None — фразы этот процесс не ведёт
        self._parent = until          # срок того, кто поднял этот процесс: его не перешагнуть
        self._until = until
        self._clock = clock

    @classmethod
    def from_environment(cls, environment: Mapping[str, str], seconds: float | None = None) -> PhraseDeadline:
        """В сервере ручек срок уже идёт — его поставила фраза, которая сервер подняла."""
        inherited = environment.get(cls.VARIABLE)
        return cls(seconds, float(inherited) if inherited else None)

    def start(self) -> None:
        """Фраза началась: срок — `seconds` с этого момента, но не позже срока родителя, если он был."""
        if self._seconds is None:
            return
        own = self._clock() + self._seconds
        self._until = own if self._parent is None else min(own, self._parent)

    def stop(self) -> None:
        self._until = self._parent

    def left(self) -> float | None:
        """Сколько секунд осталось; None — срока нет."""
        return None if self._until is None else self._until - self._clock()

    def passed(self) -> bool:
        left = self.left()
        return left is not None and left <= 0

    def environment(self) -> dict[str, str]:
        """Что передать серверу ручек: тот же момент, а не «сколько-то секунд» — пока он соберётся, они уйдут."""
        return {self.VARIABLE: repr(self._until)} if self._until is not None else {}
