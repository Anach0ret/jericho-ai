"""Журнал событий: что Jericho делал и чем это закончилось."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from types import MappingProxyType
from typing import ClassVar


@dataclass(frozen=True, slots=True)
class JournalEntry:
    """Одна запись журнала."""

    time: datetime
    event: str                                              # что произошло: tool, phrase, dry_run, error
    level: str = "INFO"                                     # уровень стандартного logging: INFO, WARNING, ERROR
    source: str = ""                                        # имя логгера — модуль, который сделал запись
    details: Mapping[str, object] = field(default_factory=dict)
    run: str = ""                                           # запуск, обрабатывавший фразу; общий у фразы и её вызовов
    user: str = ""                                          # чьё поручение (`JERICHO_USER`); пусто — единственный пользователь

    @property
    def result(self) -> Mapping[str, object] | None:
        """Ответ ручки у записи о вызове (`tool`); у других записей и у записи не того вида — None."""
        result = self.details.get("result") if self.event == "tool" else None
        return result if isinstance(result, Mapping) else None

    @property
    def call_succeeded(self) -> bool:
        """Запись о вызове ручки, который закончился успехом."""
        return self.result is not None and self.result.get("ok") is True


@dataclass(frozen=True, slots=True)
class PhraseRecord:
    """Запись «фраза»: что сказали и что ответили. Единственное место, где решено, как она лежит в журнале.

    Пишет её вход поручения (`PhraseJournal`), читают окно на панели (`status`), ручка `read_journal` и прогон
    проверок — все через этот класс, а не по строковым ключам. Сведения о запросе к модели (ходы, стоимость,
    ошибка, согласие) лежат рядом свободными полями: их состав — дело бэкенда.
    """

    EVENT: ClassVar[str] = "phrase"
    RECEIVED: ClassVar[str] = "phrase_received"   # фраза пришла, модель ещё не отвечала: её видят ручки этого же запуска

    phrase: str
    status: str
    message: str = ""
    body: str = ""
    private: bool = False                 # ответ о личной переписке: в журнале — memo, сам ответ — в папке сеанса
    options: tuple[str, ...] = ()         # варианты ответа на вопрос — кнопками
    backend: str | None = None            # какой бэкенд ответил; None — журнал этого не знает
    without_model: bool = False           # ответ собрал код (кнопка, «да»), модели не было
    turns: int = 0
    ms: int = 0
    cost_usd: float = 0.0

    def details(self, extra: Mapping[str, object] = MappingProxyType({})) -> dict[str, object]:
        """Поля записи для журнала; `extra` — сведения о запросе. Пустые поля не пишутся — журнал короче."""
        own: dict[str, object] = {"phrase": self.phrase, "status": self.status, "message": self.message}
        optional: dict[str, object] = {
            "body": self.body, "private": self.private, "options": list(self.options), "without_model": self.without_model,
        }
        return {**extra, **own, **{name: value for name, value in optional.items() if value}, "ms": self.ms}

    @classmethod
    def of(cls, entry: JournalEntry) -> PhraseRecord | None:
        """Запись журнала → запись фразы; не фраза — None."""
        if entry.event != cls.EVENT:
            return None
        details = entry.details
        options = details.get("options")
        backend = details.get("backend")
        return cls(
            phrase=_text(details, "phrase"), status=_text(details, "status"), message=_text(details, "message"),
            body=_text(details, "body"), private=details.get("private") is True,
            options=tuple(str(option) for option in options) if isinstance(options, list) else (),
            backend=backend if isinstance(backend, str) else None, without_model=details.get("without_model") is True,
            turns=_number(details, "num_turns", int), ms=_number(details, "ms", int), cost_usd=_number(details, "total_cost_usd", float),
        )

    def veiled(self, message: str) -> PhraseRecord:
        """Та же запись без текста ответа — для модели, когда ответ пересказывал переписку."""
        return replace(self, message=message, body="")


def _text(details: Mapping[str, object], name: str) -> str:
    value = details.get(name)
    return value if isinstance(value, str) else ""


def _number[NumberT: (int, float)](details: Mapping[str, object], name: str, kind: type[NumberT]) -> NumberT:
    value = details.get(name)
    return kind(value) if isinstance(value, int | float) and not isinstance(value, bool) else kind(0)
