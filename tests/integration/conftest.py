import logging
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from jericho.core.assembly.installation import Installation

PROJECT = "tests.core.sample_settings"      # пробный проект: один навык, без модулей; каркасу хватает и такого


@pytest.fixture
def installation(tmp_path: Path) -> Iterator[Installation]:
    """Пробный проект; состояние и файлы машины — во временной папке.

    Журнал после теста возвращается как был: сборка перенастраивает общий логгер.
    """
    logger = logging.getLogger("jericho")
    handlers, level, propagate = list(logger.handlers), logger.level, logger.propagate
    environment = {
        Installation.SETTINGS_VARIABLE: PROJECT,
        "XDG_STATE_HOME": str(tmp_path / "state"),
        "XDG_RUNTIME_DIR": str(tmp_path / "run"),
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
    }
    yield Installation.discover(environment, tmp_path, sys.executable)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    for handler in handlers:
        logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = propagate
