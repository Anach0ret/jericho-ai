"""Основа настроек: раздел, разделы ядра и класс настроек проекта.

Уровни, от слабого к сильному: умолчания в классах разделов → `settings/base.py` проекта → файлы этой машины.
Каждый раздел — класс `pydantic`: неверный тип или неизвестное имя — ошибка при запуске, а не тихая опечатка.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, model_validator

from jericho.core.conf.types import ExpandedPath
from jericho.core.tools.risk import Risk


class SettingsSection(BaseModel):
    """Раздел настроек: неизменяемый, лишних полей не принимает, умолчания проверяются так же, как значения из файла."""

    model_config = ConfigDict(frozen=True, extra="forbid", validate_default=True)


class SkillSettings(SettingsSection):
    """Основа раздела навыка. Навык объявляет наследника в своём `settings.py` и получает его в `ready()`."""


class ModelChoice(SettingsSection):
    """Модель, которую можно выбрать командой `<проект> model` или в окне на панели: бэкенд и модель в нём."""

    label: str                              # как пункт видит человек: «Claude Sonnet — умнее, для сложного»
    backend: str                            # пакет бэкенда — основной или один из запасных (`agent.backend`, `fallback_backends`)
    model: str = ""                         # модель в разделе этого бэкенда; пусто — какая там указана


class AgentSettings(SettingsSection):
    """Разговор с моделью — то, что не зависит от бэкенда. Свои настройки бэкенд дописывает наследником этого раздела."""

    backend: str = ""                       # пакет бэкенда модели; пусто — не выбран: на поручение ассистент ответит сбоем
    # Запасные бэкенды по порядку: основной упёрся в лимит или перегружен — поручение уходит следующему, если до
    # сбоя ничего не сделано. Например, подписка claude кончилась — Gemini через openai_api. Раздел настроек
    # каждого — как у основного.
    fallback_backends: tuple[str, ...] = ()
    timeout: float = 90.0                   # секунд на всё поручение, включая вызовы ручек
    # В каком виде модель отвечает: «brief» — статус и строка; «report» — статус, заголовок и текст.
    # Раздел промпта о формате в PROMPT_SECTIONS должен быть под стать: sections/format.md или format_report.md.
    reply_form: Literal["brief", "report"] = "brief"
    # «Да» и «нет» на ждущий вопрос — без модели: код и так их распознаёт; на «да» выполняет подтверждённый вызов,
    # ответ собирает сам. Экономит два хода модели. False — отвечает модель (ручкой confirm()).
    consent_without_model: bool = True
    # Модели на выбор: ключ — имя для `<проект> model <имя>`. Выбор держится, пока не вернут «по умолчанию»;
    # выбранная модель становится основной, остальная цепочка бэкендов остаётся запасной.
    models: dict[str, ModelChoice] = Field(default_factory=dict)
    # Кому можно отдавать личные данные — ручки с `Tool.private` (переписка): имена бэкендов, как в журнале
    # («claude_cli»). Не назван — ручка отказывает: запасная бесплатная модель могла бы учиться на переписке.
    # None — только основному бэкенду (с учётом выбранной модели); запасным — только если назвать их здесь.
    private_backends: tuple[str, ...] | None = None

    @model_validator(mode="after")
    def _choices_use_configured_backends(self) -> Self:
        known = (self.backend, *self.fallback_backends)
        for name, choice in self.models.items():
            if choice.backend not in known:
                raise ValueError(f"agent.models.{name}: backend '{choice.backend}' is neither agent.backend nor in agent.fallback_backends")
        return self


class OutputSettings(SettingsSection):
    """Куда отдать ответ на поручение, пришедшее не голосом: из терминала, по расписанию."""

    kind: Literal["stdout", "file", "notify", "mailbox"] = "stdout"
    file: ExpandedPath = Path("~/jericho-answers.md")     # для kind = "file": ответы дописываются в конец
    title: str = ""                                       # для kind = "notify": заголовок уведомления; пусто — имя проекта
    icon: str = ""                                        # для kind = "notify": значок — имя из темы значков или путь
    # Для kind = "notify": висит, пока не закроют. Иначе срок показа решает панель (Noctalia — 6 с), и напоминание,
    # пришедшее, когда у экрана никого нет, пропадает непрочитанным (журнал 26.10.2026: «записаться на лекцию»).
    persistent: bool = False
    # Для kind = "mailbox": ящик, из которого сообщения забирает транспорт (бот Telegram), и кому они.
    mailbox: ExpandedPath = Path("~/exchange/outbox")
    to: str = "owner"


class Settings(SettingsSection):
    """Настройки проекта. Проект наследует этот класс в `settings/base.py` и добавляет разделы своих навыков."""

    INSTALLED_SKILLS: tuple[str, ...] = ()   # пакеты навыков; порядок — порядок в промпте и в списке ручек
    INSTALLED_SERVICES: tuple[str, ...] = () # пакеты служб: общий доступ навыков к одной внешней системе (окна, браузер)
    # Навыки, чьё руководство сразу в общем промпте: `load_skill` для них не нужен — минус ход модели на каждой
    # фразе. Для ассистента с одним-двумя навыками; у многих навыков промпт вырос бы на все руководства сразу.
    PRELOADED_SKILLS: tuple[str, ...] = ()
    INSTALLED_MODULES: tuple[str, ...] = ()  # пакеты модулей ядра: то, что встаёт в путь поручения, — голос, диалог, заметки
    # Слои вокруг поручения — пакеты модулей из списка выше; первый — самый внешний. Порядок здесь значим:
    # он решает, что слой увидит в ответе. Модуль со слоем, не названный здесь, не соберётся.
    TASK_MIDDLEWARE: tuple[str, ...] = ()
    # Разделы общего промпта по порядку: «пакет:файл внутри пакета». Здесь — то, что каркас говорит модели сам:
    # как пользоваться навыками, подтверждениями, что делать в особых случаях и в каком виде отвечать.
    # Проект повторяет список у себя и вставляет свои разделы: роль, правила, разделы включённых частей.
    PROMPT_SECTIONS: tuple[str, ...] = (
        "jericho.core.prompting:sections/skills.md",
        "jericho.core.prompting:sections/confirmations.md",
        "jericho.core.prompting:sections/edge_cases.md",
        "jericho.core.prompting:sections/format.md",
    )
    # Слои вокруг вызова ручки; первый — самый внешний. Проект повторяет список у себя, только если меняет его:
    # добавляет свой слой или переставляет эти.
    TOOL_MIDDLEWARE: tuple[str, ...] = (
        "jericho.core.tools.middleware.Journal",              # записывает уже готовый ответ и время
        "jericho.core.tools.middleware.Refusals",             # отказ и ошибку внешнего мира превращает в ответ
        "jericho.core.skills.middleware.RequireLoadedSkill",  # ручка навыка — только после load_skill
    )
    timezone: str = ""                       # пояс ассистента, например «Europe/Berlin»; пусто — пояс машины
    # Язык того, что ядро говорит само (сбои, «отменил», кнопки «Да/Нет»), и ответов модели. Промпт ядра и описания
    # ручек пока по-русски; «да» и «нет» слышатся на обоих языках при любой настройке.
    language: Literal["ru", "en"] = "ru"
    # Ручки EFFECT, которым разрешено действовать без человека (задачи по расписанию). По умолчанию — ни одной:
    # без человека такие ручки получают отказ `nobody_to_ask`. Проект называет их поимённо и осознанно.
    unattended_effects: tuple[str, ...] = ()
    # Предел риска для пользователя (`JERICHO_USER`; у серверного ассистента — Telegram ID): ручка выше предела —
    # отказ `not_allowed_for_user`, «да» его не снимает. Владельцу — effect, остальным — сколько можно.
    # Пользователь назван, но не в списке — `default_user_risk`. Ассистент одного человека (без JERICHO_USER) — без предела.
    user_risk: dict[str, Risk] = Field(default_factory=dict)
    # Где секреты (сессии, ключи), которым не место в файле: системная связка ключей (Secret Service) или нигде.
    # Нужен набор jericho-ai[desktop]; в контейнере на сервере связки нет — «none».
    secret_store: Literal["none", "keyring"] = "none"
    default_user_risk: Risk = Risk.READ
    tool_timeout: float = 45.0               # секунд на один вызов ручки; обязан быть меньше срока фразы (agent.timeout)
    # Сколько вопрос «да?» ждёт ответа. Голос за столом — пара минут; в чате (модуль inbox) человек отвечает через
    # полчаса — там срок длиннее. Истёк — ничего не выполняется, а пользователь слышит «истёк», а не тишину.
    confirmation_minutes: int = Field(default=2, ge=1, le=1440)
    # Имя папок состояния в стандартных местах ОС (`UserDirs`; на Linux — ~/.local/state/<имя> и $XDG_RUNTIME_DIR/<имя>).
    # Одно простое имя папки, без «/» и «.» в начале:
    # иначе `same` и `same/.` — разные строки об одной папке, и пробный вариант делил бы её с рабочим (ревью 02.11.2026).
    state_name: str = Field(default="jericho", pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
    dry_run: bool = False                    # «вхолостую»: меняющие команды не выполняются, а пишутся в журнал;
                                             # такому варианту нужен свой state_name — загрузчик это проверяет
    agent: AgentSettings = AgentSettings()
    output: OutputSettings = OutputSettings()

    @model_validator(mode="after")
    def _timezone_exists(self) -> Self:
        if self.timezone:
            try:
                ZoneInfo(self.timezone)
            except (ZoneInfoNotFoundError, ValueError) as error:
                raise ValueError(f"timezone: no such time zone '{self.timezone}' — use a name like Europe/Berlin") from error
        return self

    @model_validator(mode="after")
    def _tool_ends_before_the_phrase(self) -> Self:
        """Иначе ручка продолжала бы действовать после того, как пользователю уже ответили «не получилось»."""
        if not 0 < self.tool_timeout < self.agent.timeout:
            raise ValueError(f"tool_timeout ({self.tool_timeout:g}) must be positive and less than agent.timeout ({self.agent.timeout:g})")
        return self

    def skill[SectionT: SkillSettings](self, name: str, section_class: type[SectionT]) -> SectionT:
        """Раздел навыка. Проект его не объявил — навык получает свои умолчания."""
        return self.section(name, section_class)

    def section[SectionT: SettingsSection](self, name: str, section_class: type[SectionT]) -> SectionT:
        """Раздел навыка или модуля ядра по имени. Проект его не объявил — владелец получает свои умолчания."""
        section = getattr(self, name, None)
        if section is None:
            return section_class()
        if not isinstance(section, section_class):
            raise TypeError(f"settings section '{name}' must be {section_class.__name__}, got {type(section).__name__}")
        return section
