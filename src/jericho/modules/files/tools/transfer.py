"""Копировать и переместить: несколько путей за раз, «да» — только если что-то затирается."""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from typing import ClassVar

from pydantic import Field

from jericho.core.tools.description import ToolDescription
from jericho.core.tools.request import ToolRequest
from jericho.core.tools.result import ToolRefusal, ToolResult
from jericho.core.tools.risk import Approval, Risk
from jericho.core.tools.tool import Tool
from jericho.modules.files.access import FileAccess
from jericho.modules.files.entities import Kind, Place, shown
from jericho.modules.files.errors import AlreadyExists


@dataclass(frozen=True, slots=True)
class Step:
    """Один перенос: откуда, куда и затирает ли он файл на месте цели."""

    source: Place
    target: Place
    overwrites: bool


class TransferPlan:
    """Раскладывает просьбу «эти пути — туда» на шаги и проверяет их все до того, как что-то сделано.

    Цель — существующая папка: каждый путь ложится внутрь под своим именем. Иначе путь один, и цель — его новое
    имя. Папки не сливаются: если на месте цели уже папка, это отказ, а не слияние.
    """

    SAME = "same_place"
    INTO_ITSELF = "into_itself"
    NOT_A_DIRECTORY = "target_not_a_directory"
    DUPLICATE = "duplicate_names"

    def __init__(self, access: FileAccess) -> None:
        self._access = access

    def steps(self, sources: Sequence[str], target: str, *, moving: bool) -> list[Step]:
        destination = self._access.place(target, write=True)
        into = destination.path.is_dir()
        if not into and len(sources) > 1:
            raise ToolRefusal(self.NOT_A_DIRECTORY, target=destination.shown())
        steps = [self._step(self._access.place(raw, whole=True, remove=moving), destination, into) for raw in sources]
        targets = [step.target.path for step in steps]
        if len(set(targets)) < len(targets):
            raise ToolRefusal(self.DUPLICATE, target=destination.shown())
        return steps

    def _step(self, source: Place, destination: Place, into: bool) -> Step:
        kind = self._access.filesystem.entry(source.path).kind      # нет источника — not_found
        target = self._access.place(str(destination.path / source.path.name), write=True) if into else destination
        if target.path == source.path:
            raise ToolRefusal(self.SAME, path=source.shown())
        if target.path.is_relative_to(source.path):
            raise ToolRefusal(self.INTO_ITSELF, source=source.shown(), target=target.shown())
        if not target.path.exists():
            return Step(source, target, overwrites=False)
        if kind is not Kind.FILE or target.path.is_dir():
            raise AlreadyExists(target.shown())       # папку на месте папки не заменяем и не сливаем
        return Step(source, target, overwrites=True)


class TransferRequest(ToolRequest):
    sources: list[str] = Field(min_length=1, max_length=50, description="Что: файлы и папки. Путь абсолютный или от первого корня.")
    target: str = Field(
        min_length=1,
        max_length=1000,
        description="Куда: существующая папка — всё ляжет в неё под своими именами; иначе (путь один) — новое имя.",
    )


class _Transfer(Tool[TransferRequest]):
    """Общее у копирования и перемещения: план, «да» на затирание, прежние версии затёртых файлов."""

    risk = Risk.EFFECT
    approval = Approval.TOOL      # спрашивает сама и только когда затирает: без этого действие поправимо
    request_type = TransferRequest
    _moving = False
    _verb = ""
    _NOTES: ClassVar[dict[str, str]] = {"replaces": "заменятся", "untrusted": "из загрузок"}     # приписки к вопросу

    def __init__(self, access: FileAccess) -> None:
        self._access = access
        self._plan = TransferPlan(access)

    def _run(self, request: TransferRequest) -> ToolResult:
        steps = self._plan.steps(request.sources, request.target, moving=self._moving)
        self._ask(request, steps)
        previous = [kept for step in steps if step.overwrites and (kept := self._access.keep_version(step.target))]
        for step in steps:
            self._act(step)
        return ToolResult.success(
            done=[{"from": step.source.shown(), "to": step.target.shown()} for step in steps],
            **({"previous": previous} if previous else {}),
        )

    def _ask(self, request: TransferRequest, steps: Sequence[Step]) -> None:
        """«Да» нужно всегда, когда что-то заменится или файлы из загрузок станут «своими» (как у распаковки):
        иначе чужой файл перенесли бы в доверенную папку и прочли без пометки (ревью 02.11.2026, П3a №3).
        Без этого — только если в фразе читали чужой текст."""
        arguments, summary = request.model_dump(), self._summary(steps)
        overwritten = [step.target.shown() for step in steps if step.overwrites]
        adopted = [step.source.shown() for step in steps if self._adopts(step)]
        if not overwritten and not adopted:
            self._access.ask_if_foreign(self.name, arguments, summary, [step.target.shown() for step in steps])
            return
        details = {name: paths for name, paths in (("replaces", overwritten), ("untrusted", adopted)) if paths}
        notes = [f"{self._NOTES[name]}: {', '.join(paths[:5])}" for name, paths in details.items()]
        self._access.ask(self.name, arguments, "; ".join([summary, *notes]), [overwritten, adopted], **details)

    def _adopts(self, step: Step) -> bool:
        """Из ненадёжного корня (или папки, где он лежит) — в надёжный."""
        return self._access.guard.untrusted(step.source) and not step.target.root.untrusted

    def _summary(self, steps: Sequence[Step]) -> str:
        """Что услышит пользователь: «переместить план.md → ~/Загрузки» или «скопировать 7 (план.md, …) → ~/Архив»."""
        names = [step.source.path.name for step in steps]
        where = steps[0].target.path.parent if len(steps) > 1 else steps[0].target.path
        what = names[0] if len(names) == 1 else f"{len(names)} ({', '.join(names[:3])}{', …' if len(names) > 3 else ''})"
        return f"{self._verb} {what} → {shown(where)}"

    @abstractmethod
    def _act(self, step: Step) -> None: ...


class Copy(_Transfer):
    name = "copy"
    _verb = "скопировать"
    description = ToolDescription(
        when="просят скопировать файлы или папки.",
        does=(
            "копирует файлы и папки целиком. В существующую папку — под прежними именами; один путь в новое место — "
            "под новым именем. Файл на месте цели заменяется только после «да»; его прежняя версия сохраняется."
        ),
        returns='{"ok": true, "done": [{"from", "to"}], "previous": копии заменённых файлов}.',
        refusals=(
            "needs_confirm (что-то заменится, файлы из загрузок или в фразе читали чужой текст — спроси пользователя), "
            "already_exists (на месте цели папка — не сливаю), target_not_a_directory (путей несколько, а цели-папки нет), "
            "duplicate_names, same_place, into_itself, not_found, outside_roots, forbidden_path, read_only_root, "
            "protected_path (внутри папки — файлы самого ассистента: назови пользователю inside, возьми нужное по отдельности)."
        ),
    )

    def _act(self, step: Step) -> None:
        self._access.changer.make_dir(step.target.path.parent)
        self._access.changer.copy(step.source.path, step.target.path)


class Move(_Transfer):
    name = "move"
    _moving = True
    _verb = "переместить"
    description = ToolDescription(
        when="просят переместить или переименовать файлы и папки.",
        does=(
            "перемещает или переименовывает. В существующую папку — под прежними именами; один путь в новое место — "
            "под новым именем. Файл на месте цели заменяется только после «да»; его прежняя версия сохраняется."
        ),
        returns='{"ok": true, "done": [{"from", "to"}], "previous": копии заменённых файлов}.',
        refusals=(
            "needs_confirm (что-то заменится, файлы из загрузок или в фразе читали чужой текст — спроси пользователя), "
            "already_exists, target_not_a_directory, duplicate_names, same_place, into_itself, not_found, outside_roots, "
            "forbidden_path, read_only_root (в том числе внутри папки), protected_path (внутри — файлы самого ассистента)."
        ),
    )

    def _act(self, step: Step) -> None:
        self._access.changer.make_dir(step.target.path.parent)
        self._access.changer.move(step.source.path, step.target.path)
