"""Участок «состояние»: файлы ядра, журнал, подтверждения и службы, которые получают навыки."""

from __future__ import annotations

import sys
import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

from jericho.core.agent.active_backend import ActiveBackend
from jericho.core.assembly.installation import Installation
from jericho.core.conf.settings import Settings
from jericho.core.journal.adapters.jsonl import JournalRotation, JsonLinesLogReader, LoggingConfigurator
from jericho.core.journal.protocols import JournalReader
from jericho.core.journal.reply_vault import ReplyVault
from jericho.core.services.adapters.confirmation_file import JsonFileConfirmationStore
from jericho.core.services.clock import Clock
from jericho.core.services.confirmation import ConfirmationGate, ConfirmationStore
from jericho.core.services.core_services import CoreServices
from jericho.core.services.own_paths import OwnPaths
from jericho.core.services.paths import Paths
from jericho.core.services.phrase_deadline import PhraseDeadline
from jericho.core.services.runner import DryRunRunner, SubprocessRunner
from jericho.core.services.secrets import MemorySecretStore, NoSecretStore, SecretStore
from jericho.core.tools.catalog import ToolCatalog
from jericho.core.tools.session import CallSession


class StateFiles:
    """Файлы состояния ядра. Имя папок берётся из настроек — у прогона проверочных фраз оно своё."""

    def __init__(self, settings: Settings, installation: Installation) -> None:
        self.paths = Paths.under(settings.state_name, installation.dirs).for_user(installation.user)
        self.journal = self.paths.state_dir / "journal.jsonl"
        self.eval_runs = self.paths.state_dir / "runs"
        self.confirmation = self.paths.confirmation
        self.phrase_lock = self.paths.runtime_dir / "phrase.lock"
        self.model_choice = self.paths.state_dir / "model.json"
        self.private_replies = self.paths.runtime_dir / ReplyVault.FILE   # ответы о переписке: до выхода из системы      # выбранная вручную модель: живёт, пока не сбросят


@dataclass(frozen=True, slots=True)
class State:
    files: StateFiles
    run_id: str                         # один на фразу: общий у процесса фразы и сервера ручек
    confirmations: ConfirmationStore
    gate: ConfirmationGate
    journal: JournalReader
    session: CallSession                # что произошло в этом поручении; живёт столько же, сколько процесс
    tools: ToolCatalog                  # все ручки ассистента; заполняет участок «ручки»
    services: CoreServices              # то, что ядро выдаёт навыкам
    active_backend: ActiveBackend       # кто из бэкендов ведёт фразу: в сервере ручек — из окружения
    user: str = ""                      # чьё поручение (`JERICHO_USER`); пусто — ассистент одного человека
    phrase_deadline: PhraseDeadline = field(default_factory=PhraseDeadline)    # срок фразы: в сервере ручек — из окружения


def build_state(settings: Settings, installation: Installation) -> State:
    files = StateFiles(settings, installation)
    files.paths.prepare()
    # Сервер ручек получает запуск от фразы, которая его подняла; сама фраза заводит новый.
    inherited_run = installation.environment.get(installation.RUN_VARIABLE)
    run_id = inherited_run or uuid.uuid4().hex
    if not inherited_run:
        JournalRotation(files.journal).rotate_if_full()     # файл сменяет только процесс, начавший запуск
    LoggingConfigurator(files.journal, run_id, user=installation.user).configure()
    confirmations = JsonFileConfirmationStore(files.confirmation, timedelta(minutes=settings.confirmation_minutes))
    gate = ConfirmationGate(confirmations, run_id, attended=installation.attended)
    runner = SubprocessRunner()
    # «Вхолостую» меняющие команды навыков только записываются в журнал.
    services = CoreServices(
        DryRunRunner(runner) if settings.dry_run else runner, gate, files.paths, dry_run=settings.dry_run,
        clock=Clock(settings.timezone), secrets=_secrets(settings, installation), user=installation.user,
        own_paths=_own_paths(settings, installation, files.paths),
    )
    return State(
        files=files,
        run_id=run_id,
        confirmations=confirmations,
        gate=gate,
        journal=JsonLinesLogReader(files.journal),
        session=CallSession(),
        tools=ToolCatalog(),
        services=services,
        active_backend=ActiveBackend.from_environment(installation.environment),
        user=installation.user,
        phrase_deadline=PhraseDeadline.from_environment(installation.environment, settings.agent.timeout),
    )


def _own_paths(settings: Settings, installation: Installation, paths: Paths) -> OwnPaths:
    """Состояние, сеансы всех пользователей, файлы машины, код проекта и каркаса — основа того, что ручки не трогают."""
    packages = {type(settings).__module__.split(".")[0], "jericho"}
    code = [Path(file).parent for name in packages if (file := getattr(sys.modules.get(name), "__file__", None))]
    return OwnPaths([paths.state_dir, paths.all_sessions, installation.config_dir, *code])


def _secrets(settings: Settings, installation: Installation) -> SecretStore:
    """Связка ключей — только если проект её включил: библиотека keyring — в наборе desktop, не у всех ассистентов.
    Вхолостую — секреты в памяти: прогон проверочных фраз не трогает настоящую связку."""
    if settings.secret_store != "keyring":
        return NoSecretStore()
    if settings.dry_run:
        return MemorySecretStore()
    from jericho.core.services.adapters.keyring_store import KeyringSecretStore

    return KeyringSecretStore(installation.program)
