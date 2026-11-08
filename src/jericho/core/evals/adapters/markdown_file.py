"""Проверочные фразы из файла `evals.md`.

Фразы — строки таблицы с колонками «# | Фраза | Ручки | Статус | После | Заметка». В колонке «Ручки»:

    —                                              ни одной ручки
    open_project {"project": "site"}               вызов с важными параметрами
    open_app {"workspace": 3}; open_app            два вызова
    hyprctl?                                       вызов допустим, но не обязателен
    close_windows !needs_confirm                   вызов, который должен отказать этим кодом

Статусов может быть несколько через «/» — когда правильный ответ зависит от того, что сейчас на столе.
"""

from __future__ import annotations

import json
from pathlib import Path

from jericho.core.evals.entities import EvalCase, ExpectedCall


class MarkdownEvalFile:
    """Читает фразы одного файла; ключ фразы — «<источник>:<номер>»."""

    _NOTHING = ("", "—", "-")
    _COLUMNS = 6

    def __init__(self, source: str, file: Path) -> None:
        self._source = source
        self._file = file

    def cases(self) -> tuple[EvalCase, ...]:
        rows = (self._cells(line) for line in self._file.read_text(encoding="utf-8").splitlines())
        return tuple(self._case(cells) for cells in rows if cells and cells[0].isdigit())

    def _cells(self, line: str) -> list[str]:
        if not line.startswith("|"):
            return []
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        return cells + [""] * (self._COLUMNS - len(cells))

    def _case(self, cells: list[str]) -> EvalCase:
        number, phrase, calls, statuses, after, note = cells[: self._COLUMNS]
        try:
            expected = tuple(self._call(text) for text in calls.split(";") if text.strip() not in self._NOTHING)
        except ValueError as error:
            raise ValueError(f"{self._file}: фраза {number}: {error}") from error
        return EvalCase(
            key=self._key(number),
            phrase=phrase,
            calls=expected,
            statuses=tuple(status.strip() for status in statuses.split("/")),
            after=self._key(after) if after not in self._NOTHING else "",
            note=note,
        )

    def _key(self, number: str) -> str:
        return f"{self._source}:{number}"

    @staticmethod
    def _call(text: str) -> ExpectedCall:
        name, _, rest = text.strip().replace("`", "").partition(" ")
        params, _, error = rest.partition("!")
        optional = name.endswith("?")
        return ExpectedCall(name.rstrip("?"), json.loads(params) if params.strip() else {}, optional, error.strip())
