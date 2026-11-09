# Бэкенды модели

Бэкенд — способ дойти до модели. Проект выбирает его одной строкой: `agent = AgentSettings(backend="…")`.

| Бэкенд | Что нужно | Набор зависимостей | Кто ведёт цикл «модель → ручка → модель» |
|---|---|---|---|
| `jericho.backends.scripted` | ничего | — | никто: ответы и вызовы заданы файлом сценария |
| `jericho.backends.claude_cli` | программа `claude` и подписка | `jericho-ai[claude]` | программа `claude` через сервер ручек (MCP) |
| `jericho.backends.codex_cli` | программа `codex` и подписка ChatGPT | `jericho-ai[codex]` | программа `codex` через тот же сервер ручек (MCP) |
| `jericho.backends.anthropic_api` | ключ Anthropic | `jericho-ai[anthropic]` | наш процесс (`backends/tool_loop`) |
| `jericho.backends.openai_api` | адрес с протоколом OpenAI, ключ по желанию | `jericho-ai[openai]` | наш процесс (`backends/tool_loop`) |

## Подписка Claude и условия Anthropic

Бэкенд `claude_cli` запускает программу `claude` (Claude Code), в которую вы вошли **своей** подпиской Claude. Каркас
не трогает ни вход, ни токены: программа ставится и входит в аккаунт так, как её выпустил Anthropic. По условиям
Anthropic ([Legal and compliance](https://code.claude.com/docs/en/legal-and-compliance), раздел «Authentication and
credential use», проверено 27.10.2026):

- подписка — для **обычного личного** использования её владельцем: личный ассистент на своей машине — да;
- запросы **других людей** через вашу подписку пропускать нельзя: ассистенту, которому пишут несколько человек
  (модуль `inbox`), — бэкенд по ключу (`anthropic_api`, `openai_api`). Это держит проверка `jericho.E016`;
- продукт или служба для других — только по ключу API (Claude Console или облачный провайдер);
- не называйте свой проект «Claude Code …»: написать, что ассистент запускает Claude Code, можно, взять имя — нет;
- поручения без человека тоже идут через `claude -p`: с 15.06.2026 такие запросы по подписке тратят отдельный
  месячный лимит Agent SDK, а не обычные лимиты.

## Программа codex и подписка ChatGPT

Бэкенд `codex_cli` запускает `codex exec` (Codex CLI), в который вы вошли своей подпиской ChatGPT (`codex login`).
Ручки модель получает от того же сервера ручек (`backends/mcp_tools`), что и у `claude_cli`: те же слои, отказы и
журнал. Общего «только наши инструменты», как `claude --tools ""`, у codex нет, поэтому рамку держит сама команда
(`backends/codex_cli/client.py`, пробы на codex-cli 0.166, 02.11.2026):

- `--ignore-user-config`, `--ignore-rules`, `--ephemeral` — без личного config.toml владельца (его MCP, плагины,
  роль в `developer_instructions`), без правил и без сохранения сессии; рабочая папка — пустая временная;
- `--sandbox read-only` и `approval_policy="never"` — запись и выход за песочницу отклоняются, вопросов нет;
- встроенные возможности выключены поимённо (`codex_cli.disabled_features`: оболочка, браузер, управление
  компьютером, подагенты, плагины), поиск — `web_search="disabled"`;
- ручки в этой версии codex модель вызывает из кода (`exec`): в той среде есть только объект с ручками — ни файлов
  (`node:fs` не импортируется), ни сети (`fetch` нет);
- форма ответа — `--output-schema` в строгом режиме OpenAI: все поля обязательны, необязательные модель отдаёт
  пустыми (`"options": []`);
- промпт — `developer_instructions`, фраза — через stdin;
- одобрение codex для наших ручек выключено (`tools.<ручка>.approval_mode="approve"`): согласие на опасное спрашивает
  Jericho (`needs_confirm`), а codex с `approval_policy="never"` отклонял бы каждую ручку, кроме только читающих;
- сервер ручек получает окружение процесса (`env_vars`), как у `claude`: без него ручки рабочего стола не видят Hyprland.

Чего бэкенд не выключит: глобальный `~/.codex/AGENTS.md` codex подмешивает в любой запуск. Свою роль для codex
держите в `developer_instructions` своего config.toml — до Jericho она не дойдёт.

Подписка ChatGPT, как и подписка Claude, — для её владельца: аккаунт нельзя давать другим (условия OpenAI, Terms of
Use). Ассистенту, которому пишут несколько человек, `codex_cli` не годится — это тоже держит проверка `jericho.E016`.
Лимит подписки (`usage limit`, 429, 5xx) — `ModelUnavailable`: поручение уходит запасному бэкенду.

## Ключ

В настройках лежит только **имя** переменной окружения (`api_key_env`), сам ключ лежит в окружении машины.
Для таймера systemd его кладут в `EnvironmentFile=`. Ключ читается при первом поручении, поэтому без ключа
`check`, `prompt` и ручки из терминала работают. Поручение без ключа завершается сбоем, и в журнале
названа переменная, которую нужно задать.

Ассистенту, которого запускает рабочий стол, переменную окружения не передать без записи ключа в конфиг. Для него
ключ кладут в файл (`api_key_file`, например `~/.config/<проект>/gemini_key`, права 600): переменная, если есть,
важнее файла. Папка файлов машины от ручек `files` закрыта.

## Запасные бэкенды

`agent.fallback_backends` — пакеты бэкендов по порядку. Основной ответил «модель недоступна» (`ModelUnavailable`:
лимит подписки `claude` или `codex`, HTTP 429, перегрузка 5xx/529) — поручение начинается заново на следующем. Раздел настроек
каждого — как у основного.

```python
agent: AgentSettings = AgentSettings(backend="jericho.backends.claude_cli", fallback_backends=("jericho.backends.openai_api",))
openai_api: OpenAiSettings = OpenAiSettings(base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
                                            model="gemini-3.6-flash", api_key_env="GEMINI_API_KEY")
```

- **Ничего не делается дважды.** Перед передачей каркас смотрит в журнал: были ли в этой фразе успешные вызовы
  ручек, кроме только читающих. Были — сбой остаётся сбоем и называет сделанное (`already done in this phrase`).
- Прочие ошибки (не JSON, неверная модель, нет ключа) не передаются: у запасного они повторились бы или скрыли поломку.
- **Личные данные и файлы с машины запасной не получает**, пока его не назвали: ручки с `private` (переписка) и
  `local` (`read_file`) без списка `agent.private_backends` доступны только основному бэкенду (`private` — с 0.59.0,
  раньше любому; `local` — с 0.64.17). Не назван — запасной работает без них и получает отказ `private_needs_trusted_model`. Запасной, которому доверяете
  переписку (свой ключ, без обучения на данных), — назвать вместе с основным; имена — как в журнале:

  ```python
  agent: AgentSettings = AgentSettings(
      backend="jericho.backends.claude_cli", fallback_backends=("jericho.backends.openai_api",),
      private_backends=("claude_cli", "openai_api"),
  )
  ```
- Передача пишется в журнал (`backend_switched`), у фразы — поле `backend`: какой бэкенд ответил.
- Запасные модели **внутри** одного адреса (`openai_api.fallback_models`) — отдельный, более ранний шаг: бэкенд
  сначала перебирает свои модели, и только когда кончились все, отвечает `ModelUnavailable`.

## Бэкенды по ключу: что держит код

- Ручки вызываются через тот же диспетчер, что у сервера ручек: те же слои, отказы и журнал.
- Итоговый ответ модель даёт вызовом служебной ручки `reply`, параметры которой — форма ответа проекта.
  Ручка проекта с именем `reply` останавливает сборку.
- `reply` в одном ходе с другими вызовами не принимается: такой ответ модель писала, не видя их итога.
- Ход без вызова получает напоминание. Если вместо вызова модель написала JSON-объект текстом (так бывает
  у слабых моделей), он принимается, а в журнале у такой фразы стоит `reply_as_text`.
- Число ходов ограничено (`max_turns`), время — сроком фразы (`agent.timeout`).
- В журнал идут модель, число ходов, вызовы и токены: `input_tokens`, `output_tokens`, `cached_tokens`.
- У Anthropic промпт и список ручек кешируются: со второго хода они стоят дешевле.

## Чего у бэкендов по ключу нет

Встроенного поиска (`WebSearch` у `claude_cli`) нет. Ассистенту, которому нужен интернет, нужен навык с ручкой
поиска; тогда найденный текст проходит учёт чужого текста, чего встроенный поиск не делал.

## Примеры

```python
from jericho.backends.anthropic_api.settings import AnthropicSettings

class Base(Settings):
    agent: AgentSettings = AgentSettings(backend="jericho.backends.anthropic_api")
    anthropic_api: AnthropicSettings = AnthropicSettings(model="claude-haiku-5-5")

# или
from jericho.backends.openai_api.settings import OpenAiSettings

class Base(Settings):
    agent: AgentSettings = AgentSettings(backend="jericho.backends.openai_api")
    openai_api: OpenAiSettings = OpenAiSettings(base_url="https://openrouter.ai/api/v1", model="qwen/qwen3-coder:free", api_key_env="OPENROUTER_API_KEY")
```

## Свой бэкенд по ключу

Другой API с вызовом ручек — пакет с `backend.py`, где наследник `ToolLoopBackend` (`jericho.backends.tool_loop.base`)
называет себя и свой раздел настроек (наследник `ApiModelSettings`) и собирает модель — реализацию `ChatModel`.
Цикл ходов, срок, счёт вызовов и ответ `reply` у всех бэкендов по ключу общие:

```python
class MyApi(ToolLoopBackend[MySettings]):
    name = "my_api"
    settings_class = MySettings

    def model(self, settings: MySettings, key: EnvironmentKey) -> ChatModel:
        return MyModel(settings.model, settings.max_tokens, key)
```

Бесплатные модели слабее вызывают ручки, у них есть лимиты запросов, а запросы к ним могут идти на обучение,
поэтому журналы сервера туда не отправляют. Годится ли модель, проверяет `<проект> eval`.
