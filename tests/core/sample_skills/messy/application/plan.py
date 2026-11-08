"""Сценарий навыка с pydantic внутри — нарушение E004."""

from pydantic import BaseModel


class Plan(BaseModel):
    steps: list[str]
