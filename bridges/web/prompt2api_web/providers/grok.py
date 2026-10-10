"""Grok web transport: submit through the UI, read its completed chat response."""

import json
from urllib.parse import urlparse

from ..errors import BridgeError
from .base import ProviderSpec

SPEC = ProviderSpec(
    name="grok",
    url="https://grok.com/",
    model="grok-web",
    composer='textarea[aria-label="Ask Grok anything"]',
    submit='button[aria-label="Submit"]',
)


def is_chat_response(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.hostname == "grok.com" and (
        parsed.path == "/rest/app-chat/conversations/new"
        or (
            parsed.path.startswith("/rest/app-chat/conversations/")
            and parsed.path.endswith(("/responses", "/model-responses"))
        )
    )


def decode_response(body: bytes) -> str:
    """Use final modelResponse, never concatenated reasoning/search tokens."""
    final = None
    for line in body.decode("utf-8").splitlines():
        line = line.strip()
        if line.startswith("data:"):
            line = line[5:].strip()
        if not line or line == "[DONE]":
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get("error"):
            # Do not echo an upstream body that may contain request/session data.
            raise BridgeError("Grok returned an error in the chat stream", "upstream_stream_error")
        result = event.get("result", {})
        if not isinstance(result, dict):
            continue
        response = result.get("response", result)
        if not isinstance(response, dict):
            continue
        if response.get("error"):
            raise BridgeError("Grok returned an error in the chat stream", "upstream_stream_error")
        model = response.get("modelResponse", {})
        if isinstance(model, dict) and isinstance(model.get("message"), str):
            final = model["message"]
    if final is None:
        raise BridgeError(
            "Grok response format changed or generation was incomplete",
            "unsupported_upstream_response",
        )
    return final
