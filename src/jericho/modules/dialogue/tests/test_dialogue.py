import logging
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from jericho.core.agent.entities import AgentReply, ReplyStatus
from jericho.core.agent.forms import Report
from jericho.core.agent.handle_phrase import HandlePhrase
from jericho.core.journal.entities import JournalEntry
from jericho.core.services.foreign import ForeignText
from jericho.core.testing import FakeBackend, builder
from jericho.modules.dialogue.adapters.conversation_file import JsonFileConversationMemory
from jericho.modules.dialogue.context import RecentExchanges
from jericho.modules.dialogue.entities import Exchange
from jericho.modules.dialogue.task_layer import Conversation
from jericho.modules.dialogue.testing import NOON, Memory


class TestConversationInThePrompt:
    def test_recent_exchanges_are_shown_to_the_model(self) -> None:
        memory = Memory([Exchange(NOON, "открой проект бренд", ReplyStatus.CLARIFY, "Какой: lumere-brand или brand-voice-tg-bot?")])

        prompt = builder(contexts=[RecentExchanges(memory)]).build()

        assert "- пользователь: «открой проект бренд» → ты (clarify): «Какой: lumere-brand или brand-voice-tg-bot?»" in prompt

    def test_empty_memory_is_stated_explicitly(self) -> None:
        assert "Недавних реплик нет" in builder(contexts=[RecentExchanges(Memory())]).build()


class TestConversationLayer:
    @pytest.mark.parametrize(
        ("status", "remembered"),
        [("done", True), ("clarify", True), ("refused", True), ("ignored", False)],
    )
    def test_only_meaningful_exchanges_are_remembered(self, status: str, remembered: bool) -> None:
        memory = Memory()

        HandlePhrase(builder(), FakeBackend({"status": status, "message": "текст"}), [Conversation(memory)]).execute("фраза")

        assert [exchange.phrase for exchange in memory.exchanges] == (["фраза"] if remembered else [])

    def test_failure_is_not_remembered(self) -> None:
        memory = Memory()

        HandlePhrase(builder(), FakeBackend(error="boom"), [Conversation(memory)]).execute("фраза")

        assert memory.exchanges == []

    def test_answer_to_a_question_reaches_the_model_with_the_question(self) -> None:
        memory, fake = Memory(), FakeBackend({"status": "clarify", "message": "Какой проект?"})
        handle = HandlePhrase(builder(contexts=[RecentExchanges(memory)]), fake, [Conversation(memory)])

        handle.execute("открой проект бренд")
        handle.execute("второй")

        prompt_for_the_answer = fake.asked[1][0]
        assert "«открой проект бренд» → ты (clarify): «Какой проект?»" in prompt_for_the_answer

    def test_answer_to_a_question_goes_to_the_model_together_with_the_original_phrase(self) -> None:
        """Журнал 11.10.2026: «…на третьем» → вопрос → ответ; стол из первой фразы терялся."""
        memory, fake = Memory(), FakeBackend({"status": "clarify", "message": "Что открыть на столе 3?"})
        handle = HandlePhrase(builder(contexts=[RecentExchanges(memory)]), fake, [Conversation(memory)])

        handle.execute("открой перегрыз на третьем")
        handle.execute("портфолио")

        first, answer = fake.asked[0][1], fake.asked[1][1]
        assert first == "открой перегрыз на третьем"
        assert answer.startswith("портфолио\n\n[Перед этим шёл разговор:")
        assert "— пользователь: «открой перегрыз на третьем»\n— ты спросил: «Что открыть на столе 3?»" in answer

    def test_chain_of_questions_is_passed_whole(self) -> None:
        memory = Memory([
            Exchange(NOON, "открой проект", ReplyStatus.CLARIFY, "Какой проект?"),
            Exchange(NOON, "бренд", ReplyStatus.CLARIFY, "lumere-brand или brand-voice-tg-bot?"),
        ])
        fake = FakeBackend({"status": "done", "message": "Открыл"})

        HandlePhrase(builder(contexts=[RecentExchanges(memory)]), fake, [Conversation(memory)]).execute("второй")

        sent = fake.asked[0][1]
        assert sent.index("«открой проект»") < sent.index("«бренд»") < sent.index("brand-voice-tg-bot?")

    def test_long_phrase_after_a_finished_command_goes_as_it_is(self) -> None:
        memory = Memory([
            Exchange(NOON, "открой проект", ReplyStatus.CLARIFY, "Какой проект?"),
            Exchange(NOON, "портфолио", ReplyStatus.DONE, "Открыл portfolio"),
        ])
        fake = FakeBackend({"status": "done", "message": "Стол 2"})

        HandlePhrase(builder(contexts=[RecentExchanges(memory)]), fake, [Conversation(memory)]).execute("перейди на второй стол и открой там почту")

        assert fake.asked[0][1] == "перейди на второй стол и открой там почту"

    def test_short_phrase_after_a_reply_goes_with_that_reply(self) -> None:
        """Журнал 29.10.2026: «только первый вопрос» после отчёта о шаге — «вижу только эту фразу»."""
        memory = Memory([Exchange(NOON, "продолжай план", ReplyStatus.DONE, "Шаг 3 не вышел: ответы не отметились")])
        fake = FakeBackend({"status": "done", "message": "Понял"})

        HandlePhrase(builder(), fake, [Conversation(memory)]).execute("только первый вопрос")

        sent = fake.asked[0][1]
        assert sent.startswith("только первый вопрос\n\n[Перед этим: пользователь «продолжай план» → ты (done): «Шаг 3 не вышел")
        assert "явно другая команда — выполняй её" in sent

    def test_journal_and_memory_keep_the_phrase_as_the_user_said_it(self, caplog: pytest.LogCaptureFixture) -> None:
        memory = Memory([Exchange(NOON, "открой проект", ReplyStatus.CLARIFY, "Какой проект?")])
        fake = FakeBackend({"status": "done", "message": "Открыл portfolio"})

        with caplog.at_level(logging.INFO, logger="jericho"):
            HandlePhrase(builder(contexts=[RecentExchanges(memory)]), fake, [Conversation(memory)]).execute("портфолио")

        assert caplog.records[-1].data["phrase"] == "портфолио"  # pyright: ignore[reportAttributeAccessIssue]
        assert memory.exchanges[-1].phrase == "портфолио"


class Clock:
    def __init__(self) -> None:
        self.now = NOON

    def __call__(self) -> datetime:
        return self.now


class TestJsonFileConversationMemory:
    def test_remembers_and_returns_in_order(self, tmp_path: Path) -> None:
        memory = JsonFileConversationMemory(tmp_path / "run" / "conversation.json", clock=Clock())

        memory.remember("открой проект бренд", AgentReply(ReplyStatus.CLARIFY, "Какой?"))
        memory.remember("второй", AgentReply(ReplyStatus.DONE, "Открыл"))

        assert [(e.phrase, e.status, e.message) for e in memory.recent()] == [
            ("открой проект бренд", ReplyStatus.CLARIFY, "Какой?"),
            ("второй", ReplyStatus.DONE, "Открыл"),
        ]

    def test_forgets_after_two_minutes(self, tmp_path: Path) -> None:
        clock = Clock()
        memory = JsonFileConversationMemory(tmp_path / "conversation.json", clock=clock)
        memory.remember("открой проект бренд", AgentReply(ReplyStatus.CLARIFY, "Какой?"))

        clock.now += timedelta(seconds=119)
        assert len(memory.recent()) == 1
        clock.now += timedelta(seconds=2)
        assert memory.recent() == ()

    def test_keeps_only_the_latest_three(self, tmp_path: Path) -> None:
        memory = JsonFileConversationMemory(tmp_path / "conversation.json", clock=Clock())
        for number in range(5):
            memory.remember(f"фраза {number}", AgentReply(ReplyStatus.DONE, "ок"))

        assert [e.phrase for e in memory.recent()] == ["фраза 2", "фраза 3", "фраза 4"]

    def test_broken_file_means_no_conversation(self, tmp_path: Path) -> None:
        file = tmp_path / "conversation.json"
        file.write_text("{не json", encoding="utf-8")

        assert JsonFileConversationMemory(file).recent() == ()
        assert not file.exists()      # испорченный файл отложен в сторону, а не оставлен под следующую запись


class TestForeignTextTravelsWithTheConversation:
    """Прошлый ответ мог пересказать чужую страницу: пометка «был чужой текст» едет вместе с ним (ревью R06)."""

    def test_sources_read_in_the_phrase_are_remembered_with_the_answer(self) -> None:
        memory = Memory()

        HandlePhrase(builder(), FakeBackend({"status": "done", "message": "ок"}), [Conversation(memory, lambda: ("evil.example",))]).execute("прочти")

        assert memory.exchanges[0].foreign == ("evil.example",)

    def test_sources_of_this_run_are_found_in_the_journal(self) -> None:
        from jericho.modules.dialogue.foreign import ForeignReadInRun

        entries = [
            JournalEntry(NOON, "foreign", "INFO", "jericho", {"source": "evil.example"}, run="mine"),
            JournalEntry(NOON, "foreign", "INFO", "jericho", {"source": "other.example"}, run="someone-else"),
            JournalEntry(NOON, "tool", "INFO", "jericho", {"tool": "page_read"}, run="mine"),
        ]

        class Journal:
            def tail(self, limit: int) -> list[JournalEntry]:
                return entries

        assert ForeignReadInRun(Journal(), "mine", ForeignText())() == ("evil.example",)

    def test_the_mark_outlives_the_exchange_it_came_from(self, tmp_path: Path) -> None:
        """Пять фраз подряд, чужой текст — только в первой. Разговор помнит три обмена, но пометка не теряется на пятой:
        каждый ответ запоминается с унаследованными источниками (ревью 02.11.2026, П2 №3, П3b №2)."""
        from jericho.modules.dialogue.foreign import ForeignReadInRun

        memory = JsonFileConversationMemory(tmp_path / "conversation.json")
        seen: list[frozenset[str]] = []
        for run in range(1, 6):
            foreign = ForeignText()        # каждая фраза — новый процесс
            for exchange in memory.recent():
                for source in exchange.foreign:
                    foreign.restore(source)
            seen.append(foreign.sources)
            read = [JournalEntry(NOON, "foreign", "INFO", "jericho", {"source": "evil.example"}, run="r1")] if run == 1 else []

            class Journal:
                def tail(self, limit: int, read: list[JournalEntry] = read) -> list[JournalEntry]:
                    return read

            layer = Conversation(memory, ForeignReadInRun(Journal(), f"r{run}", foreign))
            HandlePhrase(builder(), FakeBackend({"status": "done", "message": "пересказ"}), [layer]).execute(f"дальше {run}")

        assert seen == [frozenset(), *[frozenset({"evil.example"})] * 4]
        assert all(exchange.foreign == ("evil.example",) for exchange in memory.recent())

    def test_next_phrase_starts_with_the_sources_of_the_shown_answers(self, tmp_path: Path) -> None:
        from jericho.core.services.confirmation import ConfirmationGate
        from jericho.core.services.core_services import CoreServices
        from jericho.core.services.foreign import ForeignText
        from jericho.core.services.paths import Paths
        from jericho.core.services.runner import DryRunRunner, SubprocessRunner
        from jericho.core.testing.fakes import Confirmations
        from jericho.modules.dialogue.module import DialogueModule

        paths = Paths(tmp_path / "state", tmp_path / "run")
        JsonFileConversationMemory(paths.runtime_dir / DialogueModule.FILE).remember(
            "прочти", AgentReply(ReplyStatus.DONE, "там написано…"), ("evil.example",)
        )
        foreign = ForeignText()
        core = CoreServices(DryRunRunner(SubprocessRunner()), ConfirmationGate(Confirmations(), "r"), paths, foreign=foreign)

        class Sections:
            @staticmethod
            def section[SectionT](name: str, section_class: type[SectionT]) -> SectionT:
                return section_class()

        class Services:
            journal = None
            run_id = "next"
            settings = Sections()

        Services.core = core  # pyright: ignore[reportAttributeAccessIssue]
        DialogueModule().ready(Services())  # pyright: ignore[reportArgumentType]

        assert foreign.sources == {"evil.example"}


class TestPrivateCorrespondenceIsNotRemembered:
    """Решение 23.10.2026: из чужой переписки разговор помнит, что сделано, а не текст."""

    def test_memo_is_remembered_instead_of_the_retelling(self) -> None:
        memory = Memory()
        reply: dict[str, object] = {"status": "done", "message": "Марина пишет: буду в 7, захвати ключи"}

        HandlePhrase(builder(), FakeBackend(reply), [Conversation(memory, private=lambda: ("прочитал чат с Мариной: 2 сообщения",))]).execute("что пишет Марина")

        assert memory.exchanges[0].message == "прочитал чат с Мариной: 2 сообщения (полный текст ответа — ручка last_reply)"
        assert "буду в 7" not in memory.exchanges[0].message

    def test_full_private_reply_comes_back_only_through_a_private_tool(self, tmp_path: Path) -> None:
        """«Отправь» после предложенного ответа: модель берёт текст ручкой last_reply — она личная, Gemini откажут."""
        from jericho.core.agent.entities import AgentReply, ReplyStatus
        from jericho.core.journal.reply_vault import ReplyVault
        from jericho.core.services.adapters.json_file import JsonStateFile
        from jericho.core.testing import execute
        from jericho.modules.dialogue.tools import LastReply

        vault = ReplyVault(JsonStateFile(tmp_path / ReplyVault.FILE))
        assert execute(LastReply(vault), {}).error == "no_reply"
        vault.keep("run-1", AgentReply(ReplyStatus.DONE, "Марина пишет: буду в 7"))
        vault.keep("run-2", AgentReply(ReplyStatus.CLARIFY, "Ответить Олегу: «Понимаю, Олег)»?"))

        result = execute(LastReply(vault), {})

        assert result.data["text"] == "Ответить Олегу: «Понимаю, Олег)»?" and LastReply.private == ("text",)

    def test_memos_of_this_run_are_found_in_the_journal(self) -> None:
        from jericho.core.journal.entities import JournalEntry
        from jericho.core.journal.private_run import PrivateRun

        entries = [
            JournalEntry(NOON, "tool", "INFO", "jericho", {"tool": "tg_recent", "private": True, "result": {"ok": True, "memo": "прочитал чат с Мариной"}}, run="mine"),
            JournalEntry(NOON, "tool", "INFO", "jericho", {"tool": "tg_recent", "private": True, "result": {"ok": True}}, run="mine"),
            JournalEntry(NOON, "tool", "INFO", "jericho", {"tool": "tg_recent", "private": True, "result": {"ok": True, "memo": "чужое"}}, run="other"),
            JournalEntry(NOON, "tool", "INFO", "jericho", {"tool": "open_url", "result": {"ok": True, "memo": "не личное"}}, run="mine"),
        ]

        class Journal:
            def tail(self, limit: int) -> list[JournalEntry]:
                return entries

        assert PrivateRun(Journal(), "mine")() == ("прочитал чат с Мариной", PrivateRun.TOUCHED)


class TestReportBodyIsRemembered:
    def test_details_of_a_report_reach_the_next_phrase(self) -> None:
        """Журнал 02.11.2026: на «что из этого уже есть?» модель видела только заголовок отчёта, а не список мер."""
        memory = Memory()
        fake = FakeBackend({"status": "done", "title": "Способы защиты", "text": "1. Cloudflare\n2. fail2ban\n3. limit_req"})
        handle = HandlePhrase(builder(contexts=[RecentExchanges(memory)]), fake, [Conversation(memory)], form=Report())

        handle.execute("как снизить запросы ботов?")
        handle.execute("что из этого есть?")

        assert "Способы защиты — 1. Cloudflare 2. fail2ban 3. limit_req" in fake.asked[1][1]

    def test_long_body_is_kept_shortened_and_survives_the_file(self, tmp_path: Path) -> None:
        memory = JsonFileConversationMemory(tmp_path / "conversation.json", clock=lambda: NOON)

        memory.remember("сводка", AgentReply(ReplyStatus.DONE, "Сводка", body="х" * 2000))

        body = memory.recent()[0].body
        assert len(body) == Exchange.BODY_LIMIT + 1 and body.endswith("…")
