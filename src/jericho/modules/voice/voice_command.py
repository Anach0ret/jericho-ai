"""Сценарий «голосовая команда»: послушать → понять → сделать → показать уведомление."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from typing import ClassVar

from jericho.core.agent.entities import AgentReply, ReplyStatus
from jericho.core.agent.handle_phrase import HandlePhrase
from jericho.core.services.confirmation import ConfirmationGate
from jericho.core.services.lock import ExclusiveLock
from jericho.core.services.notifications import Action, Answer, AskingNotifier, Notification, StatusLook, Urgency
from jericho.modules.voice.protocols import AnswerLauncher, SpeechRecognizer, SpeechRecognizerError, StatusBoard, VoiceState

logger = logging.getLogger(__name__)


class ReplyPresenter:
    """Решает, как каждый исход выглядит в уведомлении."""

    BRIEF_MS, PER_CHARACTER_MS, LONGEST_MS = 5000, 60, 20000
    SHOWN_MS: ClassVar[dict[ReplyStatus, int]] = {ReplyStatus.CLARIFY: 12000, ReplyStatus.REFUSED: 8000, ReplyStatus.IGNORED: 2000, ReplyStatus.STOPPED: 5000}

    def __init__(self, app: str = "Jericho") -> None:
        self._app = app      # заголовок уведомлений: имя ассистента
        self._look = StatusLook(app)

    def heard(self, phrase: str) -> Notification:
        """Показывается сразу после распознавания: видно, что услышано, пока модель думает."""
        return Notification(f"{self._app} · думаю", f"«{phrase}»", Urgency.LOW)

    def nothing_heard(self) -> Notification:
        return Notification(self._app, "Ничего не расслышал", Urgency.LOW, timeout_ms=2000)

    def recognizer_failed(self) -> Notification:
        return Notification(self._look.title(ReplyStatus.FAILED), "Распознавание речи не ответило", Urgency.CRITICAL)

    def reply(self, phrase: str, reply: AgentReply) -> Notification:
        """Сбой висит, пока его не закроют; «не команда» показывает, что услышано, а не ответ модели."""
        status = reply.status
        body = f"«{phrase}»" if status is ReplyStatus.IGNORED else reply.message
        shown = self._reading_time(reply.message) if status is ReplyStatus.DONE else self.SHOWN_MS.get(status)
        return Notification(self._look.title(status), body, self._look.urgency(status), timeout_ms=shown, transient=reply.private)

    def answered_already(self) -> Notification:
        """Нажали кнопку, а вопроса уже нет: ответили голосом раньше или его время вышло."""
        return Notification(self._app, "На этот вопрос уже ответили", Urgency.LOW, timeout_ms=3000)

    def _reading_time(self, message: str) -> int:
        """Отчёт о действии мелькает пять секунд; ответ на вопрос висит столько, чтобы его успели прочитать."""
        return min(max(self.BRIEF_MS, len(message) * self.PER_CHARACTER_MS), self.LONGEST_MS)


@dataclass(frozen=True, slots=True)
class Buttons:
    """Как спрашивать кнопками: сколько ждать нажатия и кому отдать нажатую. Без них вопрос — только голосом.

    `reply_field` — уточняющий вопрос модели («какую Марину?») получает поле для ответа текстом.
    """

    launcher: AnswerLauncher
    wait: float = 120.0
    reply_field: bool = True

    YES: ClassVar[Action] = Action("yes", "Да")
    NO: ClassVar[Action] = Action("no", "Нет")
    SAID: ClassVar[dict[str, str]] = {"yes": "да", "no": "нет"}     # кнопка — то же, что сказанное слово
    CHOICE: ClassVar[str] = "choice:"     # кнопка-вариант ответа: её надпись уходит ответом, как набранная в поле

    @classmethod
    def choices(cls, options: Sequence[str]) -> tuple[Action, ...]:
        """Варианты ответа модели («Петров», «Смирнов») — кнопками."""
        return tuple(Action(f"{cls.CHOICE}{index}", option) for index, option in enumerate(options))

    @classmethod
    def answer(cls, question: Notification, action: str, text: str) -> tuple[str, str]:
        """Что нажато → что отдать следующему запуску: вариант уходит ответом текстом (своей надписью)."""
        if not action.startswith(cls.CHOICE):
            return action, text
        return Answer.REPLY, next((choice.label for choice in question.actions if choice.key == action), "")


@dataclass(frozen=True, slots=True)
class Turn:
    """Итог одного прохода под замком: ответ и, если в нём вопрос, уведомление, которое ждёт кнопку уже без замка."""

    reply: AgentReply | None = None
    question: Notification | None = None
    replaces: int | None = None
    asks: str = ""       # id вопроса «да?» в уведомлении: нажатая кнопка ответит только ему


class VoiceCommand:
    """Одна голосовая команда от нажатия клавиши до уведомления.

    Одновременно выполняется только одна: повторное нажатие, пока идёт запись или ответ,
    ничего не запускает — иначе одна фраза исполнилась бы дважды.

    Ответ с вопросом показывается с кнопками «Да» и «Нет». Нажатия ждём уже без замка, чтобы следующая фраза
    не стояла в очереди; нажатая кнопка уходит новому запуску (`--answer`) и проходит тот же путь, что слово «да».
    """

    def __init__(
        self,
        recognizer: SpeechRecognizer,
        handle_phrase: HandlePhrase,
        notifier: AskingNotifier,
        presenter: ReplyPresenter,
        lock: ExclusiveLock,
        gate: ConfirmationGate,
        board: StatusBoard,
        buttons: Buttons | None = None,
    ) -> None:
        self._recognizer = recognizer
        self._handle_phrase = handle_phrase
        self._notifier = notifier
        self._presenter = presenter
        self._lock = lock
        self._gate = gate
        self._board = board          # чем занят голос — для значка на панели
        self._buttons = buttons

    def execute(self) -> AgentReply | None:
        """Возвращает ответ на фразу; None — команды не было (занято, тишина или сбой распознавания)."""
        return self._finish(self._locked(self._run))

    def stop_listening(self) -> None:
        """Кнопка «стоп» в окне на панели — то же, что отпустить клавишу: запись кончается, фраза идёт дальше."""
        self._recognizer.stop()

    def answer(self, action: str, replaces: int | None, text: str = "", question: str = "") -> AgentReply | None:
        """Ответ из уведомления с вопросом — кнопкой или текстом: как сказанное слово, итог — на месте вопроса.

        `question` — id вопроса «да?», под которым нажато: «Да» и «Нет» засчитываются только ему (ревью 02.11.2026, П3b №1).
        """
        return self._finish(self._locked(lambda: self._answered(action, replaces, text, question)))

    def _locked(self, step: Callable[[], Turn]) -> Turn:
        if not self._lock.acquire():
            logger.info("voice", extra={"data": {"skipped": "already_running"}})
            return Turn()
        try:
            return step()
        finally:
            self._lock.release()

    def _run(self) -> Turn:
        self._board.set(VoiceState.LISTENING)
        try:
            phrase = self._recognizer.listen().strip()
        except SpeechRecognizerError as error:
            logger.error("voice", extra={"data": {"error": str(error)}})
            self._board.set(VoiceState.IDLE)
            self._notifier.show(self._presenter.recognizer_failed())
            return Turn()
        logger.info("voice", extra={"data": {"heard": phrase}})
        if not phrase:
            self._board.set(VoiceState.IDLE)
            self._notifier.show(self._presenter.nothing_heard())
            return Turn()
        return self._respond(phrase, self._notifier.show(self._presenter.heard(phrase)))

    def _answered(self, action: str, replaces: int | None, text: str, question: str) -> Turn:
        logger.info("voice", extra={"data": {"pressed": action}})
        if action == Answer.REPLY:
            return self._respond(text.strip(), replaces, question) if text.strip() else Turn()
        said = Buttons.SAID.get(action)
        waiting = self._gate.waiting()
        if said is None or waiting is None or waiting.id != question:
            self._notifier.show(self._presenter.answered_already(), replaces=replaces)
            return Turn()
        return self._respond(said, replaces, question)     # вопрос сверяется ещё раз — под замком фразы

    def _respond(self, phrase: str, shown: int | None, answering: str = "") -> Turn:
        self._board.set(VoiceState.THINKING, phrase)
        reply = self._handle_phrase.execute(phrase, answering)
        notification = self._presenter.reply(phrase, reply)
        question = self._question(notification, reply)
        self._board.set(VoiceState.WAITING if question else VoiceState.IDLE, reply.message)
        if question is not None:
            waiting = self._gate.waiting() if self._gate.asked_now() else None
            return Turn(reply, question, shown, waiting.id if waiting is not None else "")
        self._notifier.show(notification, replaces=shown)
        return Turn(reply)

    def _question(self, notification: Notification, reply: AgentReply) -> Notification | None:
        """Ответ, который ждёт человека: вопрос с «да» — кнопки, уточнение модели — поле ответа. None — ждать нечего."""
        if self._buttons is None:
            return None
        if self._gate.asked_now():
            # Поле — чтобы не только ответить «да» или «нет», но и поправить: «не 10, а 15 минут».
            correction = "Исправить или ответить…" if self._buttons.reply_field else None
            return replace(notification, actions=(Buttons.YES, Buttons.NO), reply=correction)
        if self._buttons.reply_field and reply.status is ReplyStatus.CLARIFY:
            # Варианты от модели («Петров», «Смирнов») — кнопками; поле остаётся: ответ может быть другим.
            return replace(notification, actions=Buttons.choices(reply.options), reply="Ответить…")
        return None

    def _finish(self, turn: Turn) -> AgentReply | None:
        """Вопрос показан с кнопками и ждёт нажатия; нажатую отдаём следующему запуску."""
        if turn.question is None or self._buttons is None:
            return turn.reply
        pressed = self._notifier.ask(turn.question, self._buttons.wait, replaces=turn.replaces)
        if pressed.action is not None and pressed.id is not None:
            action, text = Buttons.answer(turn.question, pressed.action, pressed.text)
            self._buttons.launcher.answer(action, pressed.id, text, turn.asks)
        else:
            self._release_board(turn.question.body)
        return turn.reply

    def _release_board(self, detail: str) -> None:
        """Вопрос кончился без ответа — значок снова «свободен». Но если тем временем идёт новая фраза
        (замок занят), состояние теперь её, и трогать его нельзя."""
        if self._lock.acquire():
            try:
                self._board.set(VoiceState.IDLE, detail)
            finally:
                self._lock.release()
