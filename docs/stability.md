# Что публично и как меняются версии

Каркас — версия 0.x: он молод и ещё меняется. Этот документ говорит, на что проект ассистента может опираться
(**публичное** — меняется только с пометкой в `CHANGELOG.md`), а что может переложиться в любой версии
(**внутреннее**). Совпадение списков ниже с кодом проверяет `tests/core/test_public_api.py`.

## Публичное

### Имена `jericho.core`

Всё, что навык и служба берут у ядра, — только отсюда (проверки E002 и E009 держат это для проектов).

| Группа | Имена |
|---|---|
| Навык и служба | `SkillConfig`, `SkillSettings`, `ServiceConfig`, `ServiceError`, `SharedServices`, `CoreServices`, `PromptContext`, `Command` |
| Ручка | `Tool`, `ToolRequest`, `ToolResult`, `ToolRefusal`, `ToolDescription`, `ToolImage`, `ToolCall`, `CallHandler`, `Risk`, `Approval`, `NEEDS_CONFIRM`, `require_consent`, `ConfirmationGate` |
| Белый список команд | `Allowlist`, `AllowlistTool`, `CommandRule`, `CommandConsole`, `RunnerConsole` |
| Службы ядра | `CommandRunner`, `CommandError`, `ForeignText`, `Clock`, `Paths`, `SecretStore`, `MemorySecretStore`, `SecretError`, `PortError` |
| Ответ и вывод | `AgentReply`, `ReplyStatus`, `Output`, `output_for` |
| Настройки | `Settings`, `SettingsSection`, `AgentSettings`, `OutputSettings`, `CommandLine`, `ExpandedPath` |

Новые поля публичных классов-данных (как `CoreServices`) добавляются **в конец**: позиционный вызов
прежней версии не меняет смысла (ревью 07.11.2026).

### Имена `jericho.core.testing`

Подмены и помощники для тестов проекта: `execute`, `builder`, `FakeBackend`, `Confirmations`, `Source`, `say_yes`,
`NOON`; проверка навыка как в `check` — `Project`, `InstalledSkills`, `DEFAULT_CHECKS`; службы ядра для сборки навыка
в тесте — `fake_core`.

### Сборка проекта

То, что использует тест `tests/test_project.py` нового проекта: `jericho.bootstrap.build_commands`,
`jericho.core.assembly.installation.Installation`.

### Настройки

- Поля `Settings`, которые проект задаёт в `settings/base.py`: `INSTALLED_SERVICES`, `INSTALLED_MODULES`,
  `INSTALLED_SKILLS`, `PRELOADED_SKILLS`, `TASK_MIDDLEWARE`, `TOOL_MIDDLEWARE`, `PROMPT_SECTIONS`, `agent`,
  `user_risk`, `default_user_risk`, `unattended_effects`, `timezone`, `dry_run`, `state_name`, `output`,
  `tool_timeout`, `secret_store`, `confirmation_minutes`, `language`.
- Имена модулей и бэкендов строками (`"jericho.modules.tasks"`, `"jericho.backends.openai_api"`) и классы их
  разделов настроек: `jericho.modules.<модуль>.settings`, `jericho.backends.<бэкенд>.settings`.
- Файлы машины: `~/.config/<проект>/local.toml` и `secrets.toml`; переменные `JERICHO_CONFIGURATION`, `JERICHO_USER`.

### Договор ручки

Атрибуты `Tool` (`name`, `description`, `request_type`, `risk`, `approval`, `service`, `private`, `outbound`,
`local`, `proves`, `relays` — с 0.62.0), метод `private_in(result)` (с 0.59.0) и что за ними обещано — `docs/tools.md`. Отказы каркаса и их коды: `invalid_parameters`,
`needs_confirm`, `nobody_to_ask`, `not_allowed_for_user`, `private_needs_trusted_model`, `skill_not_loaded`,
`tool_timeout`, `tool_failed`, `phrase_deadline_passed` (с 0.64.0).

### Командная строка, проверки, обмен

- Команды: `jericho startproject`; у проекта — `ask`, `stop`, `prompt`, `log`, `check`, `eval`, `status`,
  `startskill`, `starttool`, `startservice` и команды модулей (`task`, `timers`, `inbox`, `due` …).
- Коды проверок `jericho.E001`–`jericho.E016`: смысл кода не меняется, новые правила получают новые коды.
- Формат сообщений папки обмена с транспортом — `docs/inbox.md`.

## Внутреннее

Всё остальное: модули внутри `jericho.core.*` (кроме названных выше), ручки, адаптеры и внутренности модулей
и бэкендов, формат журнала (читать — командой `log` и ручкой `read_journal`), файлы состояния и их расположение,
тексты разделов промпта. Это перекладывается без пометки.

## Как меняются версии

| Версия | Что может меняться |
|---|---|
| `0.x.Y` | исправления; публичное и обещанное поведение — не меняются |
| `0.X.0` | новое; публичное может измениться — тогда строка в `CHANGELOG.md` начинается с **«Ломает:»** и говорит, что поправить в проекте. Где можно, старое имя живёт ещё одну версию с `DeprecationWarning` |
| `0.X.0`, безопасность | правило может стать **строже** без переходного периода (как в 0.42: вынос наружу после файлов и чужого текста — с «да»); строка начинается с **«Строже:»** |
| `1.0` | когда публичное не менялось несколько версий подряд и на каркасе работает хотя бы один чужой проект |

Проект берёт каркас по метке версии (`jericho-ai @ git+…@vX.Y.Z`) и обновляется сам, когда готов: перед этим —
`CHANGELOG.md` от своей версии до новой, затем `uv run pytest -q` и `uv run <проект> check`.
