"""Полные ответы о личной переписке — в папке сеанса, а не в журнале: после выхода из системы их нет."""

from __future__ import annotations

from jericho.core.agent.entities import AgentReply
from jericho.core.services.adapters.json_file import JsonStateFile


class ReplyVault:
    """Последние ответы фраз, тронувших личные данные: `{run: {"message", "body"}}`. Журнал фраз хранит только memo.

    Окно на панели показывает отсюда полный ответ, пока сеанс жив. Файл — в `$XDG_RUNTIME_DIR` (оперативная
    память, только владелец): переписка не оседает на диске.
    """

    KEEP = 10
    FILE = "private-replies.json"      # в `$XDG_RUNTIME_DIR` проекта

    def __init__(self, file: JsonStateFile) -> None:
        self._file = file

    def keep(self, run: str, reply: AgentReply) -> None:
        replies = self._read()
        replies.pop(run, None)
        replies[run] = {"message": reply.message, "body": reply.body}
        self._file.write(dict(list(replies.items())[-self.KEEP :]))

    def get(self, run: str) -> tuple[str, str] | None:
        found = self._read().get(run)
        return (str(found.get("message", "")), str(found.get("body", ""))) if isinstance(found, dict) else None

    def latest(self) -> tuple[str, str] | None:
        """Последний сохранённый ответ: на него, скорее всего, и отвечает следующая фраза («отправь», «нет»)."""
        replies = self._read()
        if not replies:
            return None
        found = replies[list(replies)[-1]]
        return (str(found.get("message", "")), str(found.get("body", ""))) if isinstance(found, dict) else None

    def _read(self) -> dict[str, dict[str, object]]:
        return self._file.read(lambda raw: dict(raw) if isinstance(raw, dict) else {}, {})
