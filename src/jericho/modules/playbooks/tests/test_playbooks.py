import argparse
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from jericho.core.modules.config import ModuleServices
from jericho.core.services.adapters.file_lock import FileLock
from jericho.core.services.adapters.memory_list import MemoryList
from jericho.core.services.confirmation import ConfirmationGate
from jericho.core.services.foreign import ForeignText
from jericho.core.testing import Confirmations, execute
from jericho.core.testing.fakes import fake_core
from jericho.core.tools.result import ToolResult
from jericho.modules.playbooks.adapters.json_file import JsonPlaybookStore
from jericho.modules.playbooks.command import PlaybooksCommand
from jericho.modules.playbooks.context import PlaybookList
from jericho.modules.playbooks.entities import Playbook
from jericho.modules.playbooks.module import PlaybooksModule
from jericho.modules.playbooks.shelf import PlaybookLimit, PlaybookShelf
from jericho.modules.playbooks.tools import RemovePlaybook, ShowPlaybook, SuggestPlaybook, WritePlaybook

NOON = datetime(2026, 10, 29, 12, 0)
QUIZ = {
    "title": "Пройти тест в Moodle",
    "site": "lms.example.org",
    "text": "1. «Пройти тест». 2. Ответы — choice. 3. «Закончить попытку…» → «Отправить всё и завершить тест».",
}


def shelf(store: MemoryList[Playbook] | JsonPlaybookStore | None = None, limit: int = 20) -> PlaybookShelf:
    return PlaybookShelf(store or MemoryList[Playbook](), lambda: NOON, limit=limit)


def written() -> tuple[PlaybookShelf, str]:
    playbooks = shelf()
    return playbooks, playbooks.write(QUIZ["title"], QUIZ["site"], QUIZ["text"]).id


def write(playbooks: PlaybookShelf, foreign: ForeignText | None = None, **request: object) -> ToolResult:
    gate = ConfirmationGate(Confirmations(), "run-1")
    return execute(WritePlaybook(playbooks, gate, foreign or ForeignText()), {**QUIZ, **request})


def command(playbooks: PlaybookShelf, **args: str | None) -> None:
    PlaybooksCommand(playbooks).run(argparse.Namespace(**{"accept": None, "reject": None, "remove": None, **args}))


class TestWrite:
    def test_what_the_person_dictates_is_written_at_once(self) -> None:
        playbooks = shelf()

        result = write(playbooks)

        assert result.ok and [playbook.text for playbook in playbooks.all()] == [QUIZ["text"]]

    def test_after_reading_a_page_it_is_written_only_after_yes(self) -> None:
        """Чужой текст со страницы не становится долгой подсказкой без человека."""
        playbooks, foreign = shelf(), ForeignText()
        foreign.read_from("lms.example.org")

        result = write(playbooks, foreign)

        assert result.error == "needs_confirm" and playbooks.all() == []

    def test_correction_may_be_appended_without_losing_the_rest(self) -> None:
        playbooks, playbook_id = written()

        write(playbooks, playbook=playbook_id, append=True, text="4. Окно «Вы уверены?» — та же кнопка в окне.")

        playbook = playbooks.find(playbook_id)
        assert playbook is not None and playbook.text == QUIZ["text"] + "\n4. Окно «Вы уверены?» — та же кнопка в окне."

    @pytest.mark.parametrize("site", ["https://lms.example.org", "lms.example.org/course", "ЛМС курса"])
    def test_site_is_a_bare_address(self, site: str) -> None:
        assert write(shelf(), site=site).error == "invalid_parameters"

    def test_shelf_has_a_limit(self) -> None:
        playbooks = shelf(limit=1)
        write(playbooks)

        assert write(playbooks).error == "playbooks_full"


class TestRead:
    def test_model_reads_the_playbook_and_the_window_sees_when(self) -> None:
        playbooks, playbook_id = written()

        result = execute(ShowPlaybook(playbooks), {"playbook": playbook_id})

        playbook = playbooks.find(playbook_id)
        assert result.data["playbook"]["text"] == QUIZ["text"]  # pyright: ignore[reportIndexIssue]
        assert playbook is not None and playbook.used == NOON

    def test_prompt_lists_titles_and_sites_only(self) -> None:
        playbooks, playbook_id = written()

        assert PlaybookList(playbooks).values() == {"playbooks": f"- «Пройти тест в Moodle» (id {playbook_id}) — lms.example.org"}

    def test_without_playbooks_the_prompt_says_so(self) -> None:
        assert PlaybookList(shelf()).values() == {"playbooks": "Памяток нет."}


class TestSuggest:
    def test_suggestion_waits_for_the_person_and_is_appended_on_accept(self) -> None:
        playbooks, playbook_id = written()

        result = execute(SuggestPlaybook(playbooks), {
            "playbook": playbook_id, "text": "Кнопка внизу — «Закончить попытку…», не «Завершить».", "reason": "не нашёл «Завершить»",
        })

        playbook = playbooks.find(playbook_id)
        assert result.ok and playbook is not None and playbook.text == QUIZ["text"]       # до «Принять» не меняется
        command(playbooks, accept=str(result.data["suggested"]))
        accepted = playbooks.find(playbook_id)
        assert accepted is not None and accepted.text.endswith("\nКнопка внизу — «Закончить попытку…», не «Завершить».")
        assert accepted.suggestions == ()

    def test_new_playbook_suggested_by_the_model_is_hidden_until_accepted(self) -> None:
        playbooks = shelf()

        result = execute(SuggestPlaybook(playbooks), {"title": "Разобрать входящие", "text": "Открыть «Входящие», по одному…", "reason": "делал без памятки"})

        assert result.ok and PlaybookList(playbooks).values() == {"playbooks": "Памяток нет."}
        assert execute(ShowPlaybook(playbooks), {"playbook": str(result.data["playbook"])}).error == "playbook_not_found"

    def test_rejected_new_playbook_is_gone(self) -> None:
        playbooks = shelf()
        result = execute(SuggestPlaybook(playbooks), {"title": "Разобрать входящие", "text": "Открыть «Входящие», по одному…", "reason": "делал без памятки"})

        command(playbooks, reject=str(result.data["suggested"]))

        assert playbooks.all() == []

    def test_new_playbook_needs_a_title(self) -> None:
        result = execute(SuggestPlaybook(shelf()), {"text": "Открыть «Входящие», по одному…", "reason": "делал без памятки"})

        assert result.error == "title_required"

    def test_accept_that_would_overflow_the_playbook_is_refused(self) -> None:
        playbooks = PlaybookShelf(MemoryList[Playbook](), lambda: NOON, text_limit=120)
        playbook = playbooks.write(QUIZ["title"], QUIZ["site"], QUIZ["text"])
        suggested = playbooks.suggest("ещё строка, которой уже не хватит места", "причина", playbook.id)

        with pytest.raises(PlaybookLimit):
            playbooks.accept(suggested.suggestions[-1].id)


class TestRemoveAndKeep:
    def test_model_removes_on_request(self) -> None:
        playbooks, playbook_id = written()

        result = execute(RemovePlaybook(playbooks), {"playbook": playbook_id})

        assert (result.data["removed"], playbooks.all()) == ("Пройти тест в Moodle", [])

    def test_person_removes_from_the_window(self, capsys: pytest.CaptureFixture[str]) -> None:
        playbooks, playbook_id = written()

        command(playbooks, remove=playbook_id)

        assert playbooks.all() == [] and "Убрана памятка" in capsys.readouterr().out

    def test_playbooks_survive_between_processes(self, tmp_path: Path) -> None:
        file = tmp_path / "playbooks.json"
        first = shelf(JsonPlaybookStore(file))
        playbook = first.write(QUIZ["title"], QUIZ["site"], QUIZ["text"])
        first.suggest("строка", "причина", playbook.id)

        assert shelf(JsonPlaybookStore(file)).all() == first.all()


class TestTwoProcesses:
    def test_marking_an_old_object_used_keeps_what_was_accepted_meanwhile(self, tmp_path: Path) -> None:
        """Памятку прочли → в окне приняли дополнение → `mark_used` старого объекта возвращал старый текст и
        непринятое предложение (ревью 02.11.2026, П3a №8)."""
        store = JsonPlaybookStore(tmp_path / "playbooks.json")
        written = shelf(store).write("Moodle", "moodle.example", "Вход по кнопке «Войти».")
        suggested = shelf(store).suggest("Кнопка внизу — «Закончить попытку».", "нашёл сам", written.id)
        read_earlier = shelf(store).find(written.id)
        assert read_earlier is not None

        shelf(store).accept(suggested.suggestions[0].id)       # окно на панели
        shelf(store).mark_used(read_earlier)                  # фраза — со старым объектом

        kept = shelf(store).find(written.id)
        assert kept is not None and kept.text.endswith("«Закончить попытку».") and kept.suggestions == () and kept.used == NOON


class TestLockThroughTheModule:
    """Ревью 07.11.2026, рекомендация: замок должен стоять в собранном модуле, а не только в тесте полки."""

    def test_assembled_shelf_waits_for_the_lock(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(PlaybooksModule, "LOCK_WAIT", 0.05)
        core = fake_core(tmp_path, dry_run=False)
        module = PlaybooksModule()
        module.ready(cast(ModuleServices, SimpleNamespace(core=core)))
        write = next(tool for tool in module.tools() if tool.name == "playbook_write")
        held = FileLock(core.paths.state_dir / PlaybooksModule.LOCK)
        assert held.acquire()
        try:
            result = execute(write, {"title": "Пройти тест", "site": "moodle.org", "text": "Открыть курс, затем тест."})
        finally:
            held.release()

        assert result.error == "state_busy"
