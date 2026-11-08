"""Доказательство для заметки: значение должно быть тем, что уже сработало."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Protocol

from jericho.core.journal.protocols import JournalReader
from jericho.core.tools.tool import Tool


class Evidence(Protocol):
    def supports(self, kind: str, value: str) -> bool:
        """Срабатывало ли это значение там, где заметке такого вида можно верить."""
        ...


class ProofError(Exception):
    """Ручка объявила доказательством поле, которого у неё нет."""


def declared_proofs(tools: Iterable[Tool[Any]]) -> dict[str, frozenset[tuple[str, str]]]:
    """Вид заметки → пары «ручка, поле», которые его подтверждают. Собирается из объявлений `proves` у ручек."""
    proofs: dict[str, set[tuple[str, str]]] = {}
    for tool in tools:
        for field, kind in tool.proves.items():
            if field not in tool.request_type.model_fields:
                raise ProofError(f"{tool.name}: proves names field '{field}', but the request has no such field")
            proofs.setdefault(kind, set()).add((tool.name, field))
    return {kind: frozenset(pairs) for kind, pairs in proofs.items()}


class JournalEvidence:
    """Верит только журналу: значение стояло в названном поле названной ручки, и вызов закончился успехом.

    Так в заметки не попадает ни выдуманное, ни прочитанное на чужой странице: адрес должен был открыться,
    надпись — нажаться, приложение — запуститься. Вызов текущей фразы к этому моменту уже в журнале.

    Сравнение точное и только с полями, которые ручки объявили доказательством (`Tool.proves`). Раньше значение
    искалось подстрокой во всех параметрах — и адрес, введённый в поле поиска, или кусок длинного текста
    становились «проверенными». Вид заметки, который не подтверждает ни одна ручка, записать нельзя.
    """

    def __init__(self, journal: JournalReader, proofs: Mapping[str, frozenset[tuple[str, str]]], scan: int = 5000) -> None:
        self._journal = journal
        self._proofs = proofs
        self._scan = scan

    def supports(self, kind: str, value: str) -> bool:
        proofs = self._proofs.get(kind, frozenset())
        for entry in reversed(self._journal.tail(self._scan)):
            params = entry.details.get("params")
            if not entry.call_succeeded or not isinstance(params, dict):
                continue
            # Значение заметки — строка, а в вызове поле бывает числом (chat_id): сверяются как текст.
            if any(tool == entry.details.get("tool") and field in params and str(params[field]) == value for tool, field in proofs):
                return True
        return False
