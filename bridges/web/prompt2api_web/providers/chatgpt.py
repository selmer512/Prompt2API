"""Signed-out ChatGPT UI adapter. Live response extraction still needs validation."""

from .base import ProviderSpec

SPEC = ProviderSpec(
    name="chatgpt",
    url="https://chatgpt.com/",
    model="chatgpt-web",
    # The guest UI currently uses a mobile-composer textarea even on desktop.
    # Retain the contenteditable composer used by other ChatGPT UI variants.
    composer='#prompt-textarea, textarea[aria-label="Chat with ChatGPT"]',
    submit='[data-testid="send-button"], button[aria-label="Send message"]',
    response='[data-message-author-role="assistant"]',
    busy='[data-testid="stop-button"], button[aria-label="Stop generating"], '
    'button[aria-label="Stop streaming"]',
    finished='[data-testid="copy-turn-action-button"], button[aria-label="Copy response"]',
    response_content=".markdown",
    experimental=True,
)
