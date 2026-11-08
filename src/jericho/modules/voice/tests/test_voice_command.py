from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import ClassVar

import pytest

from jericho.core.agent.entities import AgentReply, ReplyStatus
from jericho.core.agent.handle_phrase import HandlePhrase
from jericho.core.services.adapters.file_lock import FileLock
from jericho.core.services.confirmation import ConfirmationGate, PendingConfirmation
from jericho.core.services.notifications import Answer, Notification, Urgency
from jericho.core.services.output import NotifyOutput
from jericho.core.services.runner import CommandError
from jericho.core.testing import Confirmations, FakeBackend, builder
from jericho.modules.voice.adapters.hyprwhspr import HyprwhsprRecognizer
from jericho.modules.voice.adapters.status_file import StatusFile
from jericho.modules.voice.protocols import SpeechRecognizerError, VoiceState
from jericho.modules.voice.voice_command import Buttons, ReplyPresenter, VoiceCommand


class Recognizer:
    def __init__(self, phrase: str = "", fails: bool = False) -> None:
        self._phrase = phrase
        self._fails = fails
        self.stopped = False

    def listen(self) -> str:
        if self._fails:
            raise SpeechRecognizerError("no answer in 60 s")
        return self._phrase

    def stop(self) -> None:
        self.stopped = True


class Screen:
    """Запоминает показанные уведомления: (уведомление, на месте какого показано). На вопрос «нажимает» `press`."""

    def __init__(self, press: str | None = None, text: str = "") -> None:
        self.shown: list[tuple[Notification, int | None]] = []
        self.asked: list[tuple[Notification, float, int | None]] = []
        self._press = press
        self._text = text

    def show(self, notification: Notification, replaces: int | None = None) -> int | None:
        self.shown.append((notification, replaces))
        return len(self.shown)

    def ask(self, notification: Notification, wait: float, replaces: int | None = None) -> Answer:
        self.asked.append((notification, wait, replaces))
        return Answer(replaces or 99, self._press, self._text)


class Board:
    def __init__(self) -> None:
        self.states: list[tuple[VoiceState, str]] = []

    def set(self, state: VoiceState, detail: str = "") -> None:
        self.states.append((state, detail))


class Launcher:
    def __init__(self) -> None:
        self.answers: list[tuple[str, int, str, str]] = []

    def answer(self, action: str, replaces: int, text: str = "", question: str = "") -> None:
        self.answers.append((action, replaces, text, question))


def gate(asked_by: str = "", run: str = "run-1") -> ConfirmationGate:
    """Вопрос, заданный запуском `asked_by` (пусто — вопроса нет), глазами запуска `run`."""
    pending = PendingConfirmation("close_windows", {}, "закрыть 3 окна", datetime(2026, 10, 23, 12, 0), asked_by, id="q-1") if asked_by else None
    return ConfirmationGate(Confirmations(pending), run)


class Lock:
    """`free_times` — сколько раз замок дастся, потом его держит кто-то другой; None — даётся всегда."""

    def __init__(self, busy: bool = False, free_times: int | None = None) -> None:
        self._busy = busy
        self._free_times = free_times
        self.released = False

    def acquire(self) -> bool:
        if self._free_times is not None:
            self._free_times -= 1
            return self._free_times >= 0
        return not self._busy

    def release(self) -> None:
        self.released = True


def command(
    recognizer: Recognizer, screen: Screen, backend: FakeBackend, lock: Lock | None = None,
    confirmation: ConfirmationGate | None = None, launcher: Launcher | None = None, board: Board | None = None,
) -> VoiceCommand:
    buttons = Buttons(launcher, wait=30) if launcher is not None else None
    return VoiceCommand(
        recognizer, HandlePhrase(builder(), backend), screen, ReplyPresenter(), lock or Lock(), confirmation or gate(), board or Board(), buttons
    )


class TestVoiceCommand:
    def test_shows_what_was_heard_then_replaces_it_with_the_result(self) -> None:
        screen, lock = Screen(), Lock()
        backend = FakeBackend({"status": "done", "message": "Открыл portfolio в Zed"})

        reply = command(Recognizer(" открой портфолио \n"), screen, backend, lock).execute()

        assert reply == AgentReply(ReplyStatus.DONE, "Открыл portfolio в Zed")
        (heard, heard_replaces), (result, result_replaces) = screen.shown
        assert (heard.body, heard_replaces) == ("«открой портфолио»", None)
        assert (result.body, result_replaces) == ("Открыл portfolio в Zed", 1)
        assert backend.asked[0][1] == "открой портфолио"
        assert lock.released

    def test_silence_does_not_reach_the_model(self) -> None:
        screen, backend = Screen(), FakeBackend({"status": "done", "message": ""})

        assert command(Recognizer("  "), screen, backend).execute() is None
        assert [notification.body for notification, _ in screen.shown] == ["Ничего не расслышал"]
        assert backend.asked == []

    def test_recognizer_failure_is_shown_as_critical(self) -> None:
        screen, lock = Screen(), Lock()

        assert command(Recognizer(fails=True), screen, FakeBackend(), lock).execute() is None
        ((notification, _),) = screen.shown
        assert notification.urgency is Urgency.CRITICAL
        assert lock.released

    def test_second_press_while_busy_does_nothing(self) -> None:
        screen, backend = Screen(), FakeBackend({"status": "done", "message": ""})

        assert command(Recognizer("открой портфолио"), screen, backend, Lock(busy=True)).execute() is None
        assert screen.shown == [] and backend.asked == []


class TestButtons:
    QUESTION: ClassVar[dict[str, object]] = {"status": "clarify", "message": "Закрыть 3 окна Firefox на столе 2?"}

    def test_question_of_this_phrase_waits_for_a_button_without_the_lock(self) -> None:
        screen, lock, launcher = Screen(press="yes"), Lock(), Launcher()

        reply = command(Recognizer("закрой фаерфокс"), screen, FakeBackend(self.QUESTION), lock, gate("run-1"), launcher).execute()

        assert reply == AgentReply(ReplyStatus.CLARIFY, "Закрыть 3 окна Firefox на столе 2?")
        ((question, wait, replaces),) = screen.asked
        assert [action.label for action in question.actions] == ["Да", "Нет"]
        assert (wait, replaces) == (30, 1)              # на месте «думаю»
        assert [notification.body for notification, _ in screen.shown] == ["«закрой фаерфокс»"]      # ответ — только с кнопками
        assert launcher.answers == [("yes", 1, "", "q-1")]      # кнопка несёт id вопроса
        assert lock.released

    def test_nothing_pressed_nothing_launched(self) -> None:
        screen, launcher = Screen(press=None), Launcher()

        command(Recognizer("закрой фаерфокс"), screen, FakeBackend(self.QUESTION), confirmation=gate("run-1"), launcher=launcher).execute()

        assert len(screen.asked) == 1 and launcher.answers == []

    def test_old_question_does_not_put_buttons_on_another_answer(self) -> None:
        """Вопрос из прошлой фразы ещё висит, а эта фраза — про другое: кнопки были бы не о ней."""
        screen, launcher = Screen(press="yes"), Launcher()
        backend = FakeBackend({"status": "done", "message": "Открыл YouTube"})

        command(Recognizer("открой ютуб"), screen, backend, confirmation=gate("run-0"), launcher=launcher).execute()

        assert screen.asked == [] and launcher.answers == []
        assert screen.shown[-1][0].body == "Открыл YouTube"

    def test_without_buttons_the_question_is_shown_as_before(self) -> None:
        screen = Screen(press="yes")

        command(Recognizer("закрой фаерфокс"), screen, FakeBackend(self.QUESTION), confirmation=gate("run-1")).execute()

        assert screen.asked == []
        assert screen.shown[-1][0].actions == ()

    def test_pressed_button_is_the_word_said_and_replaces_the_question(self) -> None:
        screen, backend = Screen(), FakeBackend({"status": "done", "message": "Закрыл 3 окна"})

        reply = command(Recognizer(), screen, backend, confirmation=gate("run-0", run="run-2"), launcher=Launcher()).answer("yes", 41, question="q-1")

        assert reply == AgentReply(ReplyStatus.DONE, "Закрыл 3 окна")
        assert backend.asked[0][1] == "да"
        assert [(n.body, r) for n, r in screen.shown] == [("Закрыл 3 окна", 41)]

    def test_button_after_the_question_is_gone_reaches_nobody(self) -> None:
        """Ответили голосом раньше или срок вышел: «да» по кнопке не должно уйти модели как новая фраза."""
        screen, backend = Screen(), FakeBackend({"status": "done", "message": ""})

        assert command(Recognizer(), screen, backend, confirmation=gate(run="run-2"), launcher=Launcher()).answer("yes", 41) is None
        assert backend.asked == []
        assert [(n.body, r) for n, r in screen.shown] == [("На этот вопрос уже ответили", 41)]

    def test_button_of_a_replaced_question_reaches_nobody(self) -> None:
        """П3b №1: пока висело уведомление «Удалить A», другая фраза спросила «Удалить B» — старая кнопка не о нём."""
        screen, backend = Screen(), FakeBackend({"status": "done", "message": ""})

        assert command(Recognizer(), screen, backend, confirmation=gate("run-0", run="run-2"), launcher=Launcher()).answer("yes", 41, question="q-old") is None
        assert backend.asked == []
        assert [(n.body, r) for n, r in screen.shown] == [("На этот вопрос уже ответили", 41)]

    def test_button_while_another_phrase_runs_waits_for_nothing(self) -> None:
        screen, backend = Screen(), FakeBackend({"status": "done", "message": ""})

        assert command(Recognizer(), screen, backend, Lock(busy=True), gate("run-0", run="run-2"), Launcher()).answer("no", 41) is None
        assert backend.asked == [] and screen.shown == []


class TestReplyField:
    CLARIFY: ClassVar[dict[str, object]] = {"status": "clarify", "message": "Какую Марину: Иванову или Петрову?"}

    def test_clarifying_question_gets_a_field_and_the_typed_text_goes_on(self) -> None:
        screen, launcher = Screen(press=Answer.REPLY, text="Иванова"), Launcher()

        command(Recognizer("что пишет марина"), screen, FakeBackend(self.CLARIFY), launcher=launcher).execute()

        ((question, _, replaces),) = screen.asked
        assert (question.reply, question.actions, replaces) == ("Ответить…", (), 1)
        assert launcher.answers == [(Answer.REPLY, 1, "Иванова", "")]

    def test_typed_answer_is_the_next_phrase(self) -> None:
        screen, backend = Screen(), FakeBackend({"status": "done", "message": "Марина Иванова пишет: буду в 7"})

        reply = command(Recognizer(), screen, backend, launcher=Launcher()).answer(Answer.REPLY, 41, " Иванова\n")

        assert reply == AgentReply(ReplyStatus.DONE, "Марина Иванова пишет: буду в 7")
        assert backend.asked[0][1] == "Иванова"
        assert [(n.body, r) for n, r in screen.shown] == [("Марина Иванова пишет: буду в 7", 41)]

    def test_empty_answer_reaches_nobody(self) -> None:
        screen, backend = Screen(), FakeBackend({"status": "done", "message": ""})

        assert command(Recognizer(), screen, backend, launcher=Launcher()).answer(Answer.REPLY, 41, "  ") is None
        assert backend.asked == [] and screen.shown == []

    def test_confirmation_question_keeps_yes_no_buttons(self) -> None:
        screen = Screen()

        command(Recognizer("закрой фаерфокс"), screen, FakeBackend(TestButtons.QUESTION), confirmation=gate("run-1"), launcher=Launcher()).execute()

        assert screen.asked[0][0].reply == "Исправить или ответить…" and len(screen.asked[0][0].actions) == 2


class TestStopListening:
    def test_stop_button_ends_the_recording(self) -> None:
        recognizer = Recognizer()

        command(recognizer, Screen(), FakeBackend()).stop_listening()

        assert recognizer.stopped


class TestStatusBoard:
    def test_a_phrase_goes_listening_thinking_idle(self) -> None:
        board = Board()

        command(Recognizer("открой ютуб"), Screen(), FakeBackend({"status": "done", "message": "Открыл YouTube"}), board=board).execute()

        assert board.states == [(VoiceState.LISTENING, ""), (VoiceState.THINKING, "открой ютуб"), (VoiceState.IDLE, "Открыл YouTube")]

    def test_silence_is_idle_again(self) -> None:
        board = Board()

        command(Recognizer(""), Screen(), FakeBackend(), board=board).execute()

        assert [state for state, _ in board.states] == [VoiceState.LISTENING, VoiceState.IDLE]

    def test_question_waits_and_unanswered_is_idle(self) -> None:
        board = Board()

        command(Recognizer("закрой фаерфокс"), Screen(), FakeBackend(TestButtons.QUESTION), confirmation=gate("run-1"), launcher=Launcher(), board=board).execute()

        assert [state for state, _ in board.states] == [VoiceState.LISTENING, VoiceState.THINKING, VoiceState.WAITING, VoiceState.IDLE]

    def test_answered_question_leaves_the_state_to_the_next_run(self) -> None:
        board = Board()

        command(
            Recognizer("закрой фаерфокс"), Screen(press="yes"), FakeBackend(TestButtons.QUESTION), confirmation=gate("run-1"), launcher=Launcher(), board=board
        ).execute()

        assert board.states[-1][0] is VoiceState.WAITING

    def test_unanswered_question_does_not_overwrite_a_newer_phrase(self) -> None:
        """Пока висел вопрос, началась новая фраза — замок её; «свободен» от старого вопроса был бы неправдой."""
        board = Board()

        command(Recognizer("закрой фаерфокс"), Screen(), FakeBackend(TestButtons.QUESTION), Lock(free_times=1), gate("run-1"), Launcher(), board).execute()

        assert board.states[-1][0] is VoiceState.WAITING


class TestStatusFile:
    def test_writes_state_with_its_deadline(self, tmp_path: Path) -> None:
        path = tmp_path / "voice.json"
        board = StatusFile(path, {VoiceState.THINKING: 90.0}, clock=lambda: 1000.0)

        board.set(VoiceState.THINKING, "открой ютуб")
        thinking = path.read_text(encoding="utf-8")
        board.set(VoiceState.IDLE, "Открыл YouTube")

        assert thinking.strip() == '{"state": "thinking", "detail": "открой ютуб", "since": 1000.0, "until": 1090.0}'
        assert '"until": null' in path.read_text(encoding="utf-8")

    def test_current_state_and_its_expiry(self, tmp_path: Path) -> None:
        now = [1000.0]
        board = StatusFile(tmp_path / "voice.json", {VoiceState.THINKING: 90.0}, clock=lambda: now[0])

        assert board.current() == {"state": "idle", "detail": ""}          # голосом ещё не пользовались
        board.set(VoiceState.THINKING, "открой ютуб")
        assert board.current() == {"state": "thinking", "detail": "открой ютуб"}
        now[0] = 1091.0
        assert board.current() == {"state": "idle", "detail": ""}          # процесс фразы упал — срок вышел

    def test_unwritable_place_does_not_break_the_phrase(self, tmp_path: Path) -> None:
        (tmp_path / "file").write_text("", encoding="utf-8")
        StatusFile(tmp_path / "file" / "voice.json", {}).set(VoiceState.IDLE)


class TestOptions:
    def test_options_become_buttons_and_the_pressed_one_is_the_answer(self) -> None:
        """«Какой Саша?» с вариантами — кнопками; нажатая уходит ответом, как набранная в поле."""
        screen, launcher = Screen(press="choice:1"), Launcher()
        reply = {"status": "clarify", "message": "Какой Саша?", "options": ["Петров", "Смирнов"]}

        command(Recognizer("что пишет саша"), screen, FakeBackend(reply), launcher=launcher).execute()

        ((question, _, _),) = screen.asked
        assert [action.label for action in question.actions] == ["Петров", "Смирнов"] and question.reply == "Ответить…"
        assert launcher.answers == [(Answer.REPLY, 1, "Смирнов", "")]


class TestReplyPresenter:
    @pytest.mark.parametrize(
        ("status", "title", "urgency"),
        [
            (ReplyStatus.DONE, "Jericho", Urgency.NORMAL),
            (ReplyStatus.CLARIFY, "Jericho · вопрос", Urgency.NORMAL),
            (ReplyStatus.REFUSED, "Jericho · не сделано", Urgency.NORMAL),
            (ReplyStatus.IGNORED, "Jericho · не команда", Urgency.LOW),
            (ReplyStatus.FAILED, "Jericho · сбой", Urgency.CRITICAL),
        ],
    )
    def test_every_status_has_its_own_look(self, status: ReplyStatus, title: str, urgency: Urgency) -> None:
        notification = ReplyPresenter().reply("фраза", AgentReply(status, "текст"))

        assert (notification.title, notification.urgency) == (title, urgency)

    def test_ignored_phrase_shows_what_was_heard(self) -> None:
        assert ReplyPresenter().reply("мама, перезвоню", AgentReply(ReplyStatus.IGNORED)).body == "«мама, перезвоню»"

    def test_titled_like_a_scheduled_reply_but_hurried(self) -> None:
        """Подпись и срочность — те же, что у уведомления по расписанию; срок показа — свой: ответа на фразу ждут."""
        screen = Screen()
        reply = AgentReply(ReplyStatus.REFUSED, "без «да» не отправлю")

        NotifyOutput(screen, "Jericho").deliver("отправь", reply)
        voice = ReplyPresenter("Jericho").reply("отправь", reply)

        assert (voice.title, voice.urgency) == (screen.shown[0][0].title, screen.shown[0][0].urgency) == ("Jericho · не сделано", Urgency.NORMAL)
        assert voice.timeout_ms == 8000 and screen.shown[0][0].timeout_ms is None

    def test_persistent_notification_stays_until_closed(self) -> None:
        """Журнал 26.10.2026: напоминание провисело 6 с, пока у экрана никого не было, и пропало непрочитанным."""
        screen = Screen()

        NotifyOutput(screen, "Jericho", persistent=True).deliver("лекция", AgentReply(ReplyStatus.DONE, "Напоминание: записаться на лекцию"))

        assert screen.shown[0][0].timeout_ms == 0


class Runner:
    def __init__(self, output: str = "", fail_on: str = "") -> None:
        self.commands: list[list[str]] = []
        self._output = output
        self._fail_on = fail_on

    def run(
        self, command: Sequence[str], stdin: str | None = None, *, reads: bool = False, dry_answer: str = ""
    ) -> str:
        self.commands.append(list(command))
        if self._fail_on and self._fail_on in command:
            raise CommandError("no answer in 60 s")
        return self._output

    def launch(self, command: Sequence[str]) -> None:
        self.run(command)


class TestHyprwhsprRecognizer:
    def test_returns_captured_text(self) -> None:
        runner = Runner("открой портфолио")

        assert HyprwhsprRecognizer(runner, Path("/bin/hyprwhspr")).listen() == "открой портфолио"
        assert runner.commands == [[str(Path("/bin/hyprwhspr")), "record", "capture"]]

    def test_stop_ends_the_recording_like_a_released_key(self) -> None:
        runner = Runner()

        HyprwhsprRecognizer(runner, Path("/bin/hyprwhspr")).stop()

        assert runner.commands == [[str(Path("/bin/hyprwhspr")), "record", "stop"]]

    def test_timeout_cancels_the_recording(self) -> None:
        runner = Runner(fail_on="capture")

        with pytest.raises(SpeechRecognizerError):
            HyprwhsprRecognizer(runner, Path("/bin/hyprwhspr")).listen()
        assert runner.commands[-1] == [str(Path("/bin/hyprwhspr")), "record", "cancel"]


class TestFileLock:
    def test_second_holder_is_refused_until_release(self, tmp_path: Path) -> None:
        first, second = FileLock(tmp_path / "run" / "listen.lock"), FileLock(tmp_path / "run" / "listen.lock")

        assert first.acquire() is True
        assert second.acquire() is False
        first.release()
        assert second.acquire() is True
        second.release()

    def test_waiting_holder_gets_the_lock_as_soon_as_it_is_released(self, tmp_path: Path) -> None:
        """Так вторая фраза дожидается первой, а не пропадает."""
        first = FileLock(tmp_path / "phrase.lock")
        second = FileLock(tmp_path / "phrase.lock", wait=5.0, sleep=lambda seconds: first.release())
        first.acquire()

        assert second.acquire() is True
        second.release()

    def test_waiting_ends_when_the_time_is_out(self, tmp_path: Path) -> None:
        first, second = FileLock(tmp_path / "phrase.lock"), FileLock(tmp_path / "phrase.lock", wait=0.05, sleep=lambda seconds: None)
        first.acquire()

        assert second.acquire() is False
        first.release()


class TestReadingTime:
    def test_answer_to_a_question_stays_long_enough_to_be_read(self) -> None:
        """Журнал 13.10.2026: список из двенадцати фамилий мелькал те же пять секунд, что и «Открыл YouTube»."""
        presenter = ReplyPresenter()
        short = presenter.reply("открой ютуб", AgentReply(ReplyStatus.DONE, "Открыл YouTube"))
        answer = presenter.reply("кто на скамейке", AgentReply(ReplyStatus.DONE, "Дарлоу, Ми, " * 12))
        essay = presenter.reply("расскажи", AgentReply(ReplyStatus.DONE, "я" * 2000))

        assert (short.timeout_ms, answer.timeout_ms, essay.timeout_ms) == (5000, 8640, 20000)
