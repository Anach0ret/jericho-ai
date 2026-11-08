"""Наступило ли что-нибудь в очереди отложенных поручений — без сборки ассистента.

Тик идёт раз в минуту, а сборка ассистента ради пустого ответа стоит больше полсекунды и полсотни мегабайт.
Поэтому таймер сначала зовёт эту проверку (`ExecCondition=` у systemd, `if … then` в строке cron), и `due` запускается,
только когда срок правда наступил. Здесь только стандартная библиотека: импорт каркаса потянул бы pydantic.

Формат файла знает `adapters/json_file.py`; отсюда читаются лишь поля `state` и `at`. Правило то же, что
у `DeferredQueue.has_due`: наступившее ждущее или `running`. Что обе стороны понимают файл одинаково, проверяет тест.

    python -m jericho.modules.tasks.peek <файл>    # 0 — есть наступившее, 1 — нет
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

DUE, NOTHING = 0, 1     # для ExecCondition: 1–254 — «пропустить запуск», это не ошибка


def has_due(path: Path, now: datetime) -> bool:
    """Испорченный или нечитаемый файл — «есть»: пусть с ним разберётся `due`, она отложит его в сторону."""
    try:
        records = json.loads(path.read_text(encoding="utf-8"))
        return any(
            record["state"] == "running" or (record["state"] == "pending" and datetime.fromisoformat(record["at"]) <= now)
            for record in records
        )
    except FileNotFoundError:
        return False
    except (OSError, ValueError, KeyError, TypeError):
        return True


def main(argv: list[str]) -> int:
    return DUE if has_due(Path(argv[1]), datetime.now().astimezone()) else NOTHING


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
