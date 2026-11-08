"""Общая основа инструментов — того, что модель может вызвать."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import ClassVar

from jericho.core.tools.description import ToolDescription
from jericho.core.tools.private import PrivateFields
from jericho.core.tools.request import ToolRequest
from jericho.core.tools.result import ToolResult
from jericho.core.tools.risk import Approval, Risk


class Tool[RequestT: ToolRequest](ABC):
    """Инструмент: получает запрос от модели, возвращает ToolResult.

    Наследник объявляет о себе то, что ниже (обычно прямо в классе), и пишет одно действие — `_run`:

        name          как модель вызывает инструмент
        description   что модель о нём читает
        request_type  параметры — наследник ToolRequest: у каждого поля описание, ограничения — в объявлении
        risk          класс риска: READ, NAVIGATE, CHANGE или EFFECT. Объявить обязан каждый — проверка E008
        approval      только у EFFECT: кто спрашивает «да» — каркас перед каждым вызовом (ASK, умолчание) или сама
                      ручка, когда нужно (TOOL). Политику держит диспетчер (`core/tools/policy.py`)
        service       True у ручек, которые обслуживают работу, а не делают дело: загрузка навыка, заметки
        private       поля параметров и ответа с чужим или личным текстом (переписка, текст сообщения): в журнал
                      они не пишутся — там «скрыто: N знаков», модель в этой фразе получает их целиком. Такая
                      ручка кладёт в ответ `memo` — что сделано, без самого текста: его запомнит разговор
        outbound      True у ручек, которые могут унести данные наружу: открыть адрес, отправить, скачать, искать
                      в интернете. После личных данных в этой фразе такая ручка — только с «да» (политика риска)
        local         True у ручек, которые отдают модели содержимое файлов с машины пользователя. Если в той же
                      фразе модель читала и чужой текст, вынос наружу — только с «да»: внедрённая в страницу команда
                      не унесёт прочитанный файл в адресе ссылки
        proves        какое поле запроса какой вид заметки подтверждает: {"url": "address"}. Успешный вызов
                      с таким полем — единственное, что позволяет записать это значение в заметку
        relays        True у ручки, которая только передаёт другой, уже записанный вызов тому же диспетчеру (`confirm`):
                      предел пользователя проверяется у того вызова, а не у неё
        _run          само действие; не может продолжать — бросает ToolRefusal

    Про журнал, замер времени и превращение отказов в ответ ручка не знает: это слои вокруг вызова
    (`core/tools/middleware.py`), их список — `TOOL_MIDDLEWARE` в настройках.
    Интерфейсы (MCP-сервер, командная строка) берут имя, описание и параметры отсюда и ничего не дописывают.
    """

    name: str
    description: ToolDescription
    request_type: type[ToolRequest]
    risk: Risk = Risk.EFFECT      # умолчание — самое строгое: забытый класс не делает ручку безобидной
    approval: Approval = Approval.ASK     # умолчание — самое строгое: «да» перед каждым вызовом
    service: bool = False
    private: ClassVar[tuple[str, ...]] = ()
    outbound: ClassVar[bool] = False
    local: ClassVar[bool] = False
    proves: ClassVar[Mapping[str, str]] = {}
    relays: ClassVar[bool] = False
    skill: str = ""     # какому навыку принадлежит ручка; проставляет ядро, у ручек самого ядра пусто
    in_prompt: bool = False     # руководство навыка уже в общем промпте (`PRELOADED_SKILLS`): модель видит полное описание

    def execute(self, request: RequestT) -> ToolResult:
        """Само действие, без слоёв: отказ вылетает исключением. Вызывает диспетчер — он оборачивает вызов слоями."""
        return self._run(request)

    def consent_summary(self, arguments: Mapping[str, object]) -> str:
        """Что пользователь услышит в вопросе, когда «да» спрашивает каркас. Ручка может сказать это по-человечески.

        Личные поля — скрыты: вопрос попадает в журнал и в напоминания.
        """
        shown = PrivateFields(self.private).mask(arguments)
        return f"{self.name} {json.dumps(shown, ensure_ascii=False, sort_keys=True)}"

    def private_in(self, result: ToolResult) -> tuple[str, ...]:
        """Какие поля этого ответа личные. Обычно — `private`; ручка, отдающая ответ другой (`confirm`), — её поля."""
        return self.private

    @property
    def destructive(self) -> bool:
        """Подсказка для модели в протоколе: действие нельзя отменить одной командой."""
        return self.risk is Risk.EFFECT

    @property
    def read_only(self) -> bool:
        return self.risk is Risk.READ

    @abstractmethod
    def _run(self, request: RequestT) -> ToolResult: ...
