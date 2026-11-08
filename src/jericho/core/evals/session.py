"""Прогон проверочных фраз."""

from __future__ import annotations

from collections.abc import Collection, Sequence

from jericho.core.evals.entities import CaseResult, EvalCase
from jericho.core.evals.protocols import EvalSource, PhraseRunner


class EvalSession:
    """Прогоняет фразы по одной, каждую — в новом разговоре.

    Фраза, помеченная «после N», идёт в одном разговоре с фразой N: сначала заново произносится N
    (без оценки), потом она сама. Ожидание подстраивается под подключённые ручки.
    """

    def __init__(
        self,
        sources: Sequence[EvalSource],
        runner: PhraseRunner,
        connected_tools: Collection[str],
        service_tools: Collection[str] = (),
    ) -> None:
        self._sources = tuple(sources)
        self._runner = runner
        self._connected = frozenset(connected_tools)
        self._service = frozenset(service_tools)   # ручки ядра (`load_skill`): в ожиданиях их нет, в оценку не идут

    def cases(self) -> tuple[EvalCase, ...]:
        return tuple(case for source in self._sources for case in source.cases())

    def run(self, only: Collection[str] = ()) -> list[CaseResult]:
        cases = {case.key: case for case in self.cases()}
        chosen = [case for case in cases.values() if not only or case.key in only]
        return [self._result(case, cases) for case in chosen]

    def _result(self, case: EvalCase, cases: dict[str, EvalCase]) -> CaseResult:
        self._runner.forget()
        if case.after:
            self._runner.run(cases[case.after].phrase)
        outcome = self._runner.run(case.phrase)
        return CaseResult(case.for_connected(self._connected), outcome.without(self._service))
