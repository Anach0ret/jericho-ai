"""Что ядро говорит пользователю само, без модели, — на языке ассистента (`Settings.language`).

Промпт и описания ручек пока по-русски; модели на английском ассистенте велено отвечать по-английски.
«Да» и «нет» код слышит на обоих языках при любой настройке: «yes» русскоязычного не должно теряться.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Wording:
    yes: str                 # кнопки вопроса «да?»
    no: str
    failure: str
    timeout: str
    busy: str
    stopped: str
    cancelled: str           # {question}
    done: str                # {question}
    not_done: str            # {question}, {reason}
    expired: str             # {asked_at}, {question}
    expired_title: str       # {question} — сообщение в чат, когда вопрос истёк без ответа
    expired_text: str
    reminder_title: str      # {question}
    reminder_text: str       # {until}
    asks: str                # {question} — сам вопрос «да?»: его текст ставит код, а не модель
    asked_again: str         # «да» было, но с тех пор всё изменилось — вопрос задан заново
    stale: str               # кнопка под вопросом, который уже сменился, снят или истёк
    reply_language: str = ""     # строка для модели; пусто — язык промпта


RUSSIAN = Wording(
    yes="Да",
    no="Нет",
    failure="Не получилось обратиться к модели — подробности в журнале",
    timeout="Не уложился в отведённое время — что успело выполниться, видно в журнале",
    busy="Ещё занят предыдущей фразой — повтори чуть позже",
    stopped="Остановлено — что успело выполниться, видно в журнале",
    cancelled="Отменил: {question}",
    done="Сделано: {question}",
    not_done="Не сделано: {question} — {reason}",
    expired="Вопрос от {asked_at} истёк: {question} — ничего не сделано. Если нужно, попроси ещё раз.",
    expired_title="Вопрос истёк: {question}",
    expired_text="Ничего не сделано. Если нужно, попроси ещё раз.",
    reminder_title="Жду «да»: {question}",
    reminder_text="Вопрос в силе до {until}. Нет ответа — ничего не сделаю.",
    asks="{question}? Да или нет.",
    asked_again="С прошлого вопроса всё изменилось — спрашиваю заново, пока ничего не сделано.",
    stale="Этот вопрос уже не ждёт ответа: на него ответили, его сменил другой или он истёк. Ничего не сделано.",
)

ENGLISH = Wording(
    yes="Yes",
    no="No",
    failure="Could not reach the model — details are in the journal",
    timeout="Ran out of time — what got done is in the journal",
    busy="Still busy with the previous request — try again in a moment",
    stopped="Stopped — what got done is in the journal",
    cancelled="Cancelled: {question}",
    done="Done: {question}",
    not_done="Not done: {question} — {reason}",
    expired="The question from {asked_at} has expired: {question} — nothing was done. Ask again if you still need it.",
    expired_title="Question expired: {question}",
    expired_text="Nothing was done. Ask again if you still need it.",
    reminder_title="Waiting for a yes: {question}",
    reminder_text="The question stands until {until}. No answer — nothing will be done.",
    asks="{question}? Yes or no.",
    asked_again="Things have changed since the question — asking again, nothing has been done yet.",
    stale="That question is no longer waiting: it was answered, replaced by another or has expired. Nothing was done.",
    reply_language="Answer the user in English, whatever the language of these instructions.",
)

WORDINGS = {"ru": RUSSIAN, "en": ENGLISH}
