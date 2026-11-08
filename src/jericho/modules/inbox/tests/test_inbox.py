import argparse
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from pydantic import ValidationError

from jericho.core.agent.consent import AnswerWithoutModel, PhraseConsent
from jericho.core.agent.entities import AgentReply, ReplyStatus
from jericho.core.agent.handle_phrase import HandlePhrase
from jericho.core.checks.base import Project
from jericho.core.conf.settings import AgentSettings, Settings
from jericho.core.modules.config import ModuleServices
from jericho.core.services.confirmation import ConfirmationGate
from jericho.core.services.mailbox import Mailbox, MailboxError
from jericho.core.services.own_paths import OwnPaths
from jericho.core.services.process_tree import ProcessTree
from jericho.core.skills.registry import InstalledSkills
from jericho.core.testing import Confirmations, FakeBackend, builder
from jericho.core.tools.result import ToolResult
from jericho.modules.inbox.adapters.process import ProcessAnswerer
from jericho.modules.inbox.checks import SubscriptionIsNotShared
from jericho.modules.inbox.command import AnswerCommand, InboxCommand
from jericho.modules.inbox.entities import Request
from jericho.modules.inbox.module import InboxModule
from jericho.modules.inbox.reception import Reception
from jericho.modules.inbox.settings import InboxSettings

OWNER = "1001"


def request(text: str = "что с сервером?", user: object = OWNER, **extra: object) -> dict[str, object]:
    return {"id": "r1", "user": user, "chat": "c1", "text": text, **extra}


class Answerer:
    """Подмена процесса поручения: запоминает, кто и что спросил, и отвечает в ящик ответов сам — как настоящий."""

    def __init__(self, outbox: Mailbox, succeeds: bool = True) -> None:
        self.asked: list[tuple[str, str]] = []
        self._outbox = outbox
        self._succeeds = succeeds

    def prepare(self, users: object) -> None:
        self.prepared = True

    def close(self) -> None:
        self.closed = True

    def answer(self, user: str, request: Path) -> bool:
        parsed = Request.parse(Mailbox.read(request))
        self.asked.append((user, parsed.text))
        if self._succeeds:
            self._outbox.post(parsed.reply(AgentReply(ReplyStatus.DONE, "всё в порядке")))
        return self._succeeds


@pytest.fixture
def boxes(tmp_path: Path) -> tuple[Mailbox, Mailbox]:
    return Mailbox(tmp_path / "inbox"), Mailbox(tmp_path / "outbox")


def reception(boxes: tuple[Mailbox, Mailbox], answerer: Answerer, max_text: int = 4000) -> Reception:
    inbox, outbox = boxes
    return Reception(inbox, outbox, answerer, {OWNER: "владелец"}, max_text)


def sent(box: Mailbox) -> list[dict[str, object]]:
    return [Mailbox.read(path) for path in box.waiting()]


class TestMailbox:
    def test_message_appears_whole_and_in_order(self, tmp_path: Path) -> None:
        box = Mailbox(tmp_path / "box")

        first, second = box.post({"n": 1}), box.post({"n": 2})

        assert box.waiting() == [first, second]
        assert [Mailbox.read(path) for path in box.waiting()] == [{"n": 1}, {"n": 2}]
        assert list((tmp_path / "box" / "tmp").iterdir()) == []

    def test_taken_once_then_done(self, tmp_path: Path) -> None:
        box = Mailbox(tmp_path / "box")
        message = box.post({"n": 1})

        taken = box.take(message)

        assert taken is not None and box.take(message) is None     # второй читатель его уже не получит
        assert box.waiting() == [] and box.taken() == [taken]
        Mailbox.done(taken)
        assert box.taken() == []

    def test_broken_message_is_an_error_not_a_crash(self, tmp_path: Path) -> None:
        broken = tmp_path / "1.json"
        broken.write_text("[1, 2]", encoding="utf-8")

        with pytest.raises(MailboxError, match="not a JSON object"):
            Mailbox.read(broken)


class TestRequest:
    def test_telegram_numbers_become_strings(self) -> None:
        assert Request.parse(request(user=1001, chat=-42)) == Request("r1", "1001", "-42", "что с сервером?")

    def test_button_says_which_question_it_answers(self) -> None:
        assert Request.parse(request("да", answers="q-1")).answers == "q-1"

    @pytest.mark.parametrize("broken", [{"user": None}, {"user": True}, {"text": 5}, {"id": ""}, {"answers": 7}])
    def test_wrong_fields_are_refused(self, broken: dict[str, object]) -> None:
        with pytest.raises(ValueError, match="request needs"):
            Request.parse({**request(), **broken})


class TestReception:
    def test_known_user_gets_an_answer(self, boxes: tuple[Mailbox, Mailbox]) -> None:
        inbox, outbox = boxes
        answerer = Answerer(outbox)
        inbox.post(request())

        assert reception(boxes, answerer).tick() == 1

        assert answerer.asked == [(OWNER, "что с сервером?")]
        assert sent(outbox) == [{"id": "r1", "user": OWNER, "chat": "c1", "status": "done", "title": "всё в порядке", "text": ""}]
        assert inbox.waiting() == [] and inbox.taken() == []

    def test_stranger_is_set_aside_without_an_answer(self, boxes: tuple[Mailbox, Mailbox]) -> None:
        """Транспорт уже сверил пользователя — но взломанный транспорт не должен получить ассистента."""
        inbox, outbox = boxes
        answerer = Answerer(outbox)
        inbox.post(request(user="666"))

        reception(boxes, answerer).tick()

        assert answerer.asked == [] and sent(outbox) == []
        assert [path.parent.name for path in (inbox.root / "rejected").iterdir()] == ["rejected"]

    def test_broken_message_is_set_aside(self, boxes: tuple[Mailbox, Mailbox]) -> None:
        inbox, outbox = boxes
        inbox.post({"text": "без отправителя"})

        reception(boxes, Answerer(outbox)).tick()

        assert sent(outbox) == [] and len(list((inbox.root / "rejected").iterdir())) == 1

    def test_failed_answer_still_tells_the_user(self, boxes: tuple[Mailbox, Mailbox]) -> None:
        inbox, outbox = boxes
        inbox.post(request())

        reception(boxes, Answerer(outbox, succeeds=False)).tick()

        assert [(message["status"], message["chat"]) for message in sent(outbox)] == [("failed", "c1")]

    def test_too_long_is_refused_before_the_model(self, boxes: tuple[Mailbox, Mailbox]) -> None:
        inbox, outbox = boxes
        answerer = Answerer(outbox)
        inbox.post(request("x" * 11))

        reception(boxes, answerer, max_text=10).tick()

        assert answerer.asked == [] and [message["status"] for message in sent(outbox)] == ["refused"]

    def test_interrupted_answer_is_reported_not_repeated(self, boxes: tuple[Mailbox, Mailbox]) -> None:
        """Взятое до перезапуска могло уже выполниться — повторять нельзя, сказать пользователю нужно."""
        inbox, outbox = boxes
        answerer = Answerer(outbox)
        inbox.take(inbox.post(request()))

        reception(boxes, answerer).recover()

        assert answerer.asked == [] and inbox.taken() == []
        assert [message["title"] for message in sent(outbox)] == [Reception.INTERRUPTED.message]


class TestCommands:
    def test_answer_runs_the_phrase_and_replies_to_its_chat(self, boxes: tuple[Mailbox, Mailbox], tmp_path: Path) -> None:
        _, outbox = boxes
        backend = FakeBackend({"status": "done", "message": "Нагрузка 0,3"})
        file = tmp_path / "request.json"
        file.write_text(json.dumps(request()), encoding="utf-8")

        AnswerCommand(HandlePhrase(builder(), backend), outbox, ConfirmationGate(Confirmations(), "run-1")).run(argparse.Namespace(request=file))

        assert backend.asked[0][1] == "что с сервером?"
        assert [(message["chat"], message["title"]) for message in sent(outbox)] == [("c1", "Нагрузка 0,3")]
        assert "confirm" not in sent(outbox)[0]

    def test_answer_that_waits_for_yes_says_so_for_the_buttons(self, boxes: tuple[Mailbox, Mailbox], tmp_path: Path) -> None:
        """Транспорт с кнопками покажет «Да» и «Нет», только когда вопрос правда ждёт ответа."""
        _, outbox = boxes
        confirmations = Confirmations()
        gate = ConfirmationGate(confirmations, "run-1")
        backend = FakeBackend({"status": "clarify", "message": "Перезапустить portfolio_backend?"})
        file = tmp_path / "request.json"
        file.write_text(json.dumps(request("перезапусти portfolio")), encoding="utf-8")
        gate.consent("restart_container", {"container": "portfolio_backend"}, "перезапустить portfolio_backend")

        AnswerCommand(HandlePhrase(builder(), backend), outbox, gate).run(argparse.Namespace(request=file))

        pending = confirmations.pending()
        assert pending is not None
        assert (sent(outbox)[0]["confirm"], sent(outbox)[0]["confirm_id"]) == ("перезапустить portfolio_backend", pending.id)

    def test_button_of_a_replaced_question_confirms_nothing(self, boxes: tuple[Mailbox, Mailbox], tmp_path: Path) -> None:
        """Кнопка «Да» под старым сообщением бота возвращает его `confirm_id` — новый вопрос она не подтвердит."""
        _, outbox = boxes
        confirmations = Confirmations()
        ConfirmationGate(confirmations, "run-1").consent("restart_container", {"container": "b"}, "перезапустить b")
        backend = FakeBackend({"status": "done", "message": "модель ответила"})
        file = tmp_path / "request.json"
        file.write_text(json.dumps(request("да", answers="old-question")), encoding="utf-8")
        gate = ConfirmationGate(confirmations, "run-2")
        consent = AnswerWithoutModel(PhraseConsent(gate), lambda: ToolResult.success())

        AnswerCommand(HandlePhrase(builder(), backend, consent=consent), outbox, gate).run(argparse.Namespace(request=file))

        pending = confirmations.pending()
        assert sent(outbox)[0]["status"] == "refused" and backend.asked == []
        assert pending is not None and not pending.approved_by

    def test_inbox_stops_on_request(self, boxes: tuple[Mailbox, Mailbox]) -> None:
        inbox, outbox = boxes
        inbox.post(request())

        class Once(Reception):
            def tick(self) -> int:
                handled = super().tick()
                command.stop()
                return handled

        command = InboxCommand(Once(inbox, outbox, Answerer(outbox), {OWNER: "владелец"}, 4000), poll=0.01)
        command.run(argparse.Namespace())

        assert [message["status"] for message in sent(outbox)] == ["done"]


class TestSettings:
    def test_user_ids_must_fit_a_folder_name(self) -> None:
        with pytest.raises(ValidationError, match="inbox user ids"):
            InboxSettings(users={"../owner": "x"})


class TestProcessAnswerer:
    """Настоящие дочерние процессы: вместо ассистента — короткая программа на Python с тем же входом."""

    def answerer(self, script: str, timeout: float = 5.0) -> ProcessAnswerer:
        return ProcessAnswerer((sys.executable, "-c", script), {}, "JERICHO_USER", timeout)

    def test_ready_process_gets_the_request_and_a_new_one_waits(self, tmp_path: Path) -> None:
        """Сборка — до сообщения: запрос уходит уже собранному процессу, а следующий собирается про запас."""
        seen = tmp_path / "seen"
        script = (
            "import os, sys; line = sys.stdin.readline().strip(); "
            f"line and open({str(seen)!r}, 'a').write(os.environ['JERICHO_USER'] + ' ' + ' '.join(sys.argv[1:]) + ' ' + line + chr(10))"
        )
        answerer = self.answerer(script)
        answerer.prepare([OWNER])

        assert answerer.answer(OWNER, tmp_path / "r1.json") is True
        assert seen.read_text() == f"{OWNER} answer --wait {tmp_path / 'r1.json'}\n"
        assert answerer._ready[OWNER].poll() is None      # pyright: ignore[reportPrivateUsage] — следующий уже ждёт
        answerer.close()
        assert seen.read_text().count("\n") == 1           # закрытый stdin — «запросов не будет»: ждущий вышел молча

    def test_failure_and_timeout_are_false(self, tmp_path: Path) -> None:
        failing = self.answerer("import sys; sys.stdin.readline(); raise SystemExit(3)")
        slow = self.answerer("import sys, time; sys.stdin.readline().strip() and time.sleep(5)", timeout=0.3)

        assert failing.answer(OWNER, tmp_path / "r1.json") is False
        assert slow.answer(OWNER, tmp_path / "r1.json") is False
        failing.close()
        slow.close()

    def test_timeout_stops_what_the_answer_started(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Ревью 02.11.2026, сводка №10: по сроку останавливался только процесс ответа — сервер ручек и программы внутри
        ручек продолжали работать после «ответ не уложился»."""
        monkeypatch.setattr(ProcessTree, "GRACE", 0.2)
        pidfile = tmp_path / "pid"
        script = (
            "import subprocess, sys, time; sys.stdin.readline() or sys.exit(); "
            f"child = subprocess.Popen(['sh', '-c', \"trap '' TERM; exec sleep 30\"]); open({str(pidfile)!r}, 'w').write(str(child.pid)); "
            "time.sleep(30)"
        )
        slow = self.answerer(script, timeout=1.0)

        assert slow.answer(OWNER, tmp_path / "r1.json") is False
        slow.close()

        pid = int(pidfile.read_text())
        time.sleep(0.3)
        stat = Path(f"/proc/{pid}/stat")
        assert not stat.exists() or stat.read_text().rsplit(")", 1)[1].split()[0] == "Z"


class TestSubscriptionIsNotShared:
    """E016 (условия Anthropic, 27.10.2026): подписку Claude не делят с другими людьми."""

    def project(self, backend: str, users: dict[str, str], fallback: tuple[str, ...] = ()) -> Project:
        class Configured(Settings):
            inbox: InboxSettings = InboxSettings(directory=Path("/exchange"), users=users)

        settings = Configured(agent=AgentSettings(backend=backend, fallback_backends=fallback))
        return Project(Path("."), InstalledSkills([]), settings=settings)

    def test_several_people_on_a_subscription_is_an_error(self) -> None:
        messages = SubscriptionIsNotShared().run(self.project("jericho.backends.claude_cli", {"1": "владелец", "2": "гость"}))

        assert [message.code for message in messages] == ["jericho.E016"]

    def test_fallback_on_a_subscription_counts_too(self) -> None:
        project = self.project("jericho.backends.openai_api", {"1": "владелец", "2": "гость"}, fallback=("jericho.backends.claude_cli",))

        assert SubscriptionIsNotShared().run(project)

    def test_chatgpt_subscription_of_codex_counts_too(self) -> None:
        messages = SubscriptionIsNotShared().run(self.project("jericho.backends.codex_cli", {"1": "владелец", "2": "гость"}))

        assert len(messages) == 1 and "ChatGPT" in messages[0].text

    def test_owner_alone_or_a_key_is_fine(self) -> None:
        assert SubscriptionIsNotShared().run(self.project("jericho.backends.claude_cli", {"1": "владелец"})) == []
        assert SubscriptionIsNotShared().run(self.project("jericho.backends.openai_api", {"1": "владелец", "2": "гость"})) == []


class TestExchangeIsProtected:
    def test_the_exchange_folder_joins_the_assistants_own_files(self, tmp_path: Path) -> None:
        """Входящий файл — фраза пользователя: файловые ручки не пишут сюда, иначе подделали бы «да» (ревью 02.11.2026)."""
        own = OwnPaths()
        settings = SimpleNamespace(section=lambda name, section_class: InboxSettings(directory=tmp_path / "exchange"))
        services = SimpleNamespace(settings=settings, core=SimpleNamespace(own_paths=own))

        InboxModule().ready(cast(ModuleServices, services))

        assert list(own) == [tmp_path / "exchange"]
