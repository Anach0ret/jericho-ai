"""Правило входящих: подписку на модель (Claude, ChatGPT) не делят с другими людьми."""

from __future__ import annotations

from jericho.core.checks.base import CheckMessage, Project
from jericho.modules.inbox.settings import InboxSettings

# Бэкенды, которые идут через личную подписку владельца, и чья это подписка — для текста замечания.
SUBSCRIPTION_BACKENDS = {
    "jericho.backends.claude_cli": "Claude (условия Anthropic)",      # программа `claude`
    "jericho.backends.codex_cli": "ChatGPT (условия OpenAI)",         # программа `codex`
}


class SubscriptionIsNotShared:
    """E016: бэкенд по подписке (`claude_cli`, `codex_cli`) и поручения от нескольких людей через бота не сочетаются.

    Условия Anthropic (code.claude.com/docs/en/legal-and-compliance, «Authentication and credential use», 27.10.2026):
    подписка — для обычного личного использования её владельцем; гонять через неё запросы других людей нельзя.
    Условия OpenAI (Terms of Use, «Your account»): аккаунт нельзя давать другим — подписка ChatGPT, через которую
    входит `codex`, тоже только для владельца. Ассистенту, которому пишут несколько человек, нужен бэкенд по ключу (`anthropic_api`, `openai_api`). Проверяются
    основной и запасные бэкенды: запасной тоже ведёт чужие поручения, когда основной недоступен.
    """

    CODE = "jericho.E016"

    def run(self, project: Project) -> list[CheckMessage]:
        if project.settings is None:
            return []
        agent = project.settings.agent
        users = project.settings.section("inbox", InboxSettings).users
        if len(users) <= 1:
            return []
        return [
            CheckMessage(
                self.CODE, "settings",
                f"поручения пишут {len(users)} человека (`inbox.users`), а модель идёт через подписку {whose} (`{backend}`): "
                "подписка — только для её владельца; другим — бэкенд по ключу (`anthropic_api`, `openai_api`)",
            )
            for backend in (agent.backend, *agent.fallback_backends)
            if (whose := SUBSCRIPTION_BACKENDS.get(backend)) is not None
        ]
