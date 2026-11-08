"""Сборка настроек: класс проекта + файлы этой машины → один проверенный объект."""

from __future__ import annotations

import tomllib
from collections.abc import Mapping, Sequence
from importlib import import_module
from pathlib import Path
from typing import Any, cast

from pydantic import ValidationError

from jericho.core.conf.settings import Settings


class SettingsError(Exception):
    """Настройки не собрались: нет такого варианта, файл не читается или значение не проходит проверку."""


class SettingsLoader:
    """Берёт вариант настроек из модуля проекта и накладывает на него файлы машины.

    Файлы накладываются по порядку, отсутствующий пропускается. Итог проверяется после каждого файла —
    так в ошибке назван файл, который её внёс.
    """

    def __init__(self, module: str, configuration: str, files: Sequence[Path] = ()) -> None:
        self._module = module
        self._configuration = configuration
        self._files = tuple(files)

    def load(self) -> Settings:
        settings = self._effective()
        self._require_own_state(settings)
        return settings

    def _effective(self) -> Settings:
        """Вариант с наложенными файлами машины — то, с чем ассистент работает на самом деле."""
        settings_class = self._settings_class()
        settings = self._checked(settings_class, {}, source=f"{self._module}.{self._configuration}")
        for file in self._files:
            if file.exists():
                merged = self._merge(settings.model_dump(), self._read(file))
                settings = self._checked(settings_class, merged, source=str(file))
        return settings

    def _require_own_state(self, settings: Settings) -> None:
        """Вариант «вхолостую» не делит папки состояния с рабочим: иначе пробный вопрос затёр бы настоящий.

        Сравниваются **итоговые** настройки — с теми же файлами машины. Общий `local.toml` со своим `state_name`
        иначе свёл бы рабочий и пробный варианты в одну папку незаметно для проверки (ревью R07).
        """
        if not settings.dry_run:
            return
        others = {name: SettingsLoader(self._module, name, self._files)._effective() for name in self.configurations(self._module)}
        working = sorted(name for name, other in others.items() if not other.dry_run and other.state_name == settings.state_name)
        if working:
            raise SettingsError(
                f"{self._module}.{self._configuration}: dry_run shares state_name '{settings.state_name}' with "
                f"{', '.join(working)}; give the dry configuration its own state_name"
            )

    @classmethod
    def configurations(cls, module: str) -> tuple[str, ...]:
        """Варианты настроек, объявленные в модуле проекта."""
        return tuple(sorted(name for name, value in vars(import_module(module)).items() if cls._is_configuration(value)))

    def _settings_class(self) -> type[Settings]:
        settings_class = getattr(import_module(self._module), self._configuration, None)
        if not (isinstance(settings_class, type) and issubclass(settings_class, Settings)):
            available = ", ".join(self.configurations(self._module))
            raise SettingsError(f"{self._module}: no configuration '{self._configuration}', available: {available}")
        return settings_class

    @staticmethod
    def _is_configuration(value: object) -> bool:
        return isinstance(value, type) and issubclass(value, Settings) and value is not Settings

    @staticmethod
    def _read(file: Path) -> dict[str, Any]:
        try:
            return tomllib.loads(file.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as error:
            raise SettingsError(f"{file}: {error}") from error

    @staticmethod
    def _checked(settings_class: type[Settings], values: Mapping[str, Any], source: str) -> Settings:
        try:
            return settings_class.model_validate(values)
        except ValidationError as error:
            problems = "; ".join(
                f"{'.'.join(str(part) for part in problem['loc'])}: {problem['msg']}" for problem in error.errors()
            )
            raise SettingsError(f"{source}: {problems}") from error

    def _merge(self, base: dict[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
        """Словари сливаются вглубь, всё остальное заменяется целиком."""
        merged = dict(base)
        for key, value in override.items():
            current = merged.get(key)
            if isinstance(current, dict) and isinstance(value, Mapping):
                value = self._merge(cast(dict[str, Any], current), cast(Mapping[str, Any], value))
            merged[key] = value
        return merged
