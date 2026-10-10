"""Opt-in Claude DOM adapter; isolated browser profile and provider selectors."""

from .base import ProviderSpec

SPEC = ProviderSpec(
    name="claude",
    url="https://claude.ai/new",
    model="claude-web",
    composer='[contenteditable="true"][role="textbox"]',
    submit='button[aria-label="Send message"]',
    response='[data-is-streaming="false"].font-claude-response',
    busy='button[aria-label="Stop response"]',
    experimental=True,
)
