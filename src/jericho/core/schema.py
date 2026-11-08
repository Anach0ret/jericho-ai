"""JSON-схемы для модели: то, что `pydantic` строит по классу, без лишнего."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


def schema_for_model(model: type[BaseModel]) -> dict[str, Any]:
    """Схема класса для модели, без лишних знаков.

    Убираются заголовки, которые `pydantic` добавляет каждому полю, и описание самого класса: его docstring
    написан для разработчика, а не для модели. Описания полей остаются.
    """
    schema = _without_titles(model.model_json_schema())
    schema.pop("description", None)
    return schema


def _without_titles(node: Any) -> Any:
    if isinstance(node, list):
        return [_without_titles(item) for item in node]
    if not isinstance(node, dict):
        return node
    cleaned: dict[str, Any] = {}
    for key, value in node.items():
        if key == "title" and isinstance(value, str):
            continue
        # В `properties` ключи — имена полей, а не слова схемы: поле с именем `title` должно остаться.
        cleaned[key] = (
            {name: _without_titles(field) for name, field in value.items()}
            if key in ("properties", "$defs") and isinstance(value, dict)
            else _without_titles(value)
        )
    return cleaned
