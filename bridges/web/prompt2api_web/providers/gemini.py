"""Opt-in Gemini DOM adapter; availability follows the signed-in website account."""

from .base import ProviderSpec

SPEC = ProviderSpec(
    name="gemini",
    url="https://gemini.google.com/app",
    model="gemini-web",
    composer='[contenteditable="true"][role="textbox"]',
    submit='button[aria-label="Send message"]',
    response="model-response .markdown",
    busy='button[aria-label="Stop response"]',
    experimental=True,
)
