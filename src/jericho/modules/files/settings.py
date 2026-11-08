"""Настройки модуля «файлы»: с какими папками ассистенту можно работать."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from jericho.core.conf.settings import SettingsSection
from jericho.core.conf.types import CommandLine, ExpandedPath

# Что не читается и не меняется даже внутри корня: ключи, пароли, история git. Образцы — для каждой части пути.
# `*_key` — ключи без расширения (`host_key` выкатки на сервер, `ssh_host_ed25519_key`); открытая половина
# (`*.pub`) не секрет и не закрыта.
DEFAULT_DENY = (
    ".ssh", ".gnupg", ".git", ".env", ".env.*", "*.pem", "*.key", "*_key", "id_rsa*", "id_ed25519*", "id_ecdsa*",
    "*.p12", "*.pfx", "*.kdbx", "*.keystore", ".netrc", ".git-credentials", ".pgpass", "secrets*", "credentials*",
)


class RootSettings(SettingsSection):
    """Папка, внутри которой ассистенту можно работать с файлами."""

    path: ExpandedPath
    read_only: bool = False      # только смотреть и читать
    # Файлы сюда кладёт не пользователь (загрузки, вложения писем): прочитанное — чужой текст, как страница сайта
    untrusted: bool = False


class FilesSettings(SettingsSection):
    """Раздел `files`. Корней нет — модуль отказывает во всём: доступ к файлам проект открывает явно."""

    roots: tuple[RootSettings, ...] = ()     # первый корень — от него считаются относительные пути
    deny: tuple[str, ...] = DEFAULT_DENY
    max_read_bytes: int = Field(default=64 * 1024, ge=1024)    # сколько текста отдать модели за один вызов
    max_file_bytes: int = Field(default=20 * 1024 * 1024, ge=1024)    # файл больше не читается вовсе
    max_results: int = Field(default=200, ge=1, le=5000)       # записей в ответе list_dir и find_files
    # Куда уходит удалённое. freedesktop — общая корзина рабочего стола; directory — своя папка в состоянии
    # ассистента (сервер, контейнер: общей корзины там нет)
    trash: Literal["freedesktop", "directory"] = "freedesktop"
    # Распаковка: сколько архив может развернуть. Маленький архив бывает «бомбой» на гигабайты
    max_unpack_bytes: int = Field(default=2 * 1024**3, ge=1024)
    max_unpack_files: int = Field(default=10_000, ge=1)
    # Чем открыть файл программой по умолчанию: «gio open» или «xdg-open». Пусто — ручки open_file нет (сервер)
    open_command: CommandLine = ()
