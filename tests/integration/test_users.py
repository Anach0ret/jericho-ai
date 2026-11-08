"""Пользователь запуска (`JERICHO_USER`): у каждого своё «да» и свой разговор, журнал и долгие файлы — общие."""

import logging
from dataclasses import replace

import pytest

from jericho.core.assembly.installation import Installation, InstallationError
from jericho.core.assembly.state import State, build_state
from jericho.core.journal.adapters.jsonl import JsonLinesLogReader


def as_user(installation: Installation, user: str) -> Installation:
    return replace(installation, environment={**installation.environment, Installation.USER_VARIABLE: user})


def state(installation: Installation) -> State:
    return build_state(installation.settings(), installation)


class TestUsers:
    def test_session_folder_is_per_user_and_long_lived_files_are_shared(self, installation: Installation) -> None:
        owner, guest = state(as_user(installation, "1001")), state(as_user(installation, "2002"))

        assert owner.files.confirmation != guest.files.confirmation
        assert owner.files.confirmation.parent.name == "1001"
        assert owner.files.journal == guest.files.journal == state(installation).files.journal

    def test_files_of_the_assistant_cover_the_sessions_of_all_users(self, installation: Installation) -> None:
        """Файловые ручки одного пользователя не дотянутся до «да» и ответов другого (ревью 02.11.2026, П3a №2)."""
        owner, guest = state(as_user(installation, "1001")), state(as_user(installation, "2002"))
        own = list(owner.services.own_paths)

        assert any(guest.files.confirmation.is_relative_to(path) for path in own)
        assert owner.files.journal.parent in own and installation.config_dir in own

    def test_yes_of_one_user_does_not_confirm_the_question_of_another(self, installation: Installation) -> None:
        owner = state(as_user(installation, "1001"))
        owner.gate.consent("send", {"to": "x"}, "отправить x")

        guest = state(as_user(installation, "2002"))
        assert guest.gate.user_said_yes() is None and guest.confirmations.pending() is None

        owner_again = state(as_user(installation, "1001"))
        assert owner_again.gate.user_said_yes() is not None       # свой вопрос тот же пользователь подтверждает

    def test_journal_says_whose_phrase_it_was(self, installation: Installation) -> None:
        built = state(as_user(installation, "1001"))
        logging.getLogger("jericho.test").info("phrase", extra={"data": {"phrase": "привет"}})

        assert JsonLinesLogReader(built.files.journal).tail(1)[0].user == "1001"

    def test_tool_server_keeps_the_user(self, installation: Installation) -> None:
        assert as_user(installation, "1001").tool_server_environment("run-1")[Installation.USER_VARIABLE] == "1001"
        assert Installation.USER_VARIABLE not in installation.tool_server_environment("run-1")

    @pytest.mark.parametrize("user", ["../owner", "a b", "x" * 65])
    def test_user_that_would_escape_its_folder_is_refused(self, installation: Installation, user: str) -> None:
        with pytest.raises(InstallationError, match="JERICHO_USER"):
            state(as_user(installation, user))
