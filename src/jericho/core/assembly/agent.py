"""Участок «агент»: промпт, бэкенд модели из настроек и сценарий «поручение → ответ»."""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial

from jericho.core.agent.active_backend import ActiveBackend
from jericho.core.agent.consent import AnswerWithoutModel, AskedQuestion, PhraseConsent
from jericho.core.agent.context import Now, PendingQuestion
from jericho.core.agent.fallback import FallbackBackend, NamedBackend
from jericho.core.agent.forms import REPLY_FORMS
from jericho.core.agent.handle_phrase import HandlePhrase
from jericho.core.agent.model_choice import ModelChoiceFile, ModelChoices
from jericho.core.agent.phrase_journal import PhraseJournal
from jericho.core.agent.wording import WORDINGS
from jericho.core.assembly.installation import Installation
from jericho.core.assembly.skills import SkillSet
from jericho.core.assembly.state import State
from jericho.core.assembly.tools import Toolset
from jericho.core.backends.config import BackendConfig, BackendLoader, BackendServices
from jericho.core.conf.settings import Settings, SettingsSection
from jericho.core.journal.private_run import PrivateRun
from jericho.core.journal.reply_vault import ReplyVault
from jericho.core.journal.run_actions import JournalRunActions
from jericho.core.modules.registry import InstalledModules
from jericho.core.prompting.builder import PromptBuilder
from jericho.core.services.adapters.file_lock import FileLock
from jericho.core.services.adapters.json_file import JsonStateFile
from jericho.core.tools.confirm import Confirm


@dataclass(frozen=True, slots=True)
class Agent:
    prompts: PromptBuilder
    handle_phrase: HandlePhrase
    backends: tuple[BackendConfig, ...]     # основной бэкенд модели и запасные: они могут принести свои команды


def build_agent(
    settings: Settings, skills: SkillSet, modules: InstalledModules, toolset: Toolset, state: State, installation: Installation
) -> Agent:
    contexts = (Now(state.services.clock), PendingQuestion(state.confirmations, state.gate.attended), *modules.contexts())
    wording = WORDINGS[settings.language]
    prompts = PromptBuilder(
        skills.source, contexts=contexts, skills=skills.installed.names,
        guide=partial(skills.guides.guide, with_tools=False), preloaded=settings.PRELOADED_SKILLS,
        language_note=wording.reply_language,
    )
    form = REPLY_FORMS[settings.agent.reply_form]()
    loader = BackendLoader()
    # Модель, выбранная вручную (`<проект> model`, окно на панели), становится основной — до «по умолчанию».
    settings = model_choices(settings, loader).applied(ModelChoiceFile(state.files.model_choice).current())
    backends = (loader.load(settings.agent.backend), *map(loader.load, settings.agent.fallback_backends))
    state.active_backend.main = backends[0].name        # личные данные без списка — только ему (`TrustedModel`)
    services = BackendServices(
        settings=settings,
        tools=toolset.tools,
        dispatcher=toolset.dispatcher,
        reply_schema=form.schema(),
        launch=installation.launch,
        child_environment={**installation.tool_server_environment(state.run_id), ActiveBackend.MAIN_VARIABLE: backends[0].name},
        check_reply=form.parse,
        foreign=state.services.foreign,
        deadline=state.phrase_deadline,
    )
    for backend in backends:
        backend.ready(services)
    # Вторая фраза ждёт первую не дольше, чем та может идти: дольше срока разговора с моделью фраза не живёт.
    lock = FileLock(state.files.phrase_lock, wait=settings.agent.timeout)
    layers = modules.layers(settings.TASK_MIDDLEWARE)
    confirm_tool = next(tool for tool in toolset.tools if tool.name == Confirm.name)
    confirm = partial(toolset.dispatcher.call, confirm_tool, {}) if settings.agent.consent_without_model else None
    handle_phrase = HandlePhrase(
        prompts, _model(backends, toolset, state), layers, lock, form, attended=installation.attended,
        consent=AnswerWithoutModel(PhraseConsent(state.gate), confirm, wording),
        journal=PhraseJournal(PrivateRun(state.journal, state.run_id), private_replies(state), state.run_id),
        question=AskedQuestion(state.gate, wording), wording=wording, deadline=state.phrase_deadline,
    )
    return Agent(prompts, handle_phrase, backends)


def private_replies(state: State) -> ReplyVault:
    """Полные ответы о личной переписке — в папке сеанса; журнал фраз хранит только memo."""
    return ReplyVault(JsonStateFile(state.files.private_replies))


def model_choices(settings: Settings, loader: BackendLoader | None = None) -> ModelChoices:
    """Выбор модели поверх настроек: раздел бэкенда называется его именем, а не пакетом."""
    loader = loader or BackendLoader()
    def default_section(package: str) -> SettingsSection | None:
        section_class = loader.load(package).settings_class
        return section_class() if section_class is not None else None

    return ModelChoices(settings, lambda package: loader.load(package).name, default_section)


def _model(backends: tuple[BackendConfig, ...], toolset: Toolset, state: State) -> FallbackBackend:
    """Основной бэкенд и запасные одной цепочкой: упёрся в лимит — поручение уходит дальше, если ничего не сделано."""
    risks = {tool.name: tool.risk for tool in toolset.tools}
    named = [NamedBackend(backend.name, backend.backend()) for backend in backends]
    return FallbackBackend(named, JournalRunActions(state.journal, state.run_id, risks), state.active_backend, state.phrase_deadline)
