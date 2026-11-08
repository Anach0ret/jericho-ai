from pathlib import Path

import pytest

import jericho
from jericho.core.evals.adapters.markdown_file import MarkdownEvalFile

PACKAGE = Path(jericho.__file__).parent
FILES = [PACKAGE / "core" / "prompting" / "evals.md"]


class TestEvalFiles:
    @pytest.mark.parametrize("file", FILES, ids=lambda file: file.parent.name)
    def test_every_file_in_the_repository_is_readable(self, file: Path) -> None:
        cases = MarkdownEvalFile(file.parent.name, file).cases()

        assert cases and all(case.phrase and case.statuses for case in cases)
        assert all(case.after in {other.key for other in cases} for case in cases if case.after)
