"""Виды заметок, одни на все навыки: что модели разрешено запомнить и чему обязано соответствовать значение."""

from __future__ import annotations

from jericho.modules.notes.entities import NoteKind

ADDRESS = NoteKind(
    name="address",
    description="как пользователь называет сайт или страницу → её адрес.",
    pattern=r"https://\S{1,190}",
    example="«сайт курса» → https://lms.example.org/login",
)
IDENTIFIER = NoteKind(
    name="identifier",
    description=(
        "прозвище или искажённое распознаванием название → точное имя из списков руководства: приложение, "
        "проект, канал."
    ),
    pattern=r"[A-Za-z0-9._-]{1,80}",
    example="«телега» → telegram-desktop_telegram-desktop",
)
LABEL = NoteKind(
    name="label",
    description=(
        "что просят нажать или выбрать → настоящая надпись, если она звучит иначе или на другом языке. "
        "В имени назови и место: сайт, программу."
    ),
    pattern=r"[^\n\r]{1,60}",
    example="«войти на сайте курса» → Anmelden",
)

DEFAULT_KINDS = (ADDRESS, IDENTIFIER, LABEL)
