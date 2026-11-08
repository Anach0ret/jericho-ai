import json
from datetime import datetime
from pathlib import Path
from typing import ClassVar

import pytest

from jericho.core.agent.model_choice import ModelChoiceFile, ModelChoices
from jericho.core.conf.settings import Settings
from jericho.core.interfaces.cli.model_command import ModelCommand
from jericho.core.interfaces.cli.status_command import StatusCommand
from jericho.core.journal.entities import JournalEntry
from jericho.core.journal.reply_vault import ReplyVault
from jericho.core.modules.config import ModuleConfig
from jericho.core.modules.registry import InstalledModules
from jericho.core.services.confirmation import ConfirmationGate, PendingConfirmation
from jericho.core.testing import Confirmations

AT = datetime(2026, 10, 23, 15, 36)


class Journal:
    def __init__(self, *entries: JournalEntry) -> None:
        self._entries = list(entries)

    def tail(self, limit: int) -> list[JournalEntry]:
        return self._entries[-limit:]


class Voice(ModuleConfig):
    name: ClassVar[str] = "voice"

    def status(self) -> dict[str, object]:
        return {"state": "idle"}


class Quiet(ModuleConfig):
    name: ClassVar[str] = "notes"


def phrase(text: str, message: str, **details: object) -> JournalEntry:
    return JournalEntry(AT, "phrase", details={"phrase": text, "status": "done", "message": message, **details})


def command(
    journal: Journal, pending: PendingConfirmation | None = None, tmp: Path = Path("/nonexistent"), service: frozenset[str] = frozenset(),
    vault: ReplyVault | None = None,
) -> StatusCommand:
    modules = InstalledModules([("jericho.modules.voice", Voice()), ("jericho.modules.notes", Quiet())])
    model = ModelCommand(ModelChoices(Settings(), str), ModelChoiceFile(tmp / "model.json"))      # выбора моделей нет
    return StatusCommand("home", ConfirmationGate(Confirmations(pending), "run-2"), journal, modules, model, service, vault)


class TestStatusCommand:
    def test_conversation_comes_from_the_journal_in_order(self) -> None:
        journal = Journal(
            phrase("открой ютуб", "Открыл YouTube", backend="claude_cli"),
            JournalEntry(AT, "tool", details={"tool": "open_url"}),
            phrase("да", "Удалил файл", without_model=True),
        )

        snapshot = command(journal).snapshot()

        assert [(item["phrase"], item["model"]) for item in snapshot["conversation"]] == [("открой ютуб", "claude_cli"), ("да", "")]
        assert snapshot["model"] == ""

    def test_waiting_question_and_module_parts(self) -> None:
        pending = PendingConfirmation("delete", {}, "удалить «проба.txt» в корзину", AT, "run-1")

        snapshot = command(Journal(), pending).snapshot()

        assert snapshot["question"] == "удалить «проба.txt» в корзину"
        assert snapshot["modules"] == {"voice": {"state": "idle"}}       # модулю без данных места нет
        assert snapshot["conversation"] == [] and snapshot["model"] is None
        assert snapshot["models"] == {"choices": [], "current": None, "default": None, "chosen": False}

    def test_script_runs_show_up_as_exchanges(self) -> None:
        journal = Journal(JournalEntry(AT, "script", details={"script": "work", "title": "Рабочее место", "ok": False, "summary": "Не до конца"}))

        (item,) = command(journal).snapshot()["conversation"]

        assert (item["phrase"], item["status"], item["message"], item["model"]) == ("▶ Рабочее место", "failed", "Не до конца", "")

    def test_actions_are_tool_calls_without_service_ones(self) -> None:
        journal = Journal(
            JournalEntry(AT, "tool", details={"tool": "load_skill", "params": {"names": ["browser"]}, "result": {"ok": True}}),
            JournalEntry(AT, "tool", details={"tool": "open_url", "params": {"url": "https://example.org/" + "x" * 100}, "result": {"ok": True}}),
            JournalEntry(AT, "tool", details={"tool": "close_windows", "params": {}, "result": {"ok": False, "error": "needs_confirm"}}),
        )

        actions = command(journal, service=frozenset({"load_skill"})).snapshot()["actions"]

        assert [(a["tool"], a["ok"], a["error"]) for a in actions] == [("open_url", True, ""), ("close_windows", False, "needs_confirm")]
        assert len(actions[0]["params"]) == StatusCommand.PARAMS and actions[0]["params"].endswith("…")

    def test_only_the_last_phrases(self) -> None:
        journal = Journal(*(phrase(f"фраза {n}", "ок") for n in range(15)))

        conversation = command(journal).snapshot()["conversation"]

        assert len(conversation) == StatusCommand.PHRASES and conversation[-1]["phrase"] == "фраза 14"

    def test_prints_json(self, capsys: pytest.CaptureFixture[str]) -> None:
        command(Journal(phrase("привет", "Привет!"))).run(None)  # type: ignore[arg-type]

        assert json.loads(capsys.readouterr().out)["conversation"][0]["message"] == "Привет!"
