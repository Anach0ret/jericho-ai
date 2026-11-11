"""Сценарий «поручение → ответ»: главный вход Jericho."""

from __future__ import annotations

import time
from collections.abc import Sequence
from functools import partial

from jericho.core.agent.consent import AnswerWithoutModel, AskedQuestion, Heard
from jericho.core.agent.entities import AgentReply, ReplyStatus
from jericho.core.agent.forms import Brief, ReplyForm
from jericho.core.agent.phrase_journal import PhraseJournal
from jericho.core.agent.protocols import AgentBackend, AgentBackendError, ModelTimeout
from jericho.core.agent.task import Outcome, Task, TaskLayer, chain
from jericho.core.agent.wording import RUSSIAN, Wording
from jericho.core.prompting.builder import PromptBuilder
from jericho.core.services.lock import ExclusiveLock, Unlocked
from jericho.core.services.phrase_deadline import PhraseDeadline


class HandlePhrase:
    """Отдаёт поручение модели вместе с промптом и превращает её ответ в AgentReply.

    Цикл «модель вызвала инструмент → получила результат → поправилась и вызвала снова» ведёт
    бэкенд; сюда приходит уже итог. Любой сбой становится ответом со статусом FAILED —
    пользователь всегда получает строку для уведомления.

    Сам сценарий — пять шагов: собрать промпт, спросить модель, разобрать ответ, превратить сбой в ответ,
    записать в журнал (`PhraseJournal` — он же решает, что из личного ответа туда можно). Всё, что ассистент помнит между поручениями (разговор, заметки), приходит слоями
    вокруг (`TaskLayer`) и сценарию неизвестно.

    Поручения обрабатываются по одному, откуда бы они ни пришли — с клавиши или из терминала: то, что слои
    помнят, у них общее, и два поручения сразу затёрли бы это друг другу.

    «Да» и «нет» на ждущий вопрос распознаёт код (`AnswerWithoutModel`) — и, если умеет, сам же на них отвечает,
    без модели. Слои вокруг поручения работают как обычно.
    """

    UNATTENDED_NOTE = (
        "[Рядом никого нет: поручение пришло по расписанию, переспросить и подтвердить некому. Не задавай вопросов — "
        "сделай то, что можно без подтверждения, а чего не сделал и почему, скажи в ответе.]"
    )

    def __init__(
        self,
        prompts: PromptBuilder,
        backend: AgentBackend,
        layers: Sequence[TaskLayer] = (),
        lock: ExclusiveLock | None = None,
        form: ReplyForm | None = None,
        attended: bool = True,
        consent: AnswerWithoutModel | None = None,
        journal: PhraseJournal | None = None,
        question: AskedQuestion | None = None,
        wording: Wording = RUSSIAN,
        deadline: PhraseDeadline | None = None,
    ) -> None:
        self._prompts = prompts
        self._deadline = deadline or PhraseDeadline()      # срок всей фразы: бэкенды, запасные и сервер ручек — в его пределах
        self._attended = attended
        self._consent = consent      # «да» и «нет» на ждущий вопрос слышит код, до модели
        self._layers = tuple(layers)
        self._backend = backend
        self._form = form or Brief()
        self._handler = chain(layers, self._ask)
        self._lock = lock or Unlocked()
        self._journal = journal or PhraseJournal()
        self._question = question      # вопрос ручки этой фразы: дошёл до пользователя — с кнопками «Да» и «Нет», нет — снят
        self._wording = wording
        self.busy = AgentReply(ReplyStatus.FAILED, wording.busy)     # поручение не взято: другое ещё идёт — его можно повторить

    def execute(self, phrase: str, question: str = "", reply_to: str = "") -> AgentReply:
        """`question` — id вопроса «да?», под которым нажата кнопка: ответ — только ему (`PhraseConsent.hear`).
        `reply_to` — номер сообщения транспорта, на которое человек ответил: его разбирают слои (`notices`)."""
        if not phrase.strip():
            return AgentReply(ReplyStatus.IGNORED)
        if not self._lock.acquire():
            self._journal.skipped(phrase, "busy")
            return self.busy
        self._deadline.start()
        try:
            return self._handle(phrase, question, reply_to)
        finally:
            self._deadline.stop()
            self._lock.release()

    def _handle(self, phrase: str, question: str, reply_to: str = "") -> AgentReply:
        started = time.perf_counter()
        self._journal.received(phrase, self._attended)
        heard = self._consent.hear(phrase, question) if self._consent is not None and self._attended else Heard()
        message = phrase if self._attended else f"{phrase}\n\n{self.UNATTENDED_NOTE}"
        answered = self._consent is not None and self._consent.answers(heard)
        handler = chain(self._layers, partial(self._consent, heard)) if answered and self._consent is not None else self._handler
        try:
            outcome = handler(Task(text=phrase, message=message, attended=self._attended, reply_to=reply_to))
        except KeyboardInterrupt:     # `stop` или Ctrl+C: слои не запоминают оборванное поручение
            outcome = Outcome(AgentReply(ReplyStatus.STOPPED, self._wording.stopped), {"stopped": True})
        reply = self._question.settle(outcome.reply) if self._question is not None else outcome.reply
        details = {**outcome.details, **({"consent": heard.answer} if heard else {}), **({} if self._attended else {"unattended": True})}
        return self._journal.record(phrase, reply, details, round((time.perf_counter() - started) * 1000))

    def _ask(self, task: Task) -> Outcome:
        """Ответ модели и сведения о запросе для журнала (число ходов, стоимость либо текст ошибки)."""
        details: dict[str, object] = {}
        try:
            answer = self._backend.ask(self._prompts.build(), task.message)
            details.update(answer.meta)      # сведения о запросе нужны в журнале, даже если ответ не разобрался
            return Outcome(self._form.parse(answer.structured), details)
        except ModelTimeout as error:
            return Outcome(AgentReply(ReplyStatus.FAILED, self._wording.timeout), {**details, "error": str(error)})
        except (AgentBackendError, ValueError) as error:
            return Outcome(AgentReply(ReplyStatus.FAILED, self._wording.failure), {**details, "error": str(error)})
