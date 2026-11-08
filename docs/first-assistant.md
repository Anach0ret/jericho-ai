# Первый ассистент

Пошаговое руководство: ассистент `notes-helper`, который записывает заметки и по «да» стирает их все. Каждый
шаг проверен прогоном 28.10.2026 на каркасе 0.45, вывод команд — настоящий. Модель не нужна до шага 12: до этого ассистент
работает на бэкенде «сценарий».

Что получится: проект с одним навыком и двумя ручками. Первая ручка меняет поправимо, вторая — необратимо,
и о второй каркас сам спрашивает «да». Есть тесты, проверки структуры, хук перед коммитом и режим «вхолостую».

## 0. Что нужно

- Linux, Python 3.14, [uv](https://docs.astral.sh/uv/), git.
- Каркас ставится из репозитория по метке версии — в PyPI его нет (имя `jericho` там занято другим пакетом).

## 1. Создать проект

```
$ uvx --from git+https://github.com/Anach0ret/jericho-ai@v0.64.11 jericho startproject notes-helper
…
Дальше: cd notes-helper && uv sync && uv run pytest -q && uv run notes_helper ask "привет"
Как наполнять проект — в его AGENTS.md.
```

Проект берёт каркас по той же метке (строка в `dependencies` его `pyproject.toml`). Каркас из исходников рядом —
`uv run --project ../jericho jericho startproject …`: тогда проект подключит его с живой связью.

Имя проекта пишется строчными латинскими буквами, цифрами и дефисом. Пакет и команда получаются с подчёркиванием:
`notes_helper`. Имя `notes_helper` в `startproject` не примут.

```
$ cd notes-helper
$ git init && git config core.hooksPath .githooks     # хук перед коммитом: тесты, типы, check
$ uv sync
$ uv run pytest -q
2 passed
$ uv run notes_helper ask "привет"
[done] Ассистент notes-helper собран. Модели пока нет: отвечаю по сценарию.
```

Что создано:

```
notes-helper/
├── AGENTS.md                      правила для агента, который будет наполнять проект
├── README.md
├── docs/decisions.md              указатель решений: что решено, где записано, с какой даты
├── config/local.example.toml      образец файла этой машины; настоящий — ~/.config/notes_helper/local.toml
├── .githooks/pre-commit
├── tests/                         тест сборки проекта
└── src/notes_helper/
    ├── settings/base.py           варианты настроек Base, Live, DryRun, Eval
    ├── settings/prompt/role.md    роль ассистента
    ├── settings/script.yaml       сценарий для бэкенда без модели
    ├── services/                  службы (пока пусто)
    └── skills/                    навыки (пока пусто)
```

## 2. Роль

`src/notes_helper/settings/prompt/role.md` — кто ассистент, три-четыре строки:

```markdown
# РОЛЬ
Ты — ассистент **notes-helper**: ведёшь список коротких заметок пользователя — записываешь, показываешь, очищаешь.
Отвечаешь коротко, по-русски. Делаешь дело через инструменты навыков; чего нет среди навыков — не делаешь
и говоришь об этом.
```

## 3. Навык

```
$ uv run notes_helper startskill notes_manager
…
Дальше: опиши навык в SKILL.md, добавь ручку (`notes_helper starttool notes_manager <имя>`)
и подключи навык — строка "notes_helper.skills.notes_manager" в INSTALLED_SKILLS (settings/base.py).
```

Подключить — одна строка в **уже созданном** классе `Base` в `settings/base.py`:

```python
    INSTALLED_SKILLS: tuple[str, ...] = ("notes_helper.skills.notes_manager",)
```

Остальные настройки не трогать:

- **Новый класс настроек не заводят.** Варианты `Base`, `Live`, `DryRun`, `Eval` уже есть, `Live` наследует `Base`.
- **Регистр полей разный, как в Django.** Списки подключённого — заглавными (`INSTALLED_SKILLS`, `PROMPT_SECTIONS`),
  значения — строчными (`state_name`, `agent`). У каждого поля указан тип.
- **`PROMPT_SECTIONS` шаблон уже заполнил правильно.** Роль проекта и разделы каркаса записаны
  в виде «пакет:путь»: `jericho.core.prompting:sections/skills.md`. Удалишь разделы каркаса — модель не узнает
  о навыках и о форме ответа.

## 4. Где хранить заметки

Файл с заметками — забота навыка. Положим рядом класс, который с ним работает,
`skills/notes_manager/notes.py`:

```python
"""Файл заметок: одна заметка — одна строка."""

from __future__ import annotations

from pathlib import Path


class NotesFile:
    """Заметки в текстовом файле. «Вхолостую» ничего не пишет и не стирает: файл не идёт через `core.runner`,
    поэтому режим проверяет сам."""

    def __init__(self, path: Path, dry_run: bool = False) -> None:
        self._path = path
        self._dry_run = dry_run

    def all(self) -> list[str]:
        if not self._path.exists():
            return []
        return [line for line in self._path.read_text(encoding="utf-8").splitlines() if line]

    def add(self, text: str) -> None:
        if self._dry_run:
            return
        self._path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as file:
            file.write(text + "\n")
        self._path.chmod(0o600)          # заметки — только владельцу: файлы ассистента проверяет `check` (E015)

    def clear(self) -> int:
        """Стирает все заметки и возвращает, сколько их было."""
        count = len(self.all())
        if not self._dry_run:
            self._path.unlink(missing_ok=True)
        return count
```

Почему так:

- **Режим «вхолостую».** Внешние программы ручки запускают через `core.runner`, и в режиме «вхолостую» он сам
  их не выполняет. Файл, сеть, браузер через `runner` не идут, поэтому режим проверяет тот, кто пишет.
- **Файлы ассистента — только владельцу.** Папка `700`, файл `600`: в папках ассистента бывают ключи и переписка,
  и `check` (правило E015) не пропустит открытый файл — а с ним и коммит.
- **Исключения не ловим.** Если диск полон, `OSError` долетит до каркаса. Модель получит `tool_failed` без
  текста ошибки, а подробности уйдут в журнал. `except Exception` с текстом ошибки в ответе — ровно то,
  от чего каркас защищает.

## 5. Ручка «записать»

```
$ uv run notes_helper starttool notes_manager add_note
…
Дальше: впиши ручку в `tools()` в skill.py — там её нужно собрать с зависимостями.
Забудешь — напомнит `notes_helper check`.
```

Заготовка создала `tools/add_note.py`, `tests/test_add_note.py` и вписала имя ручки в шапку `SKILL.md`.
Ручка:

```python
"""Ручка `add_note`: записать заметку."""

from __future__ import annotations

from jericho.core import Risk, Tool, ToolDescription, ToolRequest, ToolResult
from pydantic import Field

from notes_helper.skills.notes_manager.notes import NotesFile


class AddNoteRequest(ToolRequest):
    text: str = Field(min_length=1, max_length=500, description="Текст заметки — как сказал пользователь, без «запиши».")


class AddNote(Tool[AddNoteRequest]):
    name = "add_note"
    request_type = AddNoteRequest
    risk = Risk.CHANGE      # меняет файл, но поправимо: заметку можно стереть
    description = ToolDescription(
        when="просят записать, запомнить, добавить в заметки.",
        does="дописывает заметку в конец списка.",
        returns='{"ok": true, "count": сколько заметок теперь}.',
        refusals="invalid_parameters — пустой или слишком длинный текст (больше 500 знаков).",
    )

    def __init__(self, notes: NotesFile) -> None:
        self._notes = notes

    def _run(self, request: AddNoteRequest) -> ToolResult:
        self._notes.add(request.text)
        return ToolResult.success(count=len(self._notes.all()))
```

- **Ограничения — в объявлении запроса.** Пустой текст до `_run` не дойдёт: модель получит `invalid_parameters`
  со списком «поле — что не так».
- **`risk` обязателен.** `READ` только читает, `NAVIGATE` открывает и переключает, `CHANGE` меняет поправимо,
  `EFFECT` не отменить или уходит наружу.
- **Ручка получает то, с чем работает** (`NotesFile`), а не все службы ядра.

## 6. Ручка «стереть всё» — с «да»

```
$ uv run notes_helper starttool notes_manager clear_notes
```

```python
"""Ручка `clear_notes`: стереть все заметки."""

from __future__ import annotations

from collections.abc import Mapping

from jericho.core import Approval, Risk, Tool, ToolDescription, ToolRequest, ToolResult

from notes_helper.skills.notes_manager.notes import NotesFile


class ClearNotesRequest(ToolRequest):
    """Параметров нет: стираются все заметки."""


class ClearNotes(Tool[ClearNotesRequest]):
    name = "clear_notes"
    request_type = ClearNotesRequest
    risk = Risk.EFFECT          # стёртое не вернуть
    approval = Approval.ASK     # «да» спрашивает каркас: ручка выполнится только после подтверждения
    description = ToolDescription(
        when="просят очистить, стереть, удалить все заметки.",
        does="стирает все заметки. Каркас сначала спросит пользователя.",
        returns='{"ok": true, "removed": сколько стёрто}.',
        refusals="needs_confirm — спроси пользователя, стереть ли все заметки (`clarify`).",
    )

    def __init__(self, notes: NotesFile) -> None:
        self._notes = notes

    def consent_summary(self, arguments: Mapping[str, object]) -> str:
        return f"стереть все заметки ({len(self._notes.all())})"

    def _run(self, request: ClearNotesRequest) -> ToolResult:
        return ToolResult.success(removed=self._notes.clear())
```

В ручке нет ни строчки про подтверждение. Для `EFFECT` с `Approval.ASK` каркас сам записывает вызов, отвечает
модели `needs_confirm` и выполняет ручку, только когда пользователь скажет «да» **следующей** фразой.
`consent_summary` — то, что попадёт в вопрос. `Approval.TOOL` нужен, когда ручка решает сама, о чём спрашивать
(закрыть одно окно — без вопроса, пять — с вопросом). Без человека, в задаче по расписанию, ручка `EFFECT`
не выполнится вовсе.

## 7. Собрать навык

`skills/notes_manager/skill.py`:

```python
"""Навык notes_manager: что он отдаёт ядру и из чего собирается."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from jericho.core import CoreServices, SkillConfig, SkillSettings, Tool

from notes_helper.skills.notes_manager.notes import NotesFile
from notes_helper.skills.notes_manager.tools.add_note import AddNote
from notes_helper.skills.notes_manager.tools.clear_notes import ClearNotes


class NotesManagerSkill(SkillConfig[SkillSettings]):
    name = "notes_manager"
    description = "заметки пользователя: записать, стереть все."

    def ready(self, settings: SkillSettings, core: CoreServices) -> None:
        self._notes = NotesFile(core.paths.state_dir / self.name / "notes.txt", dry_run=core.dry_run)

    def tools(self) -> Sequence[Tool[Any]]:
        return (AddNote(self._notes), ClearNotes(self._notes))
```

- `ready()` вызывается один раз, до `tools()`.
- Свои файлы навык держит в своей папке внутри `core.paths.state_dir`. Каталог состояния у каждого варианта
  настроек свой: у `DryRun` — `~/.local/state/notes-helper-dry`.
- Своих настроек у навыка нет, поэтому `SkillSettings`. Понадобятся — `startskill` уже положил место для них.

`SKILL.md` — руководство, которое модель получит по `load_skill(names=["notes_manager"])`. Шапку со списком
ручек заполнила заготовка:

```markdown
---
tools: [add_note, clear_notes]
---

# Навык: notes_manager

## Правила
- Записываешь то, что просят записать, — своими словами не пересказываешь.
- Стереть можно только все заметки сразу. Ручка вернёт `needs_confirm` — спроси пользователя (`clarify`),
  на «да» в следующей фразе вызови `confirm()`.

## Примеры
«запиши купить молоко» → `add_note(text="купить молоко")` → done «Записал»
«очисти заметки» → `clear_notes()` → needs_confirm → clarify «Стереть все заметки (3)?»
```

## 8. Тесты

Заготовка теста ручки проверяет поле `target` из образца, поэтому после правки ручки тест переписывают.
`tests/test_add_note.py`:

```python
from pathlib import Path

from jericho.core.testing import execute

from notes_helper.skills.notes_manager.notes import NotesFile
from notes_helper.skills.notes_manager.tools.add_note import AddNote, AddNoteRequest


class TestAddNote:
    def test_note_is_appended(self, tmp_path: Path) -> None:
        notes = NotesFile(tmp_path / "notes.txt")

        result = execute(AddNote(notes), AddNoteRequest(text="купить молоко"))

        assert result.to_dict() == {"ok": True, "count": 1} and notes.all() == ["купить молоко"]

    def test_empty_note_is_refused(self, tmp_path: Path) -> None:
        assert execute(AddNote(NotesFile(tmp_path / "notes.txt")), {"text": ""}).error == "invalid_parameters"

    def test_nothing_is_written_in_a_dry_run(self, tmp_path: Path) -> None:
        notes = NotesFile(tmp_path / "notes.txt", dry_run=True)

        execute(AddNote(notes), AddNoteRequest(text="купить молоко"))

        assert not (tmp_path / "notes.txt").exists()
```

`execute` вызывает ручку через те же слои, что в работе: неверные параметры превращаются в отказ, а не
в исключение. Заготовка `tests/test_clear_notes.py` тоже проверяет поле `target` из образца — её переписывают так же:

```python
from pathlib import Path

from jericho.core.testing import execute

from notes_helper.skills.notes_manager.notes import NotesFile
from notes_helper.skills.notes_manager.tools.clear_notes import ClearNotes, ClearNotesRequest


class TestClearNotes:
    def test_all_notes_are_cleared(self, tmp_path: Path) -> None:
        notes = NotesFile(tmp_path / "notes.txt")
        notes.add("купить молоко")
        notes.add("позвонить маме")

        result = execute(ClearNotes(notes), ClearNotesRequest())

        assert result.to_dict() == {"ok": True, "removed": 2} and notes.all() == []

    def test_the_question_names_how_many(self, tmp_path: Path) -> None:
        notes = NotesFile(tmp_path / "notes.txt")
        notes.add("купить молоко")

        assert ClearNotes(notes).consent_summary({}) == "стереть все заметки (1)"
```

Здесь проверяется сама ручка и текст вопроса. Что без «да» она не выполнится, проверять не нужно: это держит
каркас и проверяют его тесты.

Тест навыка из заготовки (`tests/test_skill.py`) прогоняет проверки структуры. Навык в нём сначала собирают —
ручки обычно собираются в `ready()`; службы ядра для этого даёт `fake_core` (вхолостую, во временной папке):

```python
from pathlib import Path

from jericho.core.testing import DEFAULT_CHECKS, InstalledSkills, Project, fake_core

from notes_helper.skills.notes_manager.skill import NotesManagerSkill


class TestNotesManagerSkill:
    def test_skill_passes_the_structure_checks(self, tmp_path: Path) -> None:
        """То же, что `jericho check`: файлы на месте, импорты по правилам, ручки вписаны и проверены тестами."""
        skill = NotesManagerSkill()
        skill.ready(skill.settings_class(), fake_core(tmp_path))      # ручки обычно собираются в ready()
        project = Project(skill.directory.parents[1], InstalledSkills([skill]))

        assert [message for check in DEFAULT_CHECKS for message in check.run(project)] == []
```

## 9. Четыре проверки перед «готово»

```
$ uv run pytest -q
8 passed
$ uvx basedpyright --pythonpath .venv/bin/python src tests
0 errors, 0 warnings, 0 notes
$ uvx ruff@0.14.0 check src tests
All checks passed!
$ uv run notes_helper check
Проверок: 14, замечаний: нет.
```

Их же запускает хук перед каждым коммитом и не пускает коммит, пока что-то не прошло.

## 10. Поговорить без модели

Бэкенд «сценарий» вызывает ручки по-настоящему, через те же слои, а решения модели берёт из
`settings/script.yaml`. Записи проверяются сверху вниз; `when` — слова, которые есть в поручении.

```yaml
- when: запиши
  calls:
    - tool: load_skill
      arguments: {names: [notes_manager]}
    - tool: add_note
      arguments: {text: купить молоко}
  reply: {status: done, message: "Записал"}
- when: очисти
  calls:
    - tool: load_skill
      arguments: {names: [notes_manager]}
    - tool: clear_notes
  reply: {status: clarify, message: "Стереть все заметки?"}
- reply: {status: done, message: "Ассистент notes-helper собран. Модели пока нет: отвечаю по сценарию."}
```

Записи на «да» не нужно: «да» и «нет» на ждущий вопрос распознаёт код, без модели и без сценария.

Текст ответа берите в кавычки: знаки «?» и «:» внутри `{…}` YAML читает как разметку. Последнюю запись
не меняйте: на неё опирается тест проекта.

```
$ uv run notes_helper ask "запиши купить молоко"
[done] Записал
$ uv run notes_helper ask "очисти заметки"
[clarify] Стереть все заметки?
$ uv run notes_helper ask "да"
[done] Сделано: стереть все заметки (1)
```

Что произошло — в журнале (`notes_helper log`, сокращено):

```
tool    tool="add_note"  params={"text": "купить молоко"}  result={"ok": true, "count": 1}
phrase  calls=[load_skill ok, add_note ok]  phrase="запиши купить молоко"  status="done"
tool    tool="clear_notes"  params={}  result={"ok": false, "error": "needs_confirm", "summary": "стереть все заметки (1)"}
phrase  calls=[load_skill ok, clear_notes needs_confirm]  phrase="очисти заметки"  status="clarify"
tool    tool="clear_notes"  params={}  result={"ok": true, "removed": 1}
tool    tool="confirm"  params={}  result={"ok": true, "removed": 1, "confirmed": "clear_notes"}
phrase  without_model=true  consent="yes"  phrase="да"  status="done"  message="Сделано: стереть все заметки (1)"
```

На «очисти» ручка не выполнилась: каркас ответил `needs_confirm`. На «да» в следующей фразе код сам выполнил
ровно записанный вызов — модель для этого не звали. Подтвердить свой же вопрос в той же фразе нельзя, а вопрос
ждёт ответа `confirmation_minutes` (2 минуты); «да» после срока получит «вопрос истёк, ничего не сделано».

## 11. Вызвать ручку руками

У каждой ручки есть своя команда, имя пишется через дефис. Описание — то самое, что читает модель:

```
$ uv run notes_helper add-note --help
Когда: просят записать, запомнить, добавить в заметки.
Что делает: дописывает заметку в конец списка.
…
$ uv run notes_helper add-note "позвонить маме"
{"ok": true, "count": 1}
$ uv run notes_helper add-note ""
{"ok": false, "error": "invalid_parameters", "problems": [{"field": "text", "problem": "String should have at least 1 character"}]}
```

Из терминала «да» не спрашивается: команду набирает сам человек, это и есть согласие.

## 12. Вхолостую

```
$ JERICHO_CONFIGURATION=DryRun uv run notes_helper ask "запиши купить молоко"
[done] Записал
```

Файл не появился: у варианта `DryRun` свой каталог состояния, и `NotesFile` в этом режиме не пишет.

## 13. Настоящая модель

В `Base` меняется бэкенд — одна строка и раздел его настроек (подробно в `docs/backends.md` каркаса):

| Бэкенд | Строка | Что нужно |
|---|---|---|
| программа `claude` | `agent = AgentSettings(backend="jericho.backends.claude_cli")` | `claude` и подписка; набор `jericho-ai[claude]` |
| программа `codex` | `agent = AgentSettings(backend="jericho.backends.codex_cli")` | `codex` и подписка ChatGPT; набор `jericho-ai[codex]` |
| Anthropic API | `agent = AgentSettings(backend="jericho.backends.anthropic_api")` | ключ в `ANTHROPIC_API_KEY`; набор `jericho-ai[anthropic]` |
| протокол OpenAI | `agent = AgentSettings(backend="jericho.backends.openai_api")` + `openai_api = OpenAiSettings(base_url=…, model=…, api_key_env=…)` | OpenRouter, Ollama; набор `jericho-ai[openai]` |

Ключ в настройки не кладут, там только имя переменной окружения. Чтобы проверить, как модель выбирает ручки,
кладут оценочные фразы в `skills/notes_manager/evals.md` и запускают `notes_helper eval` (`docs/evals.md`).
Прогон идёт через модель и стоит запросов.

## Частые ошибки

Все случаи — из настоящих прогонов.

| Сделали | Что будет | Как надо |
|---|---|---|
| `jericho startproject notes_helper` | отказ: имя — строчные латинские, цифры и дефис | `notes-helper` |
| новый класс `LiveSettings(Settings)` | `settings/__init__.py` ищет `Base`, `Live`, `DryRun`, `Eval` | править готовый `Base` |
| `state_name = "…"` без типа | трассировка `pydantic` | `state_name: str = "…"` (уже есть в `Base`) |
| `installed_skills` строчными | навык не подключится, **без ошибки** | `INSTALLED_SKILLS` |
| `STATE_NAME = …` заглавными | без типа — ошибка `pydantic`; с типом — новое поле **без ошибки**, папка состояния прежняя | `state_name` — строчными |
| раздел промпта `"pkg.settings.prompt.role"` | `must be 'package:path'` | `"notes_helper.settings:prompt/role.md"` |
| `PROMPT_SECTIONS` из одной роли | E010; модель не знает о навыках | список из шаблона не трогать |
| `load_skill(names=["notes_helper.skills.notes_manager"])` | такого навыка нет | имя навыка: `notes_manager` |
| ручка без `risk` | E008 | `risk = Risk.…` |
| `EFFECT` без `approval` | E008 | `Approval.ASK` или `Approval.TOOL` |
| `except Exception` → `failure(detail=str(e))` | модель видит текст исключения | не ловить; ожидаемое — `raise ToolRefusal("код")` |
| запись файла без проверки `dry_run` | «вхолостую» пишет по-настоящему | проверить `core.dry_run` |
| свой файл с правами по умолчанию (664) | E015, хук не пустит коммит | папка `700`, файл `600` |
| `SkillConfig[None]` | ошибка типов | `SkillConfig[SkillSettings]` |
| ручка не вписана в `tools()` | E006 | вписать |
| у ручки нет теста | E012 | `starttool` кладёт заготовку теста |
| `message: Стереть?` в `script.yaml` | ошибка YAML, не работает ни одна команда | `message: "Стереть?"` |
| хук не срабатывает | не включён | `git init && git config core.hooksPath .githooks` |

## Дальше

- **Служба** — когда одна внешняя система нужна двум навыкам: `notes_helper startservice <имя>`.
- **Модули каркаса** подключаются строкой в `INSTALLED_MODULES`:
  - `dialogue` — помнить вопрос;
  - `voice` — голос; уведомления по D-Bus, вопрос с «да» — с кнопками «Да» и «Нет» (`voice.buttons`), уточняющий вопрос — с полем для ответа текстом (`voice.reply_field`); чем занят голос, пишет в `$XDG_RUNTIME_DIR/<имя>/voice.json` — для значка на панели; нужен набор `jericho-ai[desktop]`;
  - `scripts` — быстрые сценарии: цепочки шагов-ручек без модели (и фразы для модели) — `run <имя>`, кнопкой в окне, голосом через `run_script`;
  - `tasks` — поручения по расписанию (`docs/tasks.md`);
  - `notes` — заметки самой модели;
  - `inbox` — поручения сообщениями бота Telegram (`docs/inbox.md`).
- Правила для агента, который будет наполнять проект, — в `AGENTS.md` проекта.
