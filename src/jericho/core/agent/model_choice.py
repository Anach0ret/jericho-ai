"""Выбранная вручную модель: держится в файле состояния, пока не вернут «по умолчанию»."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from jericho.core.conf.settings import ModelChoice, Settings, SettingsSection
from jericho.core.services.adapters.json_file import JsonStateFile

logger = logging.getLogger(__name__)


class ModelChoiceFile:
    """`{"choice": <имя из agent.models>}`. Нет файла — модель по умолчанию, как в настройках."""

    def __init__(self, path: Path) -> None:
        self._file = JsonStateFile(path)

    def current(self) -> str | None:
        return self._file.read(lambda raw: raw.get("choice") if isinstance(raw, dict) and isinstance(raw.get("choice"), str) else None, None)

    def choose(self, name: str) -> None:
        self._file.write({"choice": name})

    def reset(self) -> None:
        self._file.remove()


@dataclass(frozen=True, slots=True)
class ModelChoices:
    """Выбор модели поверх настроек проекта. `backend_name` — имя раздела настроек бэкенда по его пакету;
    `default_section` — его раздел по умолчанию, когда проект раздела не объявил (None — раздела у бэкенда нет)."""

    settings: Settings
    backend_name: Callable[[str], str]
    default_section: Callable[[str], SettingsSection | None] = lambda package: None

    @property
    def choices(self) -> dict[str, ModelChoice]:
        return dict(self.settings.agent.models)

    def default(self) -> str | None:
        """Пункт, совпадающий с настройками проекта: основной бэкенд и его модель. None — такого пункта нет."""
        agent = self.settings.agent
        return next((name for name, choice in self.choices.items() if choice.backend == agent.backend and self._model_of(choice) == self._configured_model(agent.backend)), None)

    def applied(self, chosen: str | None) -> Settings:
        """Настройки, в которых выбранная модель — основная, а прежняя цепочка бэкендов — запасная, без повторов."""
        choice = self.choices.get(chosen) if chosen else None
        if chosen and choice is None:
            logger.warning("model_choice_unknown", extra={"data": {"choice": chosen, "known": sorted(self.choices)}})
        if choice is None:
            return self.settings
        agent = self.settings.agent
        chain = tuple(dict.fromkeys(backend for backend in (agent.backend, *agent.fallback_backends) if backend != choice.backend))
        update: dict[str, object] = {"agent": agent.model_copy(update={"backend": choice.backend, "fallback_backends": chain})}
        if choice.model:
            name = self.backend_name(choice.backend)
            update[name] = self._section(name, choice.backend).model_copy(update={"model": choice.model})
        return self.settings.model_copy(update=update)

    def _section(self, name: str, backend: str) -> SettingsSection:
        """Раздел бэкенда из настроек — или его умолчания: раздел необязателен, и без него выбор ломал сборку (П2 №10)."""
        section = getattr(self.settings, name, None) or self.default_section(backend)
        if not isinstance(section, SettingsSection):
            raise ValueError(f"agent.models: backend {name} has no settings with a model — remove `model` from its choice")
        return section

    def _model_of(self, choice: ModelChoice) -> str:
        return choice.model or self._configured_model(choice.backend)

    def _configured_model(self, backend: str) -> str:
        section = getattr(self.settings, self.backend_name(backend), None)
        model = getattr(section, "model", "")
        return model if isinstance(model, str) else ""
