from datetime import UTC, datetime, timedelta

import pytest

from jericho.core.agent.context import Now
from jericho.core.conf.settings import Settings
from jericho.core.prompting.template import render
from jericho.core.services.clock import Clock
from jericho.core.services.confirmation import PendingConfirmation
from jericho.core.testing import NOON, Confirmations, builder


class TestPromptBuilder:
    def test_prompt_lists_skills_but_does_not_carry_their_text(self) -> None:
        prompt = builder().build()

        assert "- **desktop** — рабочий стол" in prompt
        assert "НАВЫК" not in prompt and "{{" not in prompt

    def test_pending_confirmation_is_shown_to_the_model(self) -> None:
        pending = PendingConfirmation("close_windows", {"scope": "workspace"}, "закрыть 4 окон (стол 2)", NOON, "run-1")

        prompt = builder(confirmations=Confirmations(pending)).build()

        assert "**Ждёт подтверждения:** закрыть 4 окон (стол 2). Ответ «да» → вызови `confirm()`." in prompt


class TestNow:
    def test_model_is_told_the_day_the_date_and_the_time(self) -> None:
        """Своих часов у модели нет: без этого «сегодня» она угадывает по найденным страницам."""
        clock = Clock("Europe/Berlin", system=lambda: datetime(2026, 10, 13, 20, 12, tzinfo=UTC))

        assert Now(clock).values() == {"now": "вторник, 13 октября 2026 года, 22:12 (UTC+02:00)"}

    def test_time_is_told_in_the_zone_named_in_the_settings(self) -> None:
        """На сервере часы идут по UTC: без пояса «сегодня» сменилось бы не тогда, когда у пользователя."""
        midnight_utc = datetime(2026, 10, 13, 23, 30, tzinfo=UTC)

        assert Now(Clock("Europe/Berlin", system=lambda: midnight_utc)).values() == {"now": "среда, 14 октября 2026 года, 01:30 (UTC+02:00)"}
        assert Clock("Europe/Berlin", system=lambda: midnight_utc).now().utcoffset() == timedelta(hours=2)

    def test_framework_prompt_tells_the_time_to_every_skill(self) -> None:
        """Время — в разделе каркаса, а не в разделе поиска: «актуальная лекция» нужна и браузеру (журнал 21.10.2026)."""
        from jericho.core.prompting.adapters.markdown_files import MarkdownPromptSource, section_file

        core = MarkdownPromptSource([section_file(reference) for reference in Settings().PROMPT_SECTIONS], []).core()

        assert "**Сейчас вторник, 13 октября 2026 года, 22:12.**" in render(core, {"now": "вторник, 13 октября 2026 года, 22:12"})

    def test_unknown_zone_is_an_error_in_the_settings(self) -> None:
        with pytest.raises(ValueError, match="timezone: no such time zone 'Europe/Nowhere'"):
            Settings(timezone="Europe/Nowhere")


class TestTemplate:
    def test_known_names_are_filled_and_unknown_become_empty(self) -> None:
        assert render("Стол {{workspace}}{{unknown}}.", {"workspace": "3"}) == "Стол 3."
