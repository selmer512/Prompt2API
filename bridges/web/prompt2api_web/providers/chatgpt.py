"""Opt-in ChatGPT DOM adapter. Selectors require validation against your session."""

from .base import ProviderSpec

SPEC = ProviderSpec(
    name="chatgpt",
    url="https://chatgpt.com/",
    model="chatgpt-web",
    composer="#prompt-textarea",
    submit='[data-testid="send-button"]',
    response='[data-message-author-role="assistant"]',
    busy='[data-testid="stop-button"]',
    experimental=True,
)
