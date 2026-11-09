"""Заготовки проекта, навыка, ручки и службы — аналог `startproject` и `startapp`: стандартные файлы по стандартным именам."""

from __future__ import annotations

import json
import keyword
import re
from importlib.metadata import metadata
from pathlib import Path
from string import Template
from typing import ClassVar

DISTRIBUTION = "jericho-ai"      # имя пакета каркаса; импорт и команда — `jericho`


class ScaffoldError(Exception):
    """Заготовку создать нельзя: имя не подходит или место занято."""


class Scaffold:
    """Создаёт файлы навыка, ручки и службы из образцов в `templates/`.

    Образцы — обычные файлы с подстановками `$имя`; лежат рядом, чтобы их можно было читать и править
    как код, а не как строки внутри программы.
    """

    _NAME = re.compile(r"^[a-z][a-z0-9_]*$")
    _SUFFIX = ".tmpl"
    _TOOLS_LINE = re.compile(r"(?<=\A---\n)tools: \[(.*)\]$", re.MULTILINE)     # первая строка шапки SKILL.md
    _TEMPLATES = Path(__file__).parent / "templates"

    def __init__(self, project_dir: Path, project_package: str, command: str = "jericho") -> None:
        self._skills_dir = project_dir / "skills"
        self._skills_package = f"{project_package}.skills"
        self._services_dir = project_dir / "services"
        self._services_package = f"{project_package}.services"
        self._command = command      # как называется команда проекта — для подсказок

    def skill(self, name: str, description: str) -> list[Path]:
        """Папка навыка с обязательными файлами. Возвращает созданные файлы.

        Файл, который уже лежит в папке, не трогается: у задуманного навыка может быть готовый `SKILL.md`.
        """
        self._check_name(name)
        directory = self._skills_dir / name
        if (directory / "skill.py").exists():
            raise ScaffoldError(f"{directory}: такой навык уже есть")
        line = " ".join(description.split())       # одной строкой: перевод строки в описании навыка не нужен
        values = {
            "name": name,
            "description": json.dumps(line, ensure_ascii=False),       # строкой Python: кавычки и «\\» не ломают код
            "summary": line.replace("\\", "\\\\").replace('"', '\\"'),   # внутри строки документации
            "class_name": f"{self._camel(name)}Skill",
            "package": f"{self._skills_package}.{name}",
        }
        source = self._TEMPLATES / "skill"
        templates = sorted(source.rglob(f"*{self._SUFFIX}"))
        targets = {template: directory / template.relative_to(source).with_suffix("") for template in templates}
        return [self._write(template, target, values) for template, target in targets.items() if not target.exists()]

    def tool(self, skill: str, tool: str) -> list[Path]:
        """Файл ручки и файл её тестов в существующем навыке; имя ручки вписывается в шапку `SKILL.md`.

        Возвращает созданные и изменённые файлы. В `tools()` навыка ручку вписывает автор: там её нужно
        собрать с зависимостями, а это уже не данные, а код.
        """
        self._check_name(skill)      # имя, а не путь: `../x` увёл бы запись за папку навыков
        self._check_name(tool)
        directory = self._skills_dir / skill
        if not (directory / "skill.py").exists():
            raise ScaffoldError(f"{directory}: навыка нет — сначала `{self._command} startskill {skill}`")
        values = {"tool": tool, "class_name": self._camel(tool), "package": f"{self._skills_package}.{skill}"}
        source = self._TEMPLATES / "tool"
        targets = {"tool.py": directory / "tools" / f"{tool}.py", "test_tool.py": directory / "tests" / f"test_{tool}.py"}
        taken = [str(target) for target in targets.values() if target.exists()]
        if taken:
            raise ScaffoldError(f"уже есть: {', '.join(taken)}")
        created = [self._write(source / f"{template}{self._SUFFIX}", target, values) for template, target in targets.items()]
        return [*created, *self._list_in_guide(directory / "SKILL.md", tool)]

    def service(self, name: str) -> list[Path]:
        """Пакет службы: протокол, адаптер, `service.py`, подмена для тестов. Возвращает созданные файлы."""
        self._check_name(name)
        directory = self._services_dir / name
        if (directory / "service.py").exists():
            raise ScaffoldError(f"{directory}: такая служба уже есть")
        values = {"name": name, "class_name": self._camel(name), "package": f"{self._services_package}.{name}"}
        source = self._TEMPLATES / "service"
        templates = sorted(source.rglob(f"*{self._SUFFIX}"))
        targets = {template: directory / template.relative_to(source).with_suffix("") for template in templates}
        self._services_dir.mkdir(parents=True, exist_ok=True)
        (self._services_dir / "__init__.py").touch()      # папки служб в старом проекте могло не быть
        return [self._write(template, target, values) for template, target in targets.items() if not target.exists()]

    def _list_in_guide(self, guide: Path, tool: str) -> list[Path]:
        """Дописывает ручку в строку `tools: [...]` шапки. Шапки нет или она записана иначе — файл не трогается."""
        if not guide.exists():
            return []
        text = guide.read_text(encoding="utf-8")
        listed = self._TOOLS_LINE.search(text)
        if listed is None:
            return []
        names = [name.strip() for name in listed.group(1).split(",") if name.strip()]
        if tool in names:
            return []
        line = f"tools: [{', '.join((*names, tool))}]"
        guide.write_text(text[: listed.start()] + line + text[listed.end() :], encoding="utf-8")
        return [guide]

    def _check_name(self, name: str) -> None:
        if not self._NAME.fullmatch(name):
            raise ScaffoldError(f"«{name}»: имя — латинские строчные буквы, цифры и «_», первая — буква")
        if keyword.iskeyword(name):
            raise ScaffoldError(f"«{name}»: слово Python — имя не импортируется; назови иначе (например, {name}_skill)")

    @staticmethod
    def _camel(name: str) -> str:
        return "".join(part.capitalize() for part in name.split("_"))

    @staticmethod
    def _write(template: Path, target: Path, values: dict[str, str]) -> Path:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(Template(template.read_text(encoding="utf-8")).substitute(values), encoding="utf-8")
        return target


class ProjectScaffold:
    """Создаёт проект ассистента из образца: точка входа, настройки, роль, пустые папки навыков и служб, `AGENTS.md`.

    Проект после создания собирается и проходит свои тесты: бэкенд в нём — «сценарий», ему не нужен ключ.
    """

    _NAME = re.compile(r"^[a-z][a-z0-9-]*$")
    _SUFFIX = ".tmpl"
    _TEMPLATES = Path(__file__).parent / "templates" / "project"
    _RENAMED: ClassVar[dict[str, str]] = {"gitignore": ".gitignore", "githooks": ".githooks"}     # в образце — без точки, чтобы их не прятали
    _EXECUTABLE = ("pre-commit",)

    def __init__(self, framework_dir: Path | None = None, repository: str | None = None, version: str | None = None) -> None:
        self._framework_dir = framework_dir      # папка репозитория каркаса, если он стоит из исходников
        installed = metadata(DISTRIBUTION)
        urls = dict(entry.split(", ", 1) for entry in installed.get_all("Project-URL") or ())
        self._repository = repository or urls.get("Repository", "")
        self._version = version or installed["Version"]

    def project(self, name: str, parent: Path, directory: Path | None = None) -> list[Path]:
        """Папка `parent/name` с проектом — или названная `directory` (`startproject имя .`). Имя — латинские строчные
        буквы, цифры и дефис.

        Папка может уже быть — тогда пустой (допускается только `.git`: репозиторий заводят заранее).
        В папку с файлами проект не пишется: так ничего чужого не перезаписать.
        """
        if not self._NAME.fullmatch(name):
            raise ScaffoldError(f"«{name}»: имя — латинские строчные буквы, цифры и «-», первая — буква")
        directory, package = directory or parent / name, name.replace("-", "_")
        if keyword.iskeyword(package):
            raise ScaffoldError(f"«{name}»: слово Python — пакет не импортируется; назови иначе (например, {name}-assistant)")
        if directory.exists() and any(entry.name != ".git" for entry in directory.iterdir()):
            raise ScaffoldError(f"{directory}: папка не пуста — проект создаётся в новой или пустой папке")
        values = {
            "name": name, "package": package, "command": package,
            "jericho_requirement": self._requirement(), "jericho_source": self._source(),
        }
        created: list[Path] = []
        for part, base in (("root", directory), ("package", directory / "src" / package)):
            source = self._TEMPLATES / part
            for template in sorted(source.rglob(f"*{self._SUFFIX}")):
                relative = template.relative_to(source).with_suffix("")
                target = base / Path(*(self._RENAMED.get(piece, piece) for piece in relative.parts))
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(Template(template.read_text(encoding="utf-8")).substitute(values), encoding="utf-8")
                if target.name in self._EXECUTABLE:
                    target.chmod(0o755)
                created.append(target)
        return created

    def _requirement(self) -> str:
        """Зависимость проекта от каркаса — стандартной записью (PEP 508): её понимают и uv, и pip.

        Не из исходников — прямой адрес git с меткой той версии, которой проект создан. Имя пакета — `jericho-ai`:
        `jericho` в PyPI занято чужим пакетом (текстовые квесты).
        """
        if self._framework_dir is not None:
            return DISTRIBUTION          # адрес — путь к исходникам в `[tool.uv.sources]`: машина разработки, живая связь
        if not self._repository:
            raise ScaffoldError("не известно, откуда брать каркас: в его метаданных нет Project-URL Repository")
        return f"{DISTRIBUTION} @ git+{self._repository}@v{self._version}"

    def _source(self) -> str:
        """Только для каркаса из исходников: путь к ним с живой связью. Это особенность uv — для машины разработки."""
        if self._framework_dir is None:
            return ""
        return (
            "\n[tool.uv.sources]\n"
            "# Каркас из исходников рядом — машина разработки. На другой машине вместо этого раздела в dependencies:\n"
            f'# "{DISTRIBUTION} @ git+https://github.com/Anach0ret/jericho-ai@vX.Y.Z".\n'
            # Путь с «/»: обратные слэши Windows в строке TOML — escape-последовательности, uv понимает «/» везде.
            f'{DISTRIBUTION} = {{ path = "{self._framework_dir.as_posix()}", editable = true }}\n'
        )
