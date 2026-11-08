"""Запись терминала для README: ассистент из «Первого ассистента» записывает заметку, спрашивает «да», стирает,
а журнал показывает каждый вызов.

Собирает проект `notes-helper` во временной папке — каркас из этих исходников, код навыка берётся из блоков
`docs/first-assistant.md`, так что запись не расходится с руководством. Команды выполняются по-настоящему, их вывод
пишется в файл asciicast v2 с «набором» команды. Модель не нужна: бэкенд «сценарий». Папки состояния, настроек
и рабочая — тоже временные, домашняя папка не трогается.

Две записи — для README.md (английская) и README.ru.md. Английская переводит то, что руководство пишет по-русски
и что видно на экране: сценарий бэкенда, `language = "en"` и вопрос ручки «стереть всё»; код навыка тот же.

    uv run python scripts/demo_cast.py en docs/media/demo.en.cast
    uv run python scripts/demo_cast.py ru docs/media/demo.ru.cast
    agg --font-size 18 --theme monokai docs/media/demo.en.cast docs/media/demo.en.gif     # https://github.com/asciinema/agg
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / "docs/first-assistant.md"
WIDTH, HEIGHT = 100, 22
TYPING, PAUSE, READ = 0.045, 0.5, 1.8          # секунды: на знак команды, перед выводом, на чтение вывода
SKILL = "src/notes_helper/skills/notes_manager"

# Файлы проекта ← начало блока кода в руководстве.
FILES = {
    "src/notes_helper/settings/prompt/role.md": "# РОЛЬ",
    "src/notes_helper/settings/script.yaml": "- when: запиши",
    f"{SKILL}/notes.py": '"""Файл заметок',
    f"{SKILL}/tools/add_note.py": '"""Ручка `add_note`',
    f"{SKILL}/tools/clear_notes.py": '"""Ручка `clear_notes`',
    f"{SKILL}/skill.py": '"""Навык notes_manager',
    f"{SKILL}/SKILL.md": "---\ntools: [add_note",
    f"{SKILL}/tests/test_add_note.py":
        "from pathlib import Path\n\nfrom jericho.core.testing import execute\n\nfrom notes_helper.skills.notes_manager.notes import NotesFile\nfrom notes_helper.skills.notes_manager.tools.add_note",
    f"{SKILL}/tests/test_clear_notes.py":
        "from pathlib import Path\n\nfrom jericho.core.testing import execute\n\nfrom notes_helper.skills.notes_manager.notes import NotesFile\nfrom notes_helper.skills.notes_manager.tools.clear_notes",
    f"{SKILL}/tests/test_skill.py": "from pathlib import Path\n\nfrom jericho.core.testing import DEFAULT_CHECKS",
}

# Последние три записи журнала: стирание выполнено после «да» — вызов ручки, подтверждение, фраза.
LOG = "notes_helper log -n 3"

ENGLISH_SCRIPT = """\
- when: write
  calls:
    - tool: load_skill
      arguments: {names: [notes_manager]}
    - tool: add_note
      arguments: {text: buy milk}
  reply: {status: done, message: "Noted"}
- when: clear
  calls:
    - tool: load_skill
      arguments: {names: [notes_manager]}
    - tool: clear_notes
  reply: {status: clarify, message: "This cannot be undone."}
- reply: {status: done, message: "notes-helper is ready. No model yet: replying from the script."}
"""


@dataclass(frozen=True)
class Scene:
    """Команда, ожидаемые признаки настоящего вывода и время на чтение."""

    note: str
    command: str
    expected: tuple[str, ...]
    read: float = READ
    clear: bool = False
    exit_code: int = 0


@dataclass(frozen=True)
class Recording:
    """Одна запись: пояснения и команды на экране, язык ассистента и что заменить в коде руководства."""

    title: str
    shown: tuple[Scene, ...]
    language: str = "ru"
    replace: dict[str, tuple[str, str]] = field(default_factory=dict)   # файл → (было, стало)
    files: dict[str, str] = field(default_factory=dict)                 # файл → новое содержимое


RECORDINGS = {
    "ru": Recording(
        title="Jericho: заметка, «да» и журнал",
        shown=(
            Scene("ручка «записать» меняет поправимо — выполняется сразу", 'notes_helper ask "запиши купить молоко"', ('[done] Записал',)),
            Scene("неверные параметры — отказ с объяснением, а не исключение", 'notes_helper add-note ""', ('"error": "invalid_parameters"',)),
            Scene("«стереть всё» не отменить — каркас сам спрашивает «да»", 'notes_helper ask "очисти заметки"', ('[clarify] Стереть все заметки (1)? Да или нет.',)),
            Scene("«да» слышит код, не модель: выполняется ровно записанный вызов", 'notes_helper ask "да"', ('[done] Сделано: стереть все заметки (1)',)),
            Scene("каждый вызов — в журнале: ручка, параметры, итог", LOG, ('tool="clear_notes"', '"removed": 1', 'without_model=true'), read=12, clear=True),
        ),
    ),
    "en": Recording(
        title="Jericho: a note, a \"yes\" and the journal",
        shown=(
            Scene("adding a note is a reversible change: it runs right away", 'notes_helper ask "write: buy milk"', ('[done] Noted',)),
            Scene("bad parameters: a refusal with an explanation, not an exception", 'notes_helper add-note ""', ('"error": "invalid_parameters"',)),
            Scene("deleting everything can't be undone: the framework asks first", 'notes_helper ask "clear my notes"', ('[clarify] Delete all notes (1)? Yes or no.',)),
            Scene("the \"yes\" is recognised by code, not the model: the recorded call runs", 'notes_helper ask "yes"', ('[done] Done: delete all notes (1)',)),
            Scene("every call is journaled: tool, parameters, outcome", LOG, ('tool="clear_notes"', '"removed": 1', 'without_model=true'), read=12, clear=True),
        ),
        language="en",
        replace={f"{SKILL}/tools/clear_notes.py": ('f"стереть все заметки (', 'f"delete all notes (')},
        files={"src/notes_helper/settings/script.yaml": ENGLISH_SCRIPT},
    ),
}


def main(language: str, out: Path) -> None:
    recording = RECORDINGS[language]
    with tempfile.TemporaryDirectory(prefix="jericho-demo-") as temp:
        base = Path(temp)
        env = os.environ | {
            "XDG_STATE_HOME": str(base / "state"), "XDG_CONFIG_HOME": str(base / "config"),
            "XDG_RUNTIME_DIR": str(base / "run"), "NO_COLOR": "1", "COLUMNS": str(WIDTH),
        }
        (base / "run").mkdir(mode=0o700)
        project = build(base, env)
        adapt(project, recording)
        events, clock = record(project, env, recording)
    header = {"version": 2, "width": WIDTH, "height": HEIGHT, "title": recording.title,
              "env": {"SHELL": "/bin/bash", "TERM": "xterm-256color"}}
    lines = [json.dumps(header, ensure_ascii=False)] + [json.dumps([round(t, 3), "o", text], ensure_ascii=False) for t, text in events]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{out}: {len(recording.shown)} команд, {clock:.0f} с")


def build(base: Path, env: dict[str, str]) -> Path:
    """Проект по руководству: заготовки каркаса и код из блоков `docs/first-assistant.md`."""
    run = lambda *command, cwd=base: subprocess.run(command, cwd=cwd, env=env, check=True, capture_output=True)
    run("uv", "run", "-q", "--project", str(ROOT), "jericho", "startproject", "notes-helper")
    project = base / "notes-helper"
    pyproject = project / "pyproject.toml"
    pyproject.write_text(re.sub(r'"jericho-ai @ git\+[^"]+"', f'"jericho-ai @ file://{ROOT}"', pyproject.read_text(encoding="utf-8")), encoding="utf-8")
    run("uv", "sync", "-q", cwd=project)
    run("uv", "run", "-q", "notes_helper", "startskill", "notes_manager", cwd=project)
    for tool in ("add_note", "clear_notes"):
        run("uv", "run", "-q", "notes_helper", "starttool", "notes_manager", tool, cwd=project)
    settings = project / "src/notes_helper/settings/base.py"
    settings.write_text(settings.read_text(encoding="utf-8").replace(
        "INSTALLED_SKILLS: tuple[str, ...] = ()", 'INSTALLED_SKILLS: tuple[str, ...] = ("notes_helper.skills.notes_manager",)'), encoding="utf-8")
    blocks = [code for _, code in re.findall(r"```(\w*)\n(.*?)```", GUIDE.read_text(encoding="utf-8"), re.S)]
    for path, start in FILES.items():
        (project / path).write_text(next(code for code in blocks if code.lstrip().startswith(start)), encoding="utf-8")
    return project


def adapt(project: Path, recording: Recording) -> None:
    """Язык ассистента и переводы записи; замена, которой нет в коде руководства, — ошибка, а не тихий пропуск."""
    settings = project / "src/notes_helper/settings/base.py"
    settings.write_text(settings.read_text(encoding="utf-8").replace(
        "INSTALLED_SKILLS: tuple[str, ...] = (",
        f'language: Literal["ru", "en"] = "{recording.language}"\n    INSTALLED_SKILLS: tuple[str, ...] = (', 1)
        .replace("from __future__ import annotations\n", "from __future__ import annotations\n\nfrom typing import Literal\n", 1), encoding="utf-8")
    for path, (old, new) in recording.replace.items():
        target = project / path
        text = target.read_text(encoding="utf-8")
        if old not in text:
            raise SystemExit(f"{path}: нет «{old}» — руководство изменилось, поправь RECORDINGS в scripts/demo_cast.py")
        target.write_text(text.replace(old, new), encoding="utf-8")
    for path, text in recording.files.items():
        (project / path).write_text(text, encoding="utf-8")


def record(project: Path, env: dict[str, str], recording: Recording) -> tuple[list[tuple[float, str]], float]:
    events: list[tuple[float, str]] = []
    clock = 0.5
    for scene in recording.shown:
        if scene.clear:
            events.append((clock, "\x1b[2J\x1b[H"))
        events.append((clock, f"\x1b[2m# {scene.note}\x1b[0m\r\n"))
        clock = typed(events, clock + READ / 2, scene.command)
        output = subprocess.run(["uv", "run", "-q", *shlex.split(scene.command)], cwd=project,
                                env=env, capture_output=True, text=True, encoding="utf-8", check=False)
        missing = [text for text in scene.expected if text not in output.stdout]
        if output.returncode != scene.exit_code or missing:
            raise SystemExit(f"demo step failed: {scene.command}\n"
                             f"exit={output.returncode}, expected={scene.exit_code}; missing={missing}\n"
                             f"{output.stdout}{output.stderr}")
        clock += PAUSE
        events.append((clock, (output.stdout + output.stderr).replace("\n", "\r\n")))
        clock += scene.read
    events.append((clock + READ, "\x1b[1;32m$\x1b[0m "))
    return events, clock + READ


def typed(events: list[tuple[float, str]], clock: float, command: str) -> float:
    events.append((clock, "\x1b[1;32m$\x1b[0m "))
    for char in "uv run " + command:
        clock += TYPING
        events.append((clock, char))
    clock += PAUSE
    events.append((clock, "\r\n"))
    return clock


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in RECORDINGS:
        raise SystemExit(f"запуск: scripts/demo_cast.py {'|'.join(RECORDINGS)} <файл .cast>")
    main(sys.argv[1], Path(sys.argv[2]))
