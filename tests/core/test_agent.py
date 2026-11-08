import logging
from dataclasses import replace
from pathlib import Path

import pytest

from jericho.core.agent.entities import AgentReply, BackendAnswer, ReplyStatus
from jericho.core.agent.handle_phrase import HandlePhrase
from jericho.core.agent.model_reply import ModelReply
from jericho.core.agent.protocols import ModelTimeout
from jericho.core.agent.task import Outcome, Task, TaskHandler
from jericho.core.agent.wording import RUSSIAN
from jericho.core.prompting.adapters.markdown_files import MarkdownPromptSource, PromptSectionError, section_file
from jericho.core.prompting.entities import Skill
from jericho.core.testing import FakeBackend, builder
from tests.core.sample_skills.notes.skill import NotesSkill


class TestMarkdownPromptSource:
    def test_strips_card_comment_and_reads_skill_text_from_its_folder(self, tmp_path: Path) -> None:
        (tmp_path / "role.md").write_text("<!--\nкарточка\n-->\n\n# РОЛЬ\nтекст\n", encoding="utf-8")
        (tmp_path / "format.md").write_text("# ФОРМАТ\nодна строка\n", encoding="utf-8")
        skill = NotesSkill()
        source = MarkdownPromptSource([tmp_path / "role.md", tmp_path / "format.md"], [skill])

        assert source.core() == "# РОЛЬ\nтекст\n\n# ФОРМАТ\nодна строка"      # разделы — в названном порядке, через пустую строку
        assert source.skill("notes") == Skill(
            "notes", "Заметки — записать мысль.", ("add_note", "find_note"), "# Навык\nправила"
        )


class TestPromptSections:
    def test_section_is_found_inside_the_package_that_owns_it(self) -> None:
        file = section_file("jericho.core.prompting:sections/format.md")

        assert file.name == "format.md" and file.read_text(encoding="utf-8").startswith("# ФОРМАТ ОТВЕТА")

    @pytest.mark.parametrize(("reference", "problem"), [
        ("jericho.core.prompting:sections/nothing.md", "no file"),
        ("nowhere:role.md", "must be 'package:path'"),
        ("sections/format.md", "must be 'package:path'"),
    ])
    def test_wrong_reference_is_named_with_what_is_wrong(self, reference: str, problem: str) -> None:
        with pytest.raises(PromptSectionError, match=problem):
            section_file(reference)

    def test_framework_alone_gives_a_prompt_without_anything_about_one_assistant(self) -> None:
        """Разделы по умолчанию — то, что каркас говорит модели сам: в них нет ни роли, ни голоса, ни заметок."""
        from jericho.core.conf.settings import Settings

        text = MarkdownPromptSource([section_file(reference) for reference in Settings().PROMPT_SECTIONS], []).core()

        assert [line for line in text.splitlines() if line.startswith("# ")] == [
            "# НАВЫКИ", "# ПОДТВЕРЖДЕНИЯ", "# EDGE CASES", "# ФОРМАТ ОТВЕТА",
        ]


class TestModelReply:
    def test_parses_model_answer(self) -> None:
        reply = ModelReply.model_validate({"status": "done", "message": "Открыл"}).to_reply()

        assert reply == AgentReply(ReplyStatus.DONE, "Открыл")

    @pytest.mark.parametrize(
        "data",
        [
            None,
            {},
            {"status": "done"},
            {"status": "weird", "message": ""},
            {"status": "failed", "message": ""},
            {"status": "done", "message": "Открыл", "note": "лишнее"},
        ],
    )
    def test_rejects_answer_not_by_the_form(self, data: dict[str, object] | None) -> None:
        with pytest.raises(ValueError):
            ModelReply.model_validate(data)

    def test_answer_wrapped_into_its_own_message_is_unwrapped(self) -> None:
        """Прогоны 12.10.2026: в уведомление попадал JSON целиком вместо текста."""
        wrapped = {"status": "done", "message": '{"status": "done", "message": "Открыл GitHub"}'}

        assert ModelReply.model_validate(wrapped).to_reply() == AgentReply(ReplyStatus.DONE, "Открыл GitHub")

    @pytest.mark.parametrize("message", ["{не json", '{"note": "без message"}', "Открыл {скобки} в тексте"])
    def test_ordinary_text_with_braces_is_left_alone(self, message: str) -> None:
        assert ModelReply.model_validate({"status": "done", "message": message}).message == message

    def test_schema_offers_only_statuses_the_model_may_use(self) -> None:
        schema = ModelReply.json_schema()

        assert schema == {
            "additionalProperties": False,
            "properties": {
                "status": {"enum": ["done", "clarify", "refused", "ignored"], "type": "string"},
                "message": {"type": "string"},
                "options": {"items": {"maxLength": 40, "minLength": 1, "type": "string"}, "maxItems": 4, "type": "array"},
            },
            "required": ["status", "message"],
            "type": "object",
        }

    def test_model_may_use_every_status_except_those_reserved_for_jericho(self) -> None:
        offered = set(ModelReply.json_schema()["properties"]["status"]["enum"])

        assert offered == {status.value for status in ReplyStatus} - {ReplyStatus.FAILED.value, ReplyStatus.STOPPED.value}


class Lock:
    """Замок в памяти: помнит, держат ли его сейчас и держали ли в момент обращения к модели."""

    def __init__(self, free: bool = True) -> None:
        self.held = False
        self.held_during: list[bool] = []
        self._free = free

    def acquire(self) -> bool:
        self.held = self._free
        return self._free

    def release(self) -> None:
        self.held = False


class WatchingBackend(FakeBackend):
    def __init__(self, lock: Lock) -> None:
        super().__init__({"status": "done", "message": "Готово"})
        self._lock = lock

    def ask(self, system_prompt: str, phrase: str) -> BackendAnswer:
        self._lock.held_during.append(self._lock.held)
        return super().ask(system_prompt, phrase)


class TestTaskLayers:
    """Сценарий не знает, что ассистент помнит между поручениями: это приходит слоями."""

    def test_first_layer_is_the_outermost_and_each_can_change_the_message_and_the_outcome(self) -> None:
        trace: list[str] = []

        class Layer:
            def __init__(self, name: str) -> None:
                self._name = name

            def handle(self, task: Task, proceed: TaskHandler) -> Outcome:
                trace.append(f"{self._name} до")
                outcome = proceed(replace(task, message=f"{task.message} +{self._name}"))
                trace.append(f"{self._name} после")
                return Outcome(outcome.reply, {**outcome.details, self._name: True})

        fake = FakeBackend({"status": "done", "message": "Готово"})

        with_layers = HandlePhrase(builder(), fake, [Layer("внешний"), Layer("внутренний")])

        assert with_layers.execute("открой") == AgentReply(ReplyStatus.DONE, "Готово")
        assert trace == ["внешний до", "внутренний до", "внутренний после", "внешний после"]
        assert fake.asked[0][1] == "открой +внешний +внутренний"

    def test_without_layers_nothing_is_remembered_and_nothing_is_added(self) -> None:
        """Так собирается ассистент без диалога и заметок: каркасу они не нужны."""
        fake = FakeBackend({"status": "done", "message": "Готово"})

        assert HandlePhrase(builder(), fake).execute("открой") == AgentReply(ReplyStatus.DONE, "Готово")
        assert fake.asked[0][1] == "открой"


class TestHandlePhrase:
    def test_returns_the_model_reply_and_logs_the_exchange(self, caplog: pytest.LogCaptureFixture) -> None:
        fake = FakeBackend({"status": "done", "message": "Открыл portfolio в Zed"})

        with caplog.at_level(logging.INFO, logger="jericho"):
            reply = HandlePhrase(builder(), fake).execute("открой портфолио")

        assert reply == AgentReply(ReplyStatus.DONE, "Открыл portfolio в Zed")
        assert fake.asked[0][1] == "открой портфолио" and "ЯДРО" in fake.asked[0][0]
        data = caplog.records[-1].data  # pyright: ignore[reportAttributeAccessIssue] — поле из extra
        assert (data["phrase"], data["status"], data["num_turns"]) == ("открой портфолио", "done", 3)

    def test_phrase_holds_the_lock_while_it_is_handled_and_frees_it_afterwards(self) -> None:
        """Память разговора, ожидающий вопрос и заметки общие: вторая фраза ждёт, откуда бы она ни пришла."""
        lock = Lock()

        HandlePhrase(builder(), WatchingBackend(lock), lock=lock).execute("открой портфолио")

        assert (lock.held_during, lock.held) == ([True], False)

    def test_lock_is_freed_even_when_the_model_fails(self) -> None:
        lock = Lock()

        HandlePhrase(builder(), FakeBackend(error="boom"), lock=lock).execute("фраза")

        assert lock.held is False

    def test_busy_assistant_answers_at_once_and_does_not_ask_the_model(self, caplog: pytest.LogCaptureFixture) -> None:
        fake = FakeBackend({"status": "done", "message": "Готово"})

        with caplog.at_level(logging.INFO, logger="jericho"):
            reply = HandlePhrase(builder(), fake, lock=Lock(free=False)).execute("открой портфолио")

        assert reply == AgentReply(ReplyStatus.FAILED, RUSSIAN.busy)
        assert fake.asked == []
        assert caplog.records[-1].data["skipped"] == "busy"  # pyright: ignore[reportAttributeAccessIssue]

    def test_empty_phrase_does_not_reach_the_model(self) -> None:
        fake = FakeBackend({"status": "done", "message": ""})

        assert HandlePhrase(builder(), fake).execute("   ") == AgentReply(ReplyStatus.IGNORED)
        assert fake.asked == []

    def test_running_out_of_time_is_named_so(self) -> None:
        """Журнал 29.10.2026: фраза не уложилась в 90 с, а ответ звучал как «модель недоступна»."""
        fake = FakeBackend(error="no answer in 90 s", error_type=ModelTimeout)

        assert HandlePhrase(builder(), fake).execute("пройди тест") == AgentReply(ReplyStatus.FAILED, RUSSIAN.timeout)

    @pytest.mark.parametrize("fake", [FakeBackend(error="claude reported an error"), FakeBackend({"status": "weird"}), FakeBackend(None)])
    def test_any_failure_becomes_a_failed_reply(self, fake: FakeBackend, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.INFO, logger="jericho"):
            reply = HandlePhrase(builder(), fake).execute("открой портфолио")

        assert reply == AgentReply(ReplyStatus.FAILED, RUSSIAN.failure)
        assert caplog.records[-1].levelname == "ERROR"
