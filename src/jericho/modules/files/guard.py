"""Охрана путей — единственное место, где решается, можно ли ассистенту трогать этот путь."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from fnmatch import fnmatch
from pathlib import Path

from jericho.core.tools.result import ToolRefusal
from jericho.modules.files.entities import Place, Root, shown


class PathGuard:
    """Превращает путь от модели в проверенное место — или отказывает.

    Путь раскрывается (`~`), относительный считается от первого корня, затем `resolve()` снимает `..` и символьные
    ссылки: ссылка внутри корня, ведущая наружу, наружу и проверяется. Итог обязан лежать внутри корня и ни одной
    своей частью ниже корня не совпадать с запретным образцом. Ручки строят пути только через охрану.

    Защищённые папки — сам ассистент: его состояние (журнал, ожидающее «да», токены), сеансы всех пользователей,
    файлы машины, папка обмена с транспортом, его код и код каркаса. Внутрь них нельзя ни читать, ни писать при
    любых корнях. Действие над папкой целиком (скопировать, упаковать, переместить, удалить) получает отказ, если
    защищённое лежит внутри: копия родителя унесла бы журнал и личные ответы туда, где их читают обычные ручки
    (ревью 02.11.2026, П3a №1), а перенос — подделал бы «да» или расширил корни. Отказ, а не пропуск: молча
    неполная копия хуже понятного «нельзя». По той же причине папку, внутри которой корень только для чтения, нельзя
    убрать со своего места.

    Список защищённого — живой (`OwnPaths`): модули, собранные позже модуля файлов, добавляют свои папки.
    """

    NO_ROOTS = "no_roots"
    OUTSIDE_ROOTS = "outside_roots"
    FORBIDDEN = "forbidden_path"
    READ_ONLY = "read_only_root"
    PROTECTED = "protected_path"

    def __init__(self, roots: Sequence[Root], deny: Sequence[str], protected: Iterable[Path] = ()) -> None:
        self._roots = tuple(Root(root.path.expanduser().resolve(), root.read_only, root.untrusted) for root in roots)
        self._deny = tuple(pattern.casefold() for pattern in deny)
        self._protected = protected

    @property
    def roots(self) -> tuple[Root, ...]:
        return self._roots

    def place(self, raw: str, *, write: bool = False, whole: bool = False, remove: bool = False) -> Place:
        """Проверенное место для пути от модели. `write` — действие что-то меняет; `whole` — берёт папку со всем
        содержимым (скопировать, упаковать); `remove` — сам путь со всем содержимым уходит со своего места."""
        if not self._roots:
            raise ToolRefusal(self.NO_ROOTS, detail="работа с файлами не настроена: в разделе files нет корней")
        path = Path(raw).expanduser()
        path = (path if path.is_absolute() else self._roots[0].path / path).resolve()
        root = self._root_of(path)
        if root is None:
            raise ToolRefusal(self.OUTSIDE_ROOTS, path=shown(path), roots=[shown(root.path) for root in self._roots])
        if self._denied(path, root):
            raise ToolRefusal(self.FORBIDDEN, path=shown(path))
        self._refuse_own(path, whole or remove)
        if (write or remove) and root.read_only:
            raise ToolRefusal(self.READ_ONLY, path=shown(path), root=shown(root.path))
        if remove and (inner := self._read_only_below(path)) is not None:
            raise ToolRefusal(self.READ_ONLY, path=shown(path), root=shown(inner.path), detail="внутри корень только для чтения")
        return Place(path, root)

    def untrusted(self, place: Place) -> bool:
        """Есть ли в месте или под ним ненадёжный корень: копия такой папки уносит чужие файлы вместе со своими."""
        return place.root.untrusted or any(root.untrusted and root.path.is_relative_to(place.path) for root in self._roots)

    def allows(self, path: Path, root: Root) -> bool:
        """Показывать ли запись в списке или поиске: запретное модель не видит даже по имени."""
        resolved = path.resolve()
        inside_own = any(resolved.is_relative_to(own) for own in self._own())
        return resolved.is_relative_to(root.path) and not self._denied(resolved, root) and not inside_own

    def _own(self) -> tuple[Path, ...]:
        return tuple(path.expanduser().resolve() for path in self._protected)

    def _refuse_own(self, path: Path, whole: bool) -> None:
        """Путь внутри защищённого — или, когда действие берёт папку целиком, защищённое внутри пути."""
        for own in self._own():
            if path.is_relative_to(own):
                raise ToolRefusal(self.PROTECTED, path=shown(path), detail="здесь файлы самого ассистента — их он не трогает")
            if whole and own.is_relative_to(path):
                raise ToolRefusal(
                    self.PROTECTED, path=shown(path), inside=shown(own),
                    detail="внутри лежат файлы самого ассистента — папку целиком он не берёт; назови то, что в ней нужно",
                )

    def _read_only_below(self, path: Path) -> Root | None:
        return next((root for root in self._roots if root.read_only and root.path != path and root.path.is_relative_to(path)), None)

    def _root_of(self, path: Path) -> Root | None:
        """Самый глубокий корень, внутри которого путь: у вложенного корня могут быть свои пометки."""
        inside = [root for root in self._roots if path.is_relative_to(root.path)]
        return max(inside, key=lambda root: len(root.path.parts), default=None)

    def denied_name(self, name: str) -> bool:
        """Одна часть пути совпадает с запретным образцом — для имён, которых ещё нет на диске (записи архива)."""
        return any(fnmatch(name.casefold(), pattern) for pattern in self._deny)

    def _denied(self, path: Path, root: Root) -> bool:
        return any(self.denied_name(part) for part in path.relative_to(root.path).parts)
