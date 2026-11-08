from pathlib import Path

import pytest

from jericho.core import ForeignText, ToolRefusal, ToolResult
from jericho.core.testing import execute
from jericho.modules.files.access import FileAccess
from jericho.modules.files.entities import Root
from jericho.modules.files.guard import PathGuard
from jericho.modules.files.settings import DEFAULT_DENY
from jericho.modules.files.tests.conftest import MakeAccess, items, names
from jericho.modules.files.tools.read import FileInfo, FindFiles, ListDir, ReadFile


def refusal(result: ToolResult) -> str:
    assert not result.ok, result
    return result.error


class TestGuard:
    def test_relative_path_counts_from_the_first_root(self, access: FileAccess, tree: Path) -> None:
        assert access.place("Obsidian/План.md").path == tree / "docs" / "Obsidian" / "План.md"

    @pytest.mark.parametrize("path", ["../outside/чужое.txt", "наружу/чужое.txt", "/etc/passwd"])
    def test_nothing_outside_the_roots(self, access: FileAccess, path: str) -> None:
        assert refusal(execute(FileInfo(access), {"path": path})) == "outside_roots"

    @pytest.mark.parametrize("path", ["project/.env", "project/.git/config", "project/.git"])
    def test_forbidden_inside_a_root(self, access: FileAccess, path: str) -> None:
        assert refusal(execute(ReadFile(access, 4096, 10**6), {"path": path})) == "forbidden_path"

    def test_key_without_extension_is_forbidden(self, access: FileAccess, tree: Path) -> None:
        """Аудит 27.10.2026: ключ выкатки `deploy/build/host_key` образцы `*.key` и `id_*` не закрывали."""
        (tree / "docs" / "project" / "host_key").write_text("-----BEGIN OPENSSH PRIVATE KEY-----")

        assert refusal(execute(ReadFile(access, 4096, 10**6), {"path": "project/host_key"})) == "forbidden_path"

    def test_no_roots_no_files(self, make_access: MakeAccess) -> None:
        access = make_access(roots=[])

        assert refusal(execute(ListDir(access, 10), {"path": "~"})) == "no_roots"

    def test_read_only_root_refuses_writes(self, tree: Path) -> None:
        guard = PathGuard([Root(tree / "docs", read_only=True)], DEFAULT_DENY)

        with pytest.raises(ToolRefusal, match="read_only_root"):
            guard.place("Obsidian/новое.md", write=True)


class TestListDir:
    def test_folders_first_hidden_and_forbidden_left_out(self, access: FileAccess) -> None:
        assert names(execute(ListDir(access, 10), {"path": "project"}), "entries") == ["node_modules"]

    def test_link_outside_is_not_listed(self, access: FileAccess) -> None:
        assert names(execute(ListDir(access, 10), {"path": "."}), "entries") == ["Obsidian", "project", "Отчёт март.pdf"]

    def test_without_path_lists_the_roots(self, access: FileAccess) -> None:
        roots = items(execute(ListDir(access, 10), {}), "roots")

        assert [root["untrusted"] for root in roots] == [False, True]


class TestFindFiles:
    def test_part_of_the_name_in_all_roots_skipping_service_folders(self, access: FileAccess) -> None:
        assert names(execute(FindFiles(access), {"name": "ПЛАН"}), "found") == ["План.md"]

    def test_pattern_and_kind(self, access: FileAccess) -> None:
        assert names(execute(FindFiles(access), {"name": "*.pdf", "kind": "file"}), "found") == ["Отчёт март.pdf"]

    def test_secrets_are_not_found(self, access: FileAccess) -> None:
        assert execute(FindFiles(access), {"name": "env"}).data["found"] == []

    def test_stops_on_a_huge_tree(self, access: FileAccess) -> None:
        assert execute(FindFiles(access, max_scan=2), {"name": "план"}).data["stopped"] is True


class TestReadFile:
    def test_reads_lines_in_parts(self, access: FileAccess) -> None:
        result = execute(ReadFile(access, 4096, 10**6), {"path": "Obsidian/План.md", "start": 2, "lines": 1})

        assert result.data == {"path": result.data["path"], "text": "строка 2", "start": 2, "end": 2, "total_lines": 3, "next_start": 3}

    def test_budget_keeps_whole_lines(self, access: FileAccess) -> None:
        result = execute(ReadFile(access, 20, 10**6), {"path": "Obsidian/План.md"})

        assert result.data["text"] == "строка 1"
        assert result.data["next_start"] == 2

    def test_a_line_longer_than_the_budget_is_read_to_the_end(self, access: FileAccess, tree: Path) -> None:
        """Однострочный JSON: раньше — начало с «…» и ни слова о продолжении (ревью 02.11.2026, П3a №10)."""
        line = "".join(f"{i:04d}" for i in range(1250))      # 5000 знаков одной строкой
        (tree / "docs" / "data.json").write_text(line)
        tool, parts, request = ReadFile(access, 1024, 10**6), [], {"path": "data.json"}

        while True:
            result = execute(tool, request)
            parts.append(str(result.data["text"]).removesuffix("…"))
            if "next_start" not in result.data:
                break
            request = {"path": "data.json", "start": result.data["next_start"], "offset": result.data.get("next_offset", 0)}

        assert "".join(parts) == line and len(parts) == 5

    def test_binary_and_directory_are_not_read(self, access: FileAccess) -> None:
        assert refusal(execute(ReadFile(access, 4096, 10**6), {"path": "Отчёт март.pdf"})) == "binary_file"
        assert refusal(execute(ReadFile(access, 4096, 10**6), {"path": "Obsidian"})) == "is_a_directory"

    def test_too_big(self, access: FileAccess) -> None:
        assert refusal(execute(ReadFile(access, 4096, 5), {"path": "Obsidian/План.md"})) == "too_big"

    def test_missing_file(self, access: FileAccess) -> None:
        assert refusal(execute(ReadFile(access, 4096, 10**6), {"path": "нет.md"})) == "not_found"


class TestForeignText:
    def test_untrusted_root_marks_what_was_read(self, access: FileAccess, foreign: ForeignText, tree: Path) -> None:
        execute(ReadFile(access, 4096, 10**6), {"path": str(tree / "downloads" / "письмо.txt")})

        assert foreign.sources == {f"files:{tree / 'downloads'}".casefold()}

    def test_own_files_are_not_foreign(self, access: FileAccess, foreign: ForeignText) -> None:
        execute(ReadFile(access, 4096, 10**6), {"path": "Obsidian/План.md"})
        execute(ListDir(access, 10), {"path": "."})

        assert foreign.sources == frozenset()

    def test_listing_untrusted_names_is_foreign_too(self, access: FileAccess, foreign: ForeignText, tree: Path) -> None:
        execute(ListDir(access, 10), {"path": str(tree / "downloads")})

        assert foreign.sources
