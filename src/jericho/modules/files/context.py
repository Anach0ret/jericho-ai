"""Подстановка для раздела промпта: какие папки разрешены."""

from __future__ import annotations

from jericho.modules.files.entities import shown
from jericho.modules.files.guard import PathGuard


class FileRoots:
    def __init__(self, guard: PathGuard) -> None:
        self._guard = guard

    def values(self) -> dict[str, str]:
        if not self._guard.roots:
            return {"file_roots": "Разрешённых папок нет: с файлами работать нельзя."}
        marks = {(False, False): "", (True, False): " — только чтение", (False, True): " — чужие файлы",
                 (True, True): " — только чтение, чужие файлы"}
        return {"file_roots": "\n".join(
            f"- `{shown(root.path)}`{marks[root.read_only, root.untrusted]}" for root in self._guard.roots
        )}
