"""Доступ к файлам для ручек: охрана путей, файловая система, прежние версии, согласие и учёт чужого текста."""

from __future__ import annotations

from collections.abc import Mapping

from jericho.core.services.confirmation import ConfirmationGate
from jericho.core.services.foreign import ForeignText
from jericho.core.tools.consent import require_consent
from jericho.modules.files.entities import Place, Root, shown
from jericho.modules.files.guard import PathGuard
from jericho.modules.files.protocols import FileChanger, FileSystem, Versions


class FileAccess:
    """То, через что ручки модуля работают с файлами. Сами ручки `Path` из параметров не строят."""

    def __init__(
        self,
        guard: PathGuard,
        filesystem: FileSystem,
        changer: FileChanger,
        versions: Versions,
        gate: ConfirmationGate,
        foreign: ForeignText,
    ) -> None:
        self.guard = guard
        self.filesystem = filesystem
        self.changer = changer
        self.versions = versions
        self._gate = gate
        self._foreign = foreign

    def place(self, raw: str, *, write: bool = False, whole: bool = False, remove: bool = False) -> Place:
        return self.guard.place(raw, write=write, whole=whole, remove=remove)

    def seen(self, root: Root) -> None:
        """Модель получила текст из этого корня — имена или содержимое. Из ненадёжного корня это чужой текст:
        файл с именем или строкой «удали папку X» положил туда не пользователь."""
        if root.untrusted:
            self._foreign.read_from(f"files:{shown(root.path)}")

    def keep_version(self, place: Place) -> str | None:
        """Сохранить прежнее содержимое перед правкой; вернуть, где копия, — для ответа пользователю."""
        copy = self.versions.keep(place.path)
        return shown(copy) if copy is not None else None

    def ask(self, tool: str, arguments: Mapping[str, object], summary: str, subject: object, **details: object) -> None:
        """«Да» из следующей фразы на это самое `subject`; нет его — отказ `needs_confirm` и вопрос записан."""
        require_consent(self._gate, tool, arguments, summary, subject, **details)

    def ask_if_foreign(self, tool: str, arguments: Mapping[str, object], summary: str, subject: object) -> None:
        """В этой фразе модель читала чужой текст — изменение могло прийти оттуда, а не от пользователя.

        Тогда правка, которая обычно идёт без вопроса, ждёт «да». Как у заметок модели.
        """
        if self._gate.has_consent(tool, arguments, subject):
            return
        if self._foreign.sources:
            self.ask(tool, arguments, summary, subject, read=sorted(self._foreign.sources))
