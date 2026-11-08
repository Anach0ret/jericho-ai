"""Что каркасу нужно знать о проекте, чтобы собраться: какой это проект, чем запускается и откуда берёт настройки.

Проект — ассистент, собранный на каркасе: свой модуль настроек и свои навыки. Каркас узнаёт о нём одним способом —
из переменной окружения `JERICHO_SETTINGS_MODULE`, как Django из `DJANGO_SETTINGS_MODULE`. Остальное выводится
из имени модуля; ни одного пути каркас не считает от собственной папки, кроме своих же текстов.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from importlib.util import find_spec
from pathlib import Path

from jericho.core.conf.loader import SettingsLoader
from jericho.core.conf.settings import Settings
from jericho.core.services.paths import UserDirs
from jericho.core.services.phrase_deadline import PhraseDeadline
from jericho.core.services.program import Program


class InstallationError(Exception):
    """Проект не назван или его пакет не находится."""


@dataclass(frozen=True, slots=True)
class Installation:
    settings_module: str               # «home.settings»: варианты настроек проекта — классы в этом модуле
    machine_files: tuple[Path, ...]    # настройки этой машины и секреты; вне git
    launch: tuple[str, ...]            # как запустить Jericho ещё раз: так бэкенд поднимает сервер ручек
    environment: Mapping[str, str]
    home: Path

    SETTINGS_VARIABLE = "JERICHO_SETTINGS_MODULE"      # какой проект собирать
    CONFIG_VARIABLE = "JERICHO_CONFIG_DIR"             # где файлы этой машины; не задано — ~/.config/<имя проекта>
    CONFIGURATION_VARIABLE = "JERICHO_CONFIGURATION"   # какой вариант его настроек взять
    RUN_VARIABLE = Program.RUN_VARIABLE                # запуск, которому служит этот процесс: сервер ручек получает его от фразы
    UNATTENDED_VARIABLE = "JERICHO_UNATTENDED"         # «1» — рядом никого нет: спросить и подтвердить некому
    USER_VARIABLE = "JERICHO_USER"                     # чьё поручение: у каждого пользователя своё «да» и свой разговор
    USER_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,64}")  # имя пользователя становится именем папки
    DEFAULT_CONFIGURATION = "Live"
    EVAL_CONFIGURATION = "Eval"                        # в этом варианте идёт прогон проверочных фраз
    EVALS_FILE = "evals.md"                            # проверочные фразы навыка лежат в его папке под этим именем

    @classmethod
    def discover(cls, environment: Mapping[str, str], home: Path, executable: str) -> Installation:
        """Проект, названный в окружении. Файлы машины — в `~/.config/<имя проекта>/` либо там, где сказано."""
        settings_module = environment.get(cls.SETTINGS_VARIABLE, "")
        if not settings_module:
            raise InstallationError(
                f"{cls.SETTINGS_VARIABLE} is not set: name the settings module of the assistant, for example home.settings"
            )
        name = cls._program(cls._project_package(settings_module))
        named = environment.get(cls.CONFIG_VARIABLE)
        config_dir = Path(named).expanduser() if named else UserDirs.find(environment, home).config / name
        return cls(
            settings_module=settings_module,
            machine_files=(config_dir / "local.toml", config_dir / "secrets.toml"),
            launch=(executable, "-m", "jericho"),
            environment=environment,
            home=home,
        )

    @staticmethod
    def _project_package(settings_module: str) -> str:
        """Пакет проекта — тот, в котором лежит модуль настроек: `home.settings` → `home`."""
        return settings_module.rpartition(".")[0] or settings_module

    @staticmethod
    def _program(project_package: str) -> str:
        """Имя команды проекта — последняя часть имени пакета: `acme.helper` → `helper`."""
        return project_package.rpartition(".")[2]

    @property
    def program(self) -> str:
        """Как называется команда проекта: им подписаны его таймеры, уведомления и подсказки."""
        return self._program(self.project_package)

    @property
    def configuration(self) -> str:
        return self.environment.get(self.CONFIGURATION_VARIABLE) or self.DEFAULT_CONFIGURATION

    @property
    def attended(self) -> bool:
        """Есть ли рядом человек. Запуск без него (задача по расписанию) отмечается в окружении, а не в аргументах:
        так отметку получает и сервер ручек, который поднимает бэкенд."""
        return self.environment.get(self.UNATTENDED_VARIABLE) != "1"

    @property
    def user(self) -> str:
        """Пользователь этого запуска; пусто — ассистент одного человека (рабочий стол)."""
        user = self.environment.get(self.USER_VARIABLE, "")
        if user and not self.USER_PATTERN.fullmatch(user):
            raise InstallationError(f"{self.USER_VARIABLE}: '{user}' — latin letters, digits, '-' and '_' only")
        return user

    @property
    def config_dir(self) -> Path:
        """Папка файлов этой машины."""
        return self.machine_files[0].parent

    @property
    def user_config_home(self) -> Path:
        return self.dirs.config

    @property
    def dirs(self) -> UserDirs:
        """Стандартные места ОС для файлов пользователя — с учётом окружения этого запуска."""
        return UserDirs.find(self.environment, self.home)

    @property
    def project_package(self) -> str:
        return self._project_package(self.settings_module)

    @property
    def project_dir(self) -> Path:
        """Папка пакета проекта на диске."""
        spec = find_spec(self.project_package)
        if spec is None or not spec.submodule_search_locations:
            raise InstallationError(f"{self.project_package}: the package of the assistant is not importable")
        return Path(next(iter(spec.submodule_search_locations)))

    @property
    def skills_package(self) -> str:
        """Здесь лежат навыки проекта и сюда кладутся заготовки новых."""
        return f"{self.project_package}.skills"

    @property
    def core_dir(self) -> Path:
        """Папка самого каркаса — единственное, что он знает о себе на диске."""
        return Path(__file__).resolve().parents[1]

    @property
    def core_evals(self) -> Path:
        return self.core_dir / "prompting" / self.EVALS_FILE

    def has_configuration(self, name: str) -> bool:
        return name in SettingsLoader.configurations(self.settings_module)

    def settings(self, configuration: str | None = None) -> Settings:
        """Вариант настроек проекта + файлы этой машины. Запуск фразы и сервер ручек читают их одинаково."""
        return SettingsLoader(self.settings_module, configuration or self.configuration, self.machine_files).load()

    def environment_for(self, configuration: str) -> dict[str, str]:
        """Переменные для дочернего запуска Jericho: тот же проект в названном варианте настроек."""
        child = {self.SETTINGS_VARIABLE: self.settings_module, self.CONFIGURATION_VARIABLE: configuration}
        if self.CONFIG_VARIABLE in self.environment:
            child[self.CONFIG_VARIABLE] = self.environment[self.CONFIG_VARIABLE]
        return child

    def tool_server_environment(self, run_id: str) -> dict[str, str]:
        """Переменные для сервера ручек: тот же проект, тот же вариант настроек и тот же запуск, что у фразы."""
        unattended = {} if self.attended else {self.UNATTENDED_VARIABLE: "1"}
        user = {self.USER_VARIABLE: self.user} if self.user else {}
        return {**self.environment_for(self.configuration), self.RUN_VARIABLE: run_id, **unattended, **user}

    def unattended_environment(self) -> dict[str, str]:
        """Всё окружение этого запуска плюс отметка «рядом никого нет» — для повторного запуска без человека. Без срока
        фразы: повторный запуск — свои фразы со своим сроком (ревью 07.11.2026, №1)."""
        inherited = {key: value for key, value in self.environment.items() if key != PhraseDeadline.VARIABLE}
        return {**inherited, **self.environment_for(self.configuration), self.UNATTENDED_VARIABLE: "1"}
