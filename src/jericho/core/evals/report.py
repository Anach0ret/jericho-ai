"""Отчёт о прогоне: строки для терминала и запись для сравнения со следующим прогоном."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import ClassVar

from jericho.core.evals.entities import ActualCall, CaseResult, ExpectedCall


class EvalReport:
    """Показывает, что модель сделала на каждую фразу, где разошлась с ожиданием и что изменилось с прошлого раза."""

    _NAMES: ClassVar[dict[str, str]] = {"tools": "ручки", "params": "параметры", "outcome": "исход", "status": "статус", "message": "сообщение"}
    _PASSED, _FAILED = "✓", "✗"

    def __init__(self, results: Sequence[CaseResult]) -> None:
        self._results = tuple(results)

    def lines(self) -> list[str]:
        return [line for result in self._results for line in self._case(result)] + ["", self.summary()]

    def summary(self) -> str:
        total = len(self._results)
        by_criterion = "  ".join(
            f"{self._NAMES[name]} {sum(result.marks[name] for result in self._results)}/{total}"
            for name in CaseResult.CRITERIA
        )
        seconds = sum(result.outcome.seconds for result in self._results)
        cost = sum(result.outcome.cost_usd for result in self._results)
        passed = sum(result.passed for result in self._results)
        return f"Прошло {passed} из {total}  ·  {by_criterion}  ·  {seconds:.0f} с  ·  ${cost:.3f}"

    def changes(self, previous: Mapping[str, Mapping[str, bool]]) -> list[str]:
        """Фразы, у которых оценка стала другой: что починилось и что сломалось."""
        lines: list[str] = []
        for result in self._results:
            before = previous.get(result.case.key)
            # Критерий, которого в прошлом прогоне ещё не было, не сравнивается: «изменением» он не является.
            compared = {name: mark for name, mark in result.marks.items() if before is not None and name in before}
            if before is None or all(before[name] == mark for name, mark in compared.items()):
                continue
            changed = ", ".join(
                f"{self._NAMES[name]} {self._mark(before[name])}→{self._mark(mark)}"
                for name, mark in compared.items()
                if before[name] != mark
            )
            lines.append(f"  {result.case.key:<12} {result.case.phrase}: {changed}")
        return lines

    def record(self) -> dict[str, object]:
        return {
            "summary": self.summary(),
            "cases": [
                {
                    "key": result.case.key,
                    "phrase": result.case.phrase,
                    "marks": result.marks,
                    "expected": {"calls": self._expected(result.case.calls), "statuses": list(result.case.statuses)},
                    "calls": [{"tool": call.tool, "params": dict(call.params), "result": dict(call.result)} for call in result.outcome.calls],
                    "status": result.outcome.status,
                    "message": result.outcome.message,
                    "turns": result.outcome.turns,
                    "seconds": result.outcome.seconds,
                    "cost_usd": result.outcome.cost_usd,
                }
                for result in self._results
            ],
        }

    def _case(self, result: CaseResult) -> list[str]:
        outcome = result.outcome
        happened = f"{self._actual(outcome.calls)} · {outcome.status} · «{outcome.message}»"
        lines = [f"{self._mark(result.passed)} {result.case.key:<12} {result.case.phrase}", f"    было:  {happened}"]
        if not result.passed:
            failed = ", ".join(self._NAMES[name] for name, mark in result.marks.items() if not mark)
            expected = f"{self._expected(result.case.calls)} · {'/'.join(result.case.statuses)}"
            lines.append(f"    ждали: {expected}   ← не сошлось: {failed}")
        return lines

    def _mark(self, passed: bool) -> str:
        return self._PASSED if passed else self._FAILED

    @staticmethod
    def _actual(calls: Sequence[ActualCall]) -> str:
        return "; ".join(f"{call.tool} {json.dumps(dict(call.params), ensure_ascii=False)}" for call in calls) or "—"

    @staticmethod
    def _expected(calls: Sequence[ExpectedCall]) -> str:
        return "; ".join(
            f"{call.tool}{'?' if call.optional else ''}"
            + (f" {json.dumps(dict(call.params), ensure_ascii=False)}" if call.params else "")
            for call in calls
        ) or "—"
