"""Слой «уведомления»: фраза человека может быть вопросом о сводке или тревоге, которую ассистент прислал сам."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import replace

from jericho.core.agent.task import Outcome, Task, TaskHandler
from jericho.core.services.foreign import ForeignText
from jericho.core.services.sent import SentLog, SentNotice


class NoticeContext:
    """До модели — прикладывает к фразе уведомления этого человека из журнала отправленного (`SentLog`).

    Три случая — и выбор в каждом делает код, а не модель (задача 102, ревью плана 11.11.2026):
    - ответ reply на известное уведомление — к фразе идёт **только оно**: вопрос о нём, даже если есть новее;
    - reply на сообщение, которого среди уведомлений нет (обычный ответ, истёк срок, транспорт перезапускался), —
      ни одного уведомления: подставить другое нельзя, модель уточняет, если вопрос об уведомлении;
    - не reply — последние уведомления, новые первыми: модель выбирает, подходят несколько — уточняет.
    Чужой текст, бывший в уведомлении, снова учитывается (`foreign.restore`): модель увидит его второй раз.
    """

    def __init__(self, sent: SentLog, mine: Sequence[str], foreign: ForeignText, shown: int, chars: int) -> None:
        self._sent = sent
        self._mine = tuple(mine)        # адресаты, чьи уведомления — разговор этого человека
        self._foreign = foreign
        self._shown = shown
        self._chars = chars

    def handle(self, task: Task, proceed: TaskHandler) -> Outcome:
        if not task.attended or not self._mine:
            return proceed(task)
        note = self._replied(task.reply_to) if task.reply_to else self._recent()
        return proceed(replace(task, message=f"{task.message}\n\n{note}") if note else task)

    def _replied(self, message: str) -> str:
        notice = next((found for to in self._mine if (found := self._sent.by_message(to, message)) is not None), None)
        if notice is None:
            return (
                "[Пользователь ответил на сообщение, которого нет среди твоих уведомлений за сутки: это обычный ответ, "
                "старое уведомление или память транспорта сброшена. Если вопрос — об уведомлении (сводке, тревоге), "
                "не подставляй другое: спроси, о каком.]"
            )
        return f"[Пользователь ответил на твоё уведомление — вопрос о нём, даже если есть новее:\n{self._shown_notice(notice)}]"

    def _recent(self) -> str:
        notices = sorted((notice for to in self._mine for notice in self._sent.recent(to)), key=lambda notice: notice.time, reverse=True)
        if not notices:
            return ""
        listed = "\n".join(self._shown_notice(notice) for notice in notices[: self._shown])
        return (
            f"[Уведомления, которые ты прислал этому пользователю за сутки, новые первыми:\n{listed}\n"
            "Если фраза — о них, отвечай по нужному и бери его данные (окно, проект, фильтры), а не «последние 24 часа» "
            "от вопроса. Подходят несколько — спроси, о каком. Фраза о другом — уведомления ни при чём.]"
        )

    def _shown_notice(self, notice: SentNotice) -> str:
        for source in notice.foreign:
            self._foreign.restore(source)
        text = notice.text if len(notice.text) <= self._chars else notice.text[: self._chars] + " …"
        facts = f"\n  данные: {json.dumps(notice.facts, ensure_ascii=False)}" if notice.facts else ""
        body = f"\n  {text}" if text else ""
        return f"- {notice.time:%d.%m %H:%M %Z} · {notice.task[:80]} · {notice.status}: «{notice.title}»{body}{facts}"
