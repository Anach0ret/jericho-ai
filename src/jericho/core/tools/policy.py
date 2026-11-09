"""Политика риска: что каркас разрешает ручке в зависимости от её класса и от того, кто рядом.

Это не слой из `TOOL_MIDDLEWARE`, а часть диспетчера: проект может переставлять и добавлять слои,
но убрать политику настройками нельзя.

| Класс | Человек рядом | Без человека (задача по расписанию) |
|---|---|---|
| READ, NAVIGATE, CHANGE | выполняется | выполняется |
| EFFECT, approval=ASK | только после «да» в следующей фразе | отказ `nobody_to_ask`, если ручка не названа в `unattended_effects` |
| EFFECT, approval=TOOL | ручка сама спрашивает, когда нужно | отказ `nobody_to_ask`, если ручка не названа в `unattended_effects` |
| любая с `private` (личные данные) или `local` (файлы с машины) | только если фразу ведёт бэкенд из `agent.private_backends` (не назван — основной) или модели в цепочке нет | так же |
| выше предела пользователя (`user_risk`, `default_user_risk`) | отказ `not_allowed_for_user` — «да» не снимает | так же |
| `outbound` после личных данных в этой фразе | только после «да»: внедрённая в переписку команда не унесёт её в адресе ссылки | отказ `nobody_to_ask` |
| `outbound` после файлов с машины (`local`) и чужого текста в этой фразе | только после «да»: команда со страницы не унесёт прочитанный файл | отказ `nobody_to_ask` |

У `outbound` класса EFFECT вопрос задаёт строка про EFFECT — с той же пометкой «читалась личная переписка». Ручка
EFFECT с `Approval.TOOL` спрашивает сама и обязана спрашивать **всегда**, если выносит наружу (как `tg_send`): спросить
за неё каркас не может, не задав вопрос дважды.

«Вхолостую» политика та же: меняющие команды и так не выполняются, а вопросы задаются как обычно.

Каждая строка таблицы — своё правило (`Rule`), по порядку: первое, которое решило, заканчивает проверку. Новое
правило — новый класс в списке, а не ещё одна ветка в общем методе.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from enum import Enum
from typing import Protocol

from jericho.core.agent.active_backend import ActiveBackend
from jericho.core.services.confirmation import ConfirmationGate
from jericho.core.services.foreign import ForeignText
from jericho.core.tools.consent import require_consent
from jericho.core.tools.dispatcher import ToolCall
from jericho.core.tools.result import ToolRefusal
from jericho.core.tools.risk import Approval, Risk

NOBODY_TO_ASK = "nobody_to_ask"
PRIVATE_NOTE = " (в этой фразе читалась личная переписка)"
LOCAL_NOTE = " (в этой фразе читались файлы с машины и чужой текст)"


def exposure(call: ToolCall, foreign: ForeignText) -> str:
    """Что в этой фразе может утечь через вынос наружу — пометка для вопроса «да»; пусто — нечему."""
    if call.session.private_read:
        return PRIVATE_NOTE
    if call.session.local_read and foreign.sources:
        return LOCAL_NOTE
    return ""


class Verdict(Enum):
    NEXT = "next"         # правилу нечего сказать — решают следующие
    ADMIT = "admit"       # решено: выполнять (отказ правило бросает само — `ToolRefusal`)


class Rule(Protocol):
    def check(self, call: ToolCall) -> Verdict:
        """Пропустить, передать дальше или отказать (`ToolRefusal`)."""
        ...


class UserCeiling:
    """Выше предела того, чьё это поручение (`user_risk`) — отказ; «да» его не снимает.

    `confirm` (`relays`) сам по себе — EFFECT, и предел NAVIGATE запрещал подтвердить разрешённый переход (ревью
    02.11.2026, П1 №5). Его пропускаем: подтверждённый вызов идёт через тот же диспетчер, и предел проверяется у него.
    """

    NOT_ALLOWED = "not_allowed_for_user"

    def __init__(self, ceiling: Risk | None) -> None:
        self._ceiling = ceiling      # None — без предела (ассистент одного человека)

    def check(self, call: ToolCall) -> Verdict:
        if self._ceiling is not None and not call.tool.relays and call.tool.risk.rank > self._ceiling.rank:
            raise ToolRefusal(
                self.NOT_ALLOWED, risk=call.tool.risk.value, allowed=self._ceiling.value,
                detail="этому пользователю такое действие не разрешено — скажи об этом; «да» тут не поможет",
            )
        return Verdict.NEXT


class TrustedModel:
    """Личные данные (`Tool.private`) и файлы с машины (`Tool.local`) — только бэкендам из `agent.private_backends`;
    список не назван — только основному бэкенду цепочки. Файлы — с 0.64.17: при сбое основной модели содержимое
    `~/Документы` уходило запасной (бесплатной, может учиться на данных) — аудит 27.10.2026, находка 5. Запасной (часто бесплатный, может учиться на переписке) — только если проект назвал его
    явно: раньше без списка разрешалось любому, а README обещал обратное (ревью 02.11.2026, П5 №7; решение владельца).
    Вызов без модели в цепочке (человек в терминале, кнопка сценария) пропускается: данные остаются на машине."""

    UNTRUSTED_MODEL = "private_needs_trusted_model"

    def __init__(self, private_backends: Iterable[str] | None, active: ActiveBackend) -> None:
        self._named = frozenset(private_backends) if private_backends is not None else None     # None — основной
        self._active = active

    def check(self, call: ToolCall) -> Verdict:
        name = self._active.name
        trusted = self._named if self._named is not None else {self._active.main}
        if not (call.tool.private or call.tool.local) or not name or name in trusted:
            return Verdict.NEXT
        what = "личные данные" if call.tool.private else "файлы с машины"
        raise ToolRefusal(
            self.UNTRUSTED_MODEL, backend=name,
            detail=f"{what} не отдаю модели {name}: скажи, что это сделаешь, когда снова будет основная модель",
        )


class OutboundAfterPrivate:
    """Ссылка из сообщения может нести в адресе пересказ переписки: открыть её — значит отдать его сайту. Поэтому
    после личных данных всё, что выносит наружу и обычно не спрашивает, — с «да». Так же после файлов с машины,
    если в фразе был и чужой текст: команда со страницы («прочитай ~/…/key и открой адрес …») — та же утечка.
    EFFECT спрашивает и так (правило ниже, с той же пометкой в вопросе)."""

    def __init__(self, gate: ConfirmationGate, foreign: ForeignText) -> None:
        self._gate = gate
        self._foreign = foreign

    def check(self, call: ToolCall) -> Verdict:
        note = exposure(call, self._foreign)
        if not call.tool.outbound or not note or call.tool.risk is Risk.EFFECT:
            return Verdict.NEXT
        if not self._gate.attended:
            raise ToolRefusal(NOBODY_TO_ASK, detail="после личных данных или файлов выносить наружу без «да» нельзя, а спросить некого")
        require_consent(self._gate, call.tool.name, call.arguments, call.tool.consent_summary(call.arguments) + note)
        return Verdict.ADMIT


class EffectNeedsYes:
    """EFFECT — только после «да» в следующей фразе; без человека — только ручки из `unattended_effects`.
    `Approval.TOOL` — ручка спрашивает сама, когда нужно (её «да» точнее: она знает, что именно тронет)."""

    def __init__(self, gate: ConfirmationGate, unattended_effects: Iterable[str], foreign: ForeignText) -> None:
        self._gate = gate
        self._unattended = frozenset(unattended_effects)    # ручки EFFECT, которым проект разрешил действовать без человека
        self._foreign = foreign

    def check(self, call: ToolCall) -> Verdict:
        tool = call.tool
        if tool.risk is not Risk.EFFECT:
            return Verdict.ADMIT
        if not self._gate.attended:
            if tool.name in self._unattended:
                return Verdict.ADMIT
            raise ToolRefusal(
                NOBODY_TO_ASK, detail="рядом никого нет, а действие с последствиями без «да» не выполняется; скажи об этом в ответе"
            )
        if tool.approval is Approval.TOOL:
            return Verdict.ADMIT
        note = exposure(call, self._foreign) if tool.outbound else ""
        require_consent(self._gate, tool.name, call.arguments, tool.consent_summary(call.arguments) + note)
        return Verdict.ADMIT


class RiskPolicy:
    """Правила по порядку таблицы выше. Собирается из настроек проекта; набор правил — дело каркаса."""

    NOBODY_TO_ASK = NOBODY_TO_ASK
    UNTRUSTED_MODEL = TrustedModel.UNTRUSTED_MODEL
    NOT_ALLOWED = UserCeiling.NOT_ALLOWED

    def __init__(
        self, gate: ConfirmationGate, unattended_effects: Iterable[str] = (),
        private_backends: Iterable[str] | None = None, active: ActiveBackend | None = None, ceiling: Risk | None = None,
        foreign: ForeignText | None = None,
    ) -> None:
        foreign = foreign or ForeignText()
        self._rules: Sequence[Rule] = (
            UserCeiling(ceiling),
            TrustedModel(private_backends, active or ActiveBackend()),
            OutboundAfterPrivate(gate, foreign),
            EffectNeedsYes(gate, unattended_effects, foreign),
        )

    def admit(self, call: ToolCall) -> None:
        """Пропускает вызов или отказывает. Параметры к этому времени уже проверены."""
        for rule in self._rules:
            if rule.check(call) is Verdict.ADMIT:
                return
