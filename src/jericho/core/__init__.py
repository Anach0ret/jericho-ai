"""Ядро Jericho: каркас, общий для всех навыков. О конкретных навыках ничего не знает.

Навык берёт отсюда только открытые имена: `from jericho.core import Tool, ToolRefusal`.
Внутренние папки ядра можно перекладывать, не трогая навыки.
"""

from __future__ import annotations

from jericho.core.agent.entities import AgentReply, ReplyStatus
from jericho.core.conf.settings import AgentSettings, OutputSettings, Settings, SettingsSection, SkillSettings
from jericho.core.conf.types import CommandLine, ExpandedPath
from jericho.core.errors import PortError
from jericho.core.journal.run_trail import Trail
from jericho.core.management.base import Command
from jericho.core.prompting.protocols import PromptContext
from jericho.core.services.clock import Clock
from jericho.core.services.confirmation import ConfirmationGate
from jericho.core.services.core_services import CoreServices
from jericho.core.services.foreign import ForeignText
from jericho.core.services.output import Output, output_for
from jericho.core.services.paths import Paths
from jericho.core.services.run_facts import RunFacts
from jericho.core.services.runner import CommandError, CommandRunner
from jericho.core.services.secrets import MemorySecretStore, SecretError, SecretStore
from jericho.core.services.sent import SentLog
from jericho.core.shared.config import ServiceConfig
from jericho.core.shared.registry import ServiceError, SharedServices
from jericho.core.skills.config import SkillConfig
from jericho.core.tools.allowlist import Allowlist, AllowlistTool, CommandConsole, CommandRule, RunnerConsole
from jericho.core.tools.consent import NEEDS_CONFIRM, require_consent
from jericho.core.tools.description import ToolDescription
from jericho.core.tools.dispatcher import CallHandler, ToolCall
from jericho.core.tools.request import ToolRequest
from jericho.core.tools.result import ToolImage, ToolRefusal, ToolResult
from jericho.core.tools.risk import Approval, Risk
from jericho.core.tools.tool import Tool

__all__ = [
    "NEEDS_CONFIRM",
    "AgentReply",
    "AgentSettings",
    "Allowlist",
    "AllowlistTool",
    "Approval",
    "CallHandler",
    "Clock",
    "Command",
    "CommandConsole",
    "CommandError",
    "CommandLine",
    "CommandRule",
    "CommandRunner",
    "ConfirmationGate",
    "CoreServices",
    "ExpandedPath",
    "ForeignText",
    "MemorySecretStore",
    "Output",
    "OutputSettings",
    "Paths",
    "PortError",
    "PromptContext",
    "ReplyStatus",
    "Risk",
    "RunFacts",
    "RunnerConsole",
    "SecretError",
    "SecretStore",
    "SentLog",
    "ServiceConfig",
    "ServiceError",
    "Settings",
    "SettingsSection",
    "SharedServices",
    "SkillConfig",
    "SkillSettings",
    "Tool",
    "ToolCall",
    "ToolDescription",
    "ToolImage",
    "ToolRefusal",
    "ToolRequest",
    "ToolResult",
    "Trail",
    "output_for",
    "require_consent",
]
