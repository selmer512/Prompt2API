"""Provider interface and transport settings, shared by browser adapters."""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    url: str
    model: str
    composer: str
    submit: str
    response: str = ""
    busy: str = ""
    experimental: bool = False
    finished: str = ""
    response_content: str = ""


@dataclass
class BrowserSettings:
    profile_root: Path
    headless: bool = True
    channel: str | None = None
    executable_path: str | None = None
    max_prompt_chars: int = 200_000


class Provider(Protocol):
    spec: ProviderSpec

    async def complete(self, prompt: str) -> str: ...
    async def close(self) -> None: ...
