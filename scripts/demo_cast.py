"""Запись терминала для README: ассистент из «Первого ассистента» записывает заметку, спрашивает «да» и стирает.

Собирает проект `notes-helper` во временной папке — каркас из этих исходников, код навыка берётся из блоков
`docs/first-assistant.md`, так что запись не расходится с руководством. Команды выполняются по-настоящему, их вывод
пишется в файл asciicast v2 с «набором» команды. Модель не нужна: бэкенд «сценарий». Папки состояния, настроек
и рабочая — тоже временные, домашняя папка не трогается.

    uv run python scripts/demo_cast.py docs/media/demo.cast
    agg --font-size 18 --theme monokai docs/media/demo.cast docs/media/demo.gif     # https://github.com/asciinema/agg
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / "docs/first-assistant.md"
WIDTH, HEIGHT = 100, 17
TYPING, PAUSE, READ = 0.045, 0.5, 1.8          # секунды: на знак команды, перед выводом, на чтение вывода

# Что показывает запись: проект уже собран по руководству. Пояснение — серой строкой над командой.
SHOWN = (
    ("ручка «записать» меняет поправимо — выполняется сразу", 'notes_helper ask "запиши купить молоко"'),
    ("«стереть всё» не отменить — каркас сам спрашивает «да»", 'notes_helper ask "очисти заметки"'),
    ("«да» слышит код, не модель: выполняется ровно записанный вызов", 'notes_helper ask "да"'),
    ("неверные параметры — отказ с объяснением, а не исключение", 'notes_helper add-note ""'),
    ("правила каркаса: риск у каждой ручки, тесты, права на файлы…", "notes_helper check"),
)

# Файлы проекта ← начало блока кода в руководстве.
FILES = {
    "src/notes_helper/settings/prompt/role.md": "# РОЛЬ",
    "src/notes_helper/settings/script.yaml": "- when: запиши",
    "src/notes_helper/skills/notes_manager/notes.py": '"""Файл заметок',
    "src/notes_helper/skills/notes_manager/tools/add_note.py": '"""Ручка `add_note`',
    "src/notes_helper/skills/notes_manager/tools/clear_notes.py": '"""Ручка `clear_notes`',
    "src/notes_helper/skills/notes_manager/skill.py": '"""Навык notes_manager',
    "src/notes_helper/skills/notes_manager/SKILL.md": "---\ntools: [add_note",
    "src/notes_helper/skills/notes_manager/tests/test_add_note.py":
        "from pathlib import Path\n\nfrom jericho.core.testing import execute\n\nfrom notes_helper.skills.notes_manager.notes import NotesFile\nfrom notes_helper.skills.notes_manager.tools.add_note",
    "src/notes_helper/skills/notes_manager/tests/test_clear_notes.py":
        "from pathlib import Path\n\nfrom jericho.core.testing import execute\n\nfrom notes_helper.skills.notes_manager.notes import NotesFile\nfrom notes_helper.skills.notes_manager.tools.clear_notes",
    "src/notes_helper/skills/notes_manager/tests/test_skill.py": "from pathlib import Path\n\nfrom jericho.core.testing import DEFAULT_CHECKS",
}


def main(out: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="jericho-demo-") as temp:
        base = Path(temp)
        env = os.environ | {
            "XDG_STATE_HOME": str(base / "state"), "XDG_CONFIG_HOME": str(base / "config"),
            "XDG_RUNTIME_DIR": str(base / "run"), "NO_COLOR": "1", "COLUMNS": str(WIDTH),
        }
        (base / "run").mkdir(mode=0o700)
        project = build(base, env)
        events: list[tuple[float, str]] = []
        clock = 0.5
        for note, command in SHOWN:
            events.append((clock, f"\x1b[2m# {note}\x1b[0m\r\n"))
            clock = typed(events, clock + READ / 2, command)
            output = subprocess.run(["uv", "run", "-q", *command.split(" ", 1)[:1], *split_args(command)], cwd=project,
                                    env=env, capture_output=True, text=True, check=False)
            clock += PAUSE
            events.append((clock, (output.stdout + output.stderr).replace("\n", "\r\n")))
            clock += READ
        events.append((clock, "\x1b[1;32m$\x1b[0m "))
    header = {"version": 2, "width": WIDTH, "height": HEIGHT, "title": "Jericho: заметки, «да» и проверки",
              "env": {"SHELL": "/bin/bash", "TERM": "xterm-256color"}}
    lines = [json.dumps(header, ensure_ascii=False)] + [json.dumps([round(t, 3), "o", text], ensure_ascii=False) for t, text in events]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{out}: {len(SHOWN)} команд, {clock:.0f} с")


def build(base: Path, env: dict[str, str]) -> Path:
    """Проект по руководству: заготовки каркаса и код из блоков `docs/first-assistant.md`."""
    run = lambda *command, cwd=base: subprocess.run(command, cwd=cwd, env=env, check=True, capture_output=True)
    run("uv", "run", "-q", "--project", str(ROOT), "jericho", "startproject", "notes-helper")
    project = base / "notes-helper"
    pyproject = project / "pyproject.toml"
    pyproject.write_text(re.sub(r'"jericho-ai @ git\+[^"]+"', f'"jericho-ai @ file://{ROOT}"', pyproject.read_text()))
    run("uv", "sync", "-q", cwd=project)
    run("uv", "run", "-q", "notes_helper", "startskill", "notes_manager", cwd=project)
    for tool in ("add_note", "clear_notes"):
        run("uv", "run", "-q", "notes_helper", "starttool", "notes_manager", tool, cwd=project)
    settings = project / "src/notes_helper/settings/base.py"
    settings.write_text(settings.read_text().replace(
        "INSTALLED_SKILLS: tuple[str, ...] = ()", 'INSTALLED_SKILLS: tuple[str, ...] = ("notes_helper.skills.notes_manager",)'))
    blocks = [code for _, code in re.findall(r"```(\w*)\n(.*?)```", GUIDE.read_text(), re.S)]
    for path, start in FILES.items():
        (project / path).write_text(next(code for code in blocks if code.lstrip().startswith(start)))
    return project


def split_args(command: str) -> list[str]:
    """Аргументы после имени команды — как их разберёт bash (здесь только слова и строки в двойных кавычках)."""
    return [quoted if quoted is not None else word for quoted, word in
            ((m.group(1), m.group(2)) for m in re.finditer(r'"([^"]*)"|(\S+)', command))][1:]


def typed(events: list[tuple[float, str]], clock: float, command: str) -> float:
    events.append((clock, "\x1b[1;32m$\x1b[0m "))
    for char in "uv run " + command:
        clock += TYPING
        events.append((clock, char))
    clock += PAUSE
    events.append((clock, "\r\n"))
    return clock


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs/media/demo.cast")
