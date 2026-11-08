"""Проверочная фраза, то, что на неё произошло, и оценка."""

from __future__ import annotations

from collections import Counter
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field, replace


@dataclass(frozen=True, slots=True)
class ExpectedCall:
    """Вызов ручки, которого ждём: имя и те параметры, которые важны. Остальные параметры не сравниваются."""

    tool: str
    params: Mapping[str, object] = field(default_factory=dict)
    optional: bool = False     # вызов допустим в любом количестве, но не обязателен: «посмотреть окна»
    error: str = ""            # ожидаемый отказ (`needs_confirm`); пусто — вызов должен пройти успешно

    def fits(self, call: ActualCall) -> bool:
        return call.tool == self.tool and all(call.params.get(name) == value for name, value in self.params.items())


@dataclass(frozen=True, slots=True)
class ActualCall:
    """Вызов ручки, который сделала модель, как он записан в журнале."""

    tool: str
    params: Mapping[str, object]
    result: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class EvalCase:
    """Одна проверочная фраза и её ожидание."""

    REFUSED = "refused"

    key: str                              # «desktop:11» — файл и номер в нём
    phrase: str
    calls: tuple[ExpectedCall, ...]
    statuses: tuple[str, ...]             # любой из перечисленных статусов годится
    after: str = ""                       # ключ фразы, после которой эта идёт в том же разговоре («да» после вопроса)
    note: str = ""

    def for_connected(self, tools: Collection[str]) -> EvalCase:
        """Ожидание с учётом того, что подключено.

        Все нужные ручки на месте — ожидание как записано. Ни одной нет — правильный ответ «пока не умею»,
        без вызовов. Есть часть (составная фраза: «открой проект и включи музыку») — ждём то, что сделать
        можно; о несделанном модель говорит в сообщении, а статус годится и записанный, и `refused`.
        """
        connected = tuple(call for call in self.calls if call.tool in tools)
        if len(connected) == len(self.calls):
            return self
        if not any(not call.optional for call in connected):
            return EvalCase(self.key, self.phrase, (), (self.REFUSED,), self.after, self.note)
        statuses = (*self.statuses, *((self.REFUSED,) if self.REFUSED not in self.statuses else ()))
        return EvalCase(self.key, self.phrase, connected, statuses, self.after, self.note)


@dataclass(frozen=True, slots=True)
class PhraseOutcome:
    """Что произошло на фразу: вызовы ручек, ответ и цена."""

    calls: tuple[ActualCall, ...] = ()
    status: str = ""
    message: str = ""
    turns: int = 0
    seconds: float = 0.0
    cost_usd: float = 0.0

    def without(self, tools: Collection[str]) -> PhraseOutcome:
        """То же, но без вызовов названных ручек."""
        return replace(self, calls=tuple(call for call in self.calls if call.tool not in tools))


@dataclass(frozen=True, slots=True)
class CaseResult:
    """Фраза, ожидание с учётом подключённых ручек и то, что получилось."""

    MESSAGE_LIMIT = 80
    CRITERIA = ("tools", "params", "outcome", "status", "message")

    case: EvalCase
    outcome: PhraseOutcome

    @property
    def tools_ok(self) -> bool:
        """Вызваны ровно те ручки, что нужны: ни одной лишней, ни одной пропущенной."""
        optional = {call.tool for call in self.case.calls if call.optional}
        expected = Counter(call.tool for call in self.case.calls if not call.optional)
        actual = Counter(call.tool for call in self.outcome.calls if call.tool not in optional)
        return actual == expected

    @property
    def params_ok(self) -> bool:
        """Каждому ожидаемому вызову нашёлся свой настоящий с теми же важными параметрами."""
        return all(actual is not None for _, actual in self._matched())

    @property
    def outcome_ok(self) -> bool:
        """Исход вызовов: ожидаемые прошли (или отказали тем самым кодом), а «сделано» не сказано поверх отказа.

        Без этого фраза засчитывалась, когда ручка вернула сбой, а модель ответила `done` (ревью R10).
        """
        # Пропущенный вызов — забота критериев «ручки» и «параметры».
        if any(actual is not None and self._error(actual) != expected.error for expected, actual in self._matched()):
            return False
        expected_errors = {call.error for call in self.case.calls if call.error}
        unexpected = [call for call in self.outcome.calls if self._error(call) and self._error(call) not in expected_errors]
        return not (self.outcome.status == "done" and unexpected)

    def _matched(self) -> list[tuple[ExpectedCall, ActualCall | None]]:
        """Каждому обязательному ожидаемому вызову — свой настоящий с теми же важными параметрами, или None.

        Настоящий вызов достаётся одному ожидаемому: два одинаковых ожидания требуют двух вызовов.
        """
        remaining = list(self.outcome.calls)
        pairs: list[tuple[ExpectedCall, ActualCall | None]] = []
        for expected in (call for call in self.case.calls if not call.optional):
            actual = next((call for call in remaining if expected.fits(call)), None)
            if actual is not None:
                remaining.remove(actual)
            pairs.append((expected, actual))
        return pairs

    @staticmethod
    def _error(call: ActualCall) -> str:
        return "" if call.result.get("ok", True) is True else str(call.result.get("error", "failed"))

    @property
    def status_ok(self) -> bool:
        return self.outcome.status in self.case.statuses

    @property
    def message_ok(self) -> bool:
        return len(self.outcome.message) <= self.MESSAGE_LIMIT

    @property
    def marks(self) -> dict[str, bool]:
        return {
            "tools": self.tools_ok, "params": self.params_ok, "outcome": self.outcome_ok,
            "status": self.status_ok, "message": self.message_ok,
        }

    @property
    def passed(self) -> bool:
        return all(self.marks.values())
