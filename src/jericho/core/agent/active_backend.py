"""Кто из бэкендов модели сейчас ведёт фразу — чтобы политика риска знала, кому уходят личные данные."""

from __future__ import annotations

from collections.abc import Mapping


class ActiveBackend:
    """Имя бэкенда, который ведёт фразу (`claude_cli`, `openai_api`); пусто — модели в цепочке нет: вызов составил человек
    (команда в терминале, кнопка сценария).

    В процессе фразы имя ставит цепочка бэкендов (`FallbackBackend`) перед каждым ответом — так видно, что ответ
    перешёл к запасному. Сервер ручек — отдельный процесс; его бэкенд передаёт имя переменной окружения.

    `main` — основной бэкенд цепочки (с учётом выбранной вручную модели): ему личные данные можно, когда проект
    не назвал доверенных (`agent.private_backends`). Ставит сборка агента; серверу ручек — тоже через окружение.
    """

    VARIABLE = "JERICHO_BACKEND"
    MAIN_VARIABLE = "JERICHO_MAIN_BACKEND"

    def __init__(self, name: str = "", main: str = "") -> None:
        self.name = name
        self.main = main

    @classmethod
    def from_environment(cls, environment: Mapping[str, str]) -> ActiveBackend:
        return cls(environment.get(cls.VARIABLE, ""), environment.get(cls.MAIN_VARIABLE, ""))
