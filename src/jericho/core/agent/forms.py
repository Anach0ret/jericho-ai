"""Форма ответа: что модель обязана вернуть и как это становится ответом ассистента.

Форму выбирает проект (`agent.reply_form`): личному ассистенту нужна строка для уведомления, ассистенту,
который готовит сводки, — заголовок и текст. Раздел промпта о формате проект называет в `PROMPT_SECTIONS`
под стать выбранной форме: `sections/format.md` для короткой, `sections/format_report.md` для отчёта.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from jericho.core.agent.entities import AgentReply, ReplyStatus
from jericho.core.agent.model_reply import ModelReply
from jericho.core.schema import schema_for_model


class ReplyForm(Protocol):
    def schema(self) -> dict[str, Any]:
        """Схема, которой модель обязана следовать (структурированный вывод)."""
        ...

    def parse(self, structured: Mapping[str, object] | None) -> AgentReply:
        """Ответ модели → ответ ассистента. Не по форме — `ValueError`."""
        ...


class Brief:
    """Короткая форма: статус и одна строка."""

    def schema(self) -> dict[str, Any]:
        return ModelReply.json_schema()

    def parse(self, structured: Mapping[str, object] | None) -> AgentReply:
        return ModelReply.model_validate(structured).to_reply()


class ModelReport(BaseModel):
    """То, что модель возвращает в форме «отчёт». Статуса `failed` здесь нет: его ставит только сам Jericho."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["done", "clarify", "refused", "ignored"]
    title: str = Field(description="Суть одной строкой: что сделано или что выяснилось.")
    text: str = Field(default="", description="Сам отчёт: факты, числа, списки. Пусто, если добавить нечего.")
    options: list[Annotated[str, StringConstraints(min_length=1, max_length=40)]] = Field(
        default_factory=list, max_length=4, description="Варианты ответа на вопрос clarify — станут кнопками. Без вопроса — пусто."
    )


class Report:
    """Отчёт: статус, заголовок и текст. Заголовок видно сразу, текст идёт туда, куда проект отдаёт ответы."""

    def schema(self) -> dict[str, Any]:
        return schema_for_model(ModelReport)

    def parse(self, structured: Mapping[str, object] | None) -> AgentReply:
        report = ModelReport.model_validate(structured)
        options = tuple(report.options) if report.status == "clarify" else ()
        return AgentReply(ReplyStatus(report.status), report.title, report.text, options=options)


REPLY_FORMS: Mapping[str, type[ReplyForm]] = {"brief": Brief, "report": Report}
