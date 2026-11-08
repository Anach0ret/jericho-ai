# Jericho

[![CI](https://github.com/Anach0ret/jericho-ai/actions/workflows/ci.yml/badge.svg)](https://github.com/Anach0ret/jericho-ai/actions/workflows/ci.yml)

**Каркас для ассистентов, которые действуют, а не только отвечают.** Модель выбирает действие из набора
«ручек», а разрешение, согласие «да» и журнал держит код. Ассистент — отдельный проект: свои навыки, настройки
и роль; каркас ставится в него пакетом.

```
поручение → промпт → модель → вызов ручки → проверки и политика риска → действие → ответ → журнал
```

![Ассистент из руководства «Первый ассистент»: записать заметку, «да» перед стиранием, отказ на неверные параметры, проверки каркаса](docs/media/demo.gif)

Запись собирает `scripts/demo_cast.py` — из кода руководства [docs/first-assistant.md](docs/first-assistant.md), команды выполняются по-настоящему, без модели.

[English](README.en.md) · документация — на русском.

## Зачем

Дать модели инструменты легко. Трудно сделать так, чтобы она могла **делать**, но не могла **натворить**:
отправить не то, удалить не там, унести личное наружу по команде, спрятанной в чужой странице. В Jericho это
решает код, а не текст в промпте:

- **У каждой ручки — класс риска.** `READ` и `NAVIGATE` идут сразу, `CHANGE` — поправимое, `EFFECT` (не отменить
  или уходит наружу) — только после «да» пользователя. «Да» распознаёт код по фразе человека, а не модель; оно
  действует один раз и только на названный объект. Без человека (по расписанию) `EFFECT` не выполняется — кроме
  ручек, которые проект разрешил поимённо.
- **Личные данные — только доверенной модели.** Поля с перепиской не пишутся в журнал (и в аварийную запись) и по
  умолчанию достаются только основной модели; запасной — только если назвать её в `agent.private_backends`
  ([пример](docs/backends.md#запасные-бэкенды)).
  После личного или после файла с машины, если в той же фразе был чужой текст, вынести что-то наружу можно только
  с «да».
- **Чужой текст учитывается.** Страница, письмо, вывод программы помечены как чужие — указания из них не команда.
- **Каждый вызов — в журнале**: ручка, параметры, итог, время, чьё поручение.
- **Навыки может писать ИИ-агент.** Заготовки (`startskill`, `starttool`) и проверки структуры (`check`,
  E001–E016) не дают молча нарушить архитектуру: правило приходит вместе с проверкой.

Что именно гарантируется, кем и чем проверено — [docs/security.md](docs/security.md); там же честный список того,
чего каркас **не** обещает. Главное из него: это **не песочница** для непроверенного кода — каркас ограничивает
модель, а код навыков доверенный: его пишет или принимает человек.

## Где пригодится

| Сценарий | Пример |
|---|---|
| **Личный ассистент** на рабочем столе | голосом и текстом: окна, файлы, Telegram, дела, память, поручения по расписанию; уведомления с кнопками «Да/Нет» |
| **Ассистент для эксплуатации** через бота | «что с сервером?», «в чём ошибка вебхука?» — разбор журналов приложений и кода; перезапуск и выкатка — только названного в настройках и после «да»; тревоги без модели |
| **Ассистент внутри сервиса** | сервис открывает ассистенту свои действия ручками — поверх своего API или MCP. Пользователь текстом описывает, что хочет получить; ассистент раскладывает это на вызовы ручек и выполняет от его имени: читает — сразу, меняет — по правилам класса риска, необратимое — после «да» на показанный план. Пример: в таск-менеджере «заведи задачи под релиз, раздай команде, разбей на этапы» — и готовая поставка в дашборде без ручной настройки |

Первые два работают у автора каждый день. Третий — та же схема «модель выбирает, код разрешает», перенесённая
в чужой сервис; для него каркас ещё растёт (вход из веба, мост к MCP, права пользователя в ручке).

## Быстрый старт

Нужны Python 3.14 и [uv](https://docs.astral.sh/uv/); пока — Linux (почему — в «Статусе»). Каркас ставится из репозитория по метке
версии (имя `jericho` в PyPI занято другим пакетом).

```bash
uvx --from git+https://github.com/Anach0ret/jericho-ai@v0.64.7 jericho startproject my-assistant
cd my-assistant
git init -b main && git config core.hooksPath .githooks
uv sync && uv run pytest -q
uv run my_assistant ask "привет"      # бэкенд «сценарий»: без модели и без ключа
```

Подключить модель по ключу — в `settings/base.py` проекта (зависимость `jericho-ai[openai]` или `jericho-ai[anthropic]`):

```python
from jericho.backends.openai_api.settings import OpenAiSettings

class Base(Settings):
    agent: AgentSettings = AgentSettings(backend="jericho.backends.openai_api")
    openai_api: OpenAiSettings = OpenAiSettings(base_url="https://openrouter.ai/api/v1", model="…", api_key_env="OPENROUTER_API_KEY")
```

Подойдёт любой сервис с протоколом OpenAI (OpenRouter, Gemini, Ollama) или Anthropic API —
[docs/backends.md](docs/backends.md). Дальше — первый навык пошагово: [docs/first-assistant.md](docs/first-assistant.md).

## Как выглядит ручка

```python
class SendReport(Tool[SendReportRequest]):
    name = "send_report"
    request_type = SendReportRequest
    risk = Risk.EFFECT            # уходит наружу: без человека — отказ
    approval = Approval.ASK       # «да» до вызова спрашивает каркас (у EFFECT обязательно назвать — проверка E008)
    description = ToolDescription(
        when="просят отправить отчёт клиенту.",
        does="отправляет готовый отчёт письмом на адрес из карточки клиента.",
        returns='{"ok": true, "sent_to": адрес}.',
        refusals="no_report — отчёта ещё нет: сначала build_report.",
    )

    def _run(self, request: SendReportRequest) -> ToolResult:
        ...
        return ToolResult.success(sent_to=address)
```

Модель видит имя, описание и схему параметров. Неправильные параметры, ручка без загруженного навыка, `EFFECT` без
«да», превышенный срок — отказ с кодом раньше, чем ручка что-то сделает.

## Чем это не является

- **Не цепочка промптов и не граф агента** (LangChain, LangGraph): здесь договор ручки — класс риска, согласие,
  журнал, — а ход поручения ведёт модель.
- **Не просто «инструменты для модели»** (MCP, tool calling в PydanticAI и SDK провайдеров): Jericho — политика
  поверх инструментов, которую нельзя отключить настройкой, плюс учёт чужого текста и личных данных. Сервер MCP
  каркас поднимает сам — для бэкенда `claude_cli`.
- **Не платформа для тысяч пользователей**: поручение — отдельный процесс, состояние — в файлах. Для себя и для
  команды — да; для сервиса на массу людей — нет.

## Статус

Версия 0.x: каркас молод и ещё меняется — что публично и как меняются версии, в
[docs/stability.md](docs/stability.md). Документация и тексты для модели — на русском; ответы
ассистента можно перевести на английский настройкой `language = "en"`. Это личный проект: на вопросы и issues автор
отвечает по возможности, без сроков.

**Платформы.** Каркас задуман без привязки к ОС: то, что зависит от системы, — батарейки, необязательные модули,
которые на другой ОС не включают, а пишут свои. Батарейки под Linux — голос, уведомления по D-Bus (`notify`,
extra `desktop`), задачи на таймерах systemd (`tasks`). Само ядро пока проверяется только на Linux: в нём ещё есть
механизмы POSIX — замок файла (`fcntl`), срок ручки (`SIGALRM`), остановка дерева программ (`/proc`, группы
процессов), права файлов `0600`. Поэтому на Windows ядро пока не запускается, на macOS не проверялось (остановка
дерева программ там неполная); перевод этих мест на кроссплатформенные — следующая большая работа.

## Что здесь

| Папка | Что в ней |
|---|---|
| `src/jericho/core/` | ручка и политика вокруг её вызова, навык, сценарий поручения, промпт, настройки и сборка, журнал, подтверждения, проверки, прогон фраз |
| `src/jericho/modules/` | модули — необязательное, что встаёт в путь поручения: `voice`, `dialogue`, `memory`, `notes`, `journal_reader`, `tasks`, `plans`, `playbooks`, `inbox`, `files`, `search`, `scripts` |
| `src/jericho/backends/` | бэкенды модели: `scripted` — без модели, `anthropic_api` и `openai_api` — по ключу, `claude_cli` — программа `claude` по вашей подписке |

Проект называет в настройках, что включено:

```python
class Base(Settings):
    INSTALLED_SERVICES: tuple[str, ...] = ("my_assistant.services.windows",)   # общий доступ навыков к одной внешней системе
    INSTALLED_MODULES: tuple[str, ...] = ("jericho.modules.voice", "jericho.modules.dialogue")
    TASK_MIDDLEWARE: tuple[str, ...] = ("jericho.modules.dialogue",)            # слои вокруг поручения, по порядку
    INSTALLED_SKILLS: tuple[str, ...] = ("my_assistant.skills.desktop",)
    PROMPT_SECTIONS: tuple[str, ...] = ("my_assistant.settings:prompt/role.md", "jericho.core.prompting:sections/skills.md", ...)
    agent: AgentSettings = AgentSettings(backend="jericho.backends.anthropic_api")
```

Команды у любого проекта: `ask` (поручение текстом), `stop`, `prompt`, `log`, `status`, `check`, `eval`,
`startskill`, `starttool`, `startservice`. С модулем `tasks` — `task <имя>` и `timers install|list|remove`.

## Документы

- **Первый ассистент — пошагово:** [docs/first-assistant.md](docs/first-assistant.md)
- **Модель безопасности:** [docs/security.md](docs/security.md) · **где что решено:** [docs/decisions.md](docs/decisions.md)
- **Что публично и как меняются версии:** [docs/stability.md](docs/stability.md)
- Договор ручки — [docs/tools.md](docs/tools.md) · правила структуры — [docs/checks.md](docs/checks.md) ·
  бэкенды — [docs/backends.md](docs/backends.md) · проверочные фразы — [docs/evals.md](docs/evals.md) ·
  задачи без человека — [docs/tasks.md](docs/tasks.md) · поручения через бота — [docs/inbox.md](docs/inbox.md)
- Как сообщить об уязвимости — [SECURITY.md](SECURITY.md) · как предложить изменение — [CONTRIBUTING.md](CONTRIBUTING.md)

## Проверки

```bash
uv sync --all-extras
uv run pytest -q
uvx basedpyright
uvx ruff@0.14.0 check src tests
```

Хук перед коммитом — [.githooks/pre-commit](.githooks/pre-commit), включается один раз:
`git config core.hooksPath .githooks`. В GitHub Actions — то же плюс проект из образца с нуля.

## Лицензия

[Apache License 2.0](LICENSE). Бэкенд `claude_cli` работает через вашу подписку Claude — только для вашего личного
ассистента; условия Anthropic — в [docs/backends.md](docs/backends.md#подписка-claude-и-условия-anthropic).
