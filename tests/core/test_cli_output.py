"""Вывод команд — в UTF-8 на любой ОС: перенаправленный вывод Windows (cp1252) иначе роняет команду на русском."""

import io
import sys

import pytest

from jericho.core.interfaces.cli.main import utf8_output


def test_output_in_a_system_encoding_becomes_utf8(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = io.BytesIO()
    monkeypatch.setattr("sys.stdout", io.TextIOWrapper(raw, encoding="cp1252"))

    utf8_output()
    print("Создано и изменено:", flush=True)

    assert raw.getvalue().decode("utf-8") == "Создано и изменено:\n"


def test_stream_that_is_not_a_file_is_left_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = io.StringIO()
    monkeypatch.setattr("sys.stdout", captured)

    utf8_output()

    assert sys.stdout is captured
