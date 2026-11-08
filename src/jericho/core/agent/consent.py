"""«Да» и «нет» пользователя на ждущий вопрос — их распознаёт код по самой фразе, а не модель."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, replace

from jericho.core.agent.entities import AgentReply, ReplyStatus
from jericho.core.agent.task import Outcome, Task
from jericho.core.agent.wording import RUSSIAN, Wording
from jericho.core.services.confirmation import ConfirmationGate
from jericho.core.tools.consent import NEEDS_CONFIRM
from jericho.core.tools.result import ToolResult

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Heard:
    """Что вход поручения услышал во фразе: «да» или «нет» на ждущий вопрос — и сам вопрос."""

    answer: str = ""        # "yes", "no", "expired" (ответ пришёл после срока), "stale" (кнопка сменившегося вопроса)
                            # или пусто — фраза не ответ на вопрос
    question: str = ""      # о чём спрашивали: так ответ без модели назовёт, что сделано или отменено
    asked_at: str = ""      # когда спрашивали — для «истёк»: «вопрос от 14:05»

    def __bool__(self) -> bool:
        return bool(self.answer)


class AskedQuestion:
    """Вопрос «да?» доходит до пользователя только ответом `clarify` — и словами кода, а не модели.

    Текст вопроса — из сохранённого вызова (`summary`), слова модели — подробностями под ним. Модель отвечала
    «Продолжать читать?», а «да» на это выполняло ждущую отправку письма (ревью 02.11.2026, сводка №2). Варианты —
    ровно «Да» и «Нет», те, что слышит `PhraseConsent`: свою кнопку «Да, отправить» ядро не принимало (журнал 29.10.2026).

    Последним пользователь должен увидеть тот вопрос, на который ответит «да». Поэтому вопрос снимается, если ответ
    этой фразы его не задал (журнал 29.10.2026: «отвечать дальше?» → «да» → записана заметка) или если модель
    в следующей фразе задала свой вопрос.
    """

    def __init__(self, gate: ConfirmationGate, wording: Wording = RUSSIAN) -> None:
        self._gate = gate
        self._wording = wording

    def settle(self, reply: AgentReply) -> AgentReply:
        waiting = self._gate.waiting()
        if waiting is None:
            return reply
        mine = self._gate.asked_now()
        if mine and reply.status is ReplyStatus.CLARIFY:
            return self._asks(waiting.summary, reply)
        if mine or reply.status is ReplyStatus.CLARIFY:
            dropped = self._gate.withdraw()
            if dropped is not None:
                logger.warning("confirmation_unasked", extra={"data": {"dropped": dropped.summary, "status": reply.status.value}})
        return reply

    def _asks(self, summary: str, reply: AgentReply) -> AgentReply:
        """Вопрос — строкой кода; что сказала модель — подробностями."""
        question = self._wording.asks.format(question=f"{summary[:1].upper()}{summary[1:]}".rstrip(" .?"))
        said = "\n\n".join(part for part in (reply.message, reply.body) if part.strip())
        return replace(reply, message=question, body=said, options=(self._wording.yes, self._wording.no))


class PhraseConsent:
    """Слушает фразу до модели: однозначное «да» одобряет ждущий вопрос, «нет» снимает его.

    Принимается только фраза целиком: «да», «давай», «подтверждаю». «Да, и ещё открой почту» — не согласие:
    модель могла бы приписать «да» не тому, и вопрос остаётся ждать отдельного «да». Так согласие приходит
    из доверенного входа — от пользователя, а не из решения модели (ревью R02).
    """

    YES = frozenset({
        "да", "ага", "угу", "конечно", "да конечно", "подтверждаю", "давай", "да давай", "делай", "да делай",
        "отправляй", "да отправляй", "выполняй", "можно", "да можно", "ок", "окей", "хорошо", "верно", "да верно",
        "yes", "yeah", "yep", "sure", "ok", "okay", "confirm", "go ahead", "do it", "yes do it", "yes go ahead",
    })
    NO = frozenset({
        "нет", "не надо", "не нужно", "нет не надо", "нет не нужно", "отмена", "отмени", "отменяй", "стоп",
        "не делай", "нет не делай",
        "no", "nope", "cancel", "stop", "don t", "do not", "no thanks", "no don t",
    })
    _NOISE = re.compile(r"[^\w\s]")
    _POLITE = re.compile(r"\s*\b(?:пожалуйста|please)\b\s*")

    def __init__(self, gate: ConfirmationGate) -> None:
        self._gate = gate

    def hear(self, phrase: str, question: str = "") -> Heard:
        """«Да», «нет» — или пусто: фраза не ответ на вопрос (или вопроса нет).

        `question` — id вопроса, под которым нажата кнопка: ответ засчитывается только ему. Проверка — здесь, под замком
        фразы: пока висело уведомление, другая фраза могла сменить вопрос (ревью 02.11.2026, П3b №1).
        """
        words = self._POLITE.sub(" ", self._NOISE.sub(" ", phrase.casefold())).split()
        said = " ".join(words)
        if question and said in self.YES | self.NO and not self._still_waits(question):
            return Heard("stale")
        if said in self.YES and (approved := self._gate.user_said_yes()) is not None:
            return Heard("yes", approved.summary)
        if said in self.NO and (declined := self._gate.user_said_no()) is not None:
            logger.info("confirmation_declined", extra={"data": {"phrase": phrase}})
            return Heard("no", declined.summary)
        if said in self.YES | self.NO and (expired := self._gate.take_expired()) is not None:
            logger.warning("confirmation_expired", extra={"data": {"asked": expired.summary, "asked_at": expired.asked_at.isoformat(), "answer": said}})
            return Heard("expired", expired.summary, f"{expired.asked_at:%H:%M}")
        return Heard()

    def _still_waits(self, question: str) -> bool:
        """Тот ли вопрос ждёт ответа, под которым нажата кнопка."""
        waiting = self._gate.waiting()
        if waiting is not None and waiting.id == question:
            return True
        logger.warning("confirmation_stale", extra={"data": {"button": question, "waiting": waiting.summary if waiting else None}})
        return False


class AnswerWithoutModel:
    """«Да» и «нет» на ждущий вопрос — без модели: код слышит ответ (`PhraseConsent`), а на «да» `confirm` выполняет
    ровно тот вызов, о котором спрашивали (как ручка `confirm()`). Это экономит модели два хода.

    Без `confirm` ответ только слышится — одобряет вопрос, — а выполняет его модель своим `confirm()`.
    """

    def __init__(self, consent: PhraseConsent, confirm: Callable[[], ToolResult] | None = None, wording: Wording = RUSSIAN) -> None:
        self._consent = consent
        self._confirm = confirm
        self._wording = wording

    def hear(self, phrase: str, question: str = "") -> Heard:
        return self._consent.hear(phrase, question)

    def answers(self, heard: Heard) -> bool:
        """Ответит ли на это сам код, без модели. Об истёкшем и сменившемся вопросе — всегда: выполнять тут нечего."""
        return heard.answer in ("expired", "stale") or (bool(heard) and self._confirm is not None)

    def __call__(self, heard: Heard, task: Task) -> Outcome:
        """Вопрос назван словами, итог — из ответа подтверждённой ручки."""
        if heard.answer == "no":
            return Outcome(AgentReply(ReplyStatus.DONE, self._wording.cancelled.format(question=heard.question)), {"without_model": True})
        if heard.answer == "expired":
            reply = self._wording.expired.format(asked_at=heard.asked_at, question=heard.question)
            return Outcome(AgentReply(ReplyStatus.REFUSED, reply), {"without_model": True, "expired": True})
        if heard.answer == "stale":
            return Outcome(AgentReply(ReplyStatus.REFUSED, self._wording.stale), {"without_model": True, "stale": True})
        result = self._confirm() if self._confirm is not None else ToolResult.failure("no_confirm")
        if result.error == NEEDS_CONFIRM:     # всё изменилось: вопрос задан заново и ждёт следующего «да» (П1 №4)
            return Outcome(AgentReply(ReplyStatus.CLARIFY, self._wording.asked_again), {"without_model": True, "asked_again": True})
        if result.ok:
            detail = result.data.get("detail")
            done = f"{heard.question[:1].upper()}{heard.question[1:]} — {detail}" if isinstance(detail, str) and detail else self._wording.done.format(question=heard.question)
            return Outcome(AgentReply(ReplyStatus.DONE, done), {"without_model": True, "confirmed": result.data.get("confirmed")})
        reason = result.data.get("changed") or result.data.get("detail") or result.error     # словами, если отказ объяснил
        refused = self._wording.not_done.format(question=heard.question, reason=reason)
        return Outcome(AgentReply(ReplyStatus.REFUSED, refused), {"without_model": True, "error": result.error})
