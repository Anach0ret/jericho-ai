"""Что приносит поиск: короткие выдержки со ссылками — чужой текст."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


@dataclass(frozen=True, slots=True)
class SearchHit:
    title: str
    url: str
    snippet: str
    age: str = ""      # «2 hours ago», «13 Oct 2026» — как назвал поисковик; пусто — не назвал

    def to_dict(self) -> dict[str, str]:
        return {"title": self.title, "url": self.url, "snippet": self.snippet, **({"age": self.age} if self.age else {})}


class Freshness(StrEnum):
    ANY = "any"
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    YEAR = "year"
