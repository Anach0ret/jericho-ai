from datetime import datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from jericho.core.agent.entities import AgentReply, ReplyStatus
from jericho.core.agent.forms import REPLY_FORMS, Brief, Report
from jericho.core.agent.handle_phrase import HandlePhrase
from jericho.core.conf.settings import AgentSettings, OutputSettings, Settings
from jericho.core.services.mailbox import Mailbox
from jericho.core.services.output import FileOutput, StdoutOutput, output_for
from jericho.core.testing import FakeBackend, builder


class TestReplyForms:
    def test_brief_is_a_status_and_one_line(self) -> None:
        assert Brief().parse({"status": "done", "message": "Открыл"}) == AgentReply(ReplyStatus.DONE, "Открыл")
        assert set(Brief().schema()["properties"]) == {"status", "message", "options"}

    def test_report_is_a_title_seen_at_once_and_a_text_behind_it(self) -> None:
        reply = Report().parse({"status": "done", "title": "Диск заполнен на 91 %", "text": "/var — 48 ГБ\n/home — 12 ГБ"})

        assert reply == AgentReply(ReplyStatus.DONE, "Диск заполнен на 91 %", "/var — 48 ГБ\n/home — 12 ГБ")
        assert set(Report().schema()["properties"]) == {"status", "title", "text", "options"}

    def test_options_are_buttons_only_for_a_question(self) -> None:
        """Варианты ответа — кнопками у вопроса; у «сделано» их быть не может: им некуда вести."""
        question = Brief().parse({"status": "clarify", "message": "Какой Саша?", "options": ["Петров", "Смирнов"]})
        done = Brief().parse({"status": "done", "message": "Готово", "options": ["лишнее"]})

        assert question.options == ("Петров", "Смирнов") and done.options == ()
        assert Report().parse({"status": "clarify", "title": "Какой?", "options": ["А", "Б"]}).options == ("А", "Б")

    @pytest.mark.parametrize("answer", [{"status": "done", "message": "строка вместо отчёта"}, {"status": "failed", "title": "x"}, None])
    def test_answer_not_by_the_chosen_form_is_refused(self, answer: dict[str, object] | None) -> None:
        with pytest.raises(ValidationError):
            Report().parse(answer)

    def test_form_is_chosen_in_the_settings_by_name(self) -> None:
        class Reporting(Settings):
            agent: AgentSettings = AgentSettings(reply_form="report")

        assert isinstance(REPLY_FORMS[Reporting().agent.reply_form](), Report)
        assert isinstance(REPLY_FORMS[Settings().agent.reply_form](), Brief)

    def test_scenario_asks_and_reads_in_the_chosen_form(self) -> None:
        fake = FakeBackend({"status": "done", "title": "Службы в порядке", "text": "nginx — работает"})

        reply = HandlePhrase(builder(), fake, form=Report()).execute("утренняя сводка")

        assert (reply.message, reply.body) == ("Службы в порядке", "nginx — работает")

    def test_answer_in_the_wrong_form_becomes_a_failure_not_a_crash(self) -> None:
        fake = FakeBackend({"status": "done", "message": "коротко"})

        assert HandlePhrase(builder(), fake, form=Report()).execute("сводка").status is ReplyStatus.FAILED


class TestOutputs:
    REPORT = AgentReply(ReplyStatus.DONE, "Диск заполнен на 91 %", "/var — 48 ГБ")

    def test_stdout_prints_the_line_and_then_the_details(self) -> None:
        printed: list[str] = []

        StdoutOutput(printed.append).deliver("сводка", self.REPORT)
        StdoutOutput(printed.append).deliver("открой ютуб", AgentReply(ReplyStatus.DONE, "Открыл YouTube"))

        assert printed == ["[done] Диск заполнен на 91 %", "/var — 48 ГБ", "[done] Открыл YouTube"]

    def test_file_collects_answers_one_after_another(self, tmp_path: Path) -> None:
        output = FileOutput(tmp_path / "reports" / "answers.md", now=lambda: datetime(2026, 10, 14, 7, 0))

        output.deliver("утренняя сводка", self.REPORT)
        output.deliver("проверь службы", AgentReply(ReplyStatus.REFUSED, "Нет доступа"))

        assert (tmp_path / "reports" / "answers.md").read_text(encoding="utf-8") == (
            "## 2026-10-14 07:00 · done · Диск заполнен на 91 %\nПоручение: утренняя сводка\n\n/var — 48 ГБ\n\n"
            "## 2026-10-14 07:00 · refused · Нет доступа\nПоручение: проверь службы\n\n"
        )

    def test_mailbox_posts_a_message_for_the_transport(self, tmp_path: Path) -> None:
        """Сводка или напоминание на сервере: бот заберёт сообщение и отдаст адресату."""
        box = Mailbox(tmp_path / "outbox")

        output_for(OutputSettings(kind="mailbox", mailbox=box.root), "server").deliver("сводка", AgentReply(ReplyStatus.DONE, "Всё в порядке", "диск 45 %"))

        [message] = [Mailbox.read(path) for path in box.waiting()]
        notice = message.pop("notice")
        assert message == {"to": "owner", "task": "сводка", "status": "done", "title": "Всё в порядке", "text": "диск 45 %"}
        assert isinstance(notice, str) and len(notice) == 32      # номер для квитанции транспорта
