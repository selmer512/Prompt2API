import os
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path

from .providers import SPECS
from .providers.base import BrowserSettings, ProviderSpec


@dataclass
class Settings:
    api_key: str
    browser: BrowserSettings
    providers: list[ProviderSpec]
    host: str = "127.0.0.1"
    port: int = 8320
    max_body_bytes: int = 2_000_000
    keepalive_seconds: float = 10


def load_settings(path: str | None = None) -> Settings:
    data = {}
    if path:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    server, browser = data.get("server", {}), data.get("browser", {})
    key = os.environ.get("PROMPT2API_WEB_KEY", "")
    if not key:
        raise ValueError("Set PROMPT2API_WEB_KEY to a client bearer key before starting the bridge")
    configured = data.get("providers", {"grok": {"enabled": True}})
    providers = []
    for name, entry in configured.items():
        if name not in SPECS:
            raise ValueError(f"Unknown provider: {name}")
        if not entry.get("enabled", False):
            continue
        spec = SPECS[name]
        if spec.experimental and not entry.get("allow_experimental", False):
            raise ValueError(
                f"{name} requires allow_experimental=true and local selector validation"
            )
        # URLs and model identity are fixed per module, not supplied by downstream clients.
        overrides = {k: entry[k] for k in ("composer", "submit", "response", "busy") if k in entry}
        providers.append(replace(spec, **overrides))
    if not providers:
        raise ValueError("Enable at least one provider")
    return Settings(
        api_key=key,
        browser=BrowserSettings(
            profile_root=Path(
                browser.get("profile_root", "~/.prompt2api-web/profiles")
            ).expanduser(),
            headless=browser.get("headless", True),
            channel=browser.get("channel"),
            executable_path=browser.get("executable_path"),
            max_prompt_chars=browser.get("max_prompt_chars", 200_000),
        ),
        providers=providers,
        host=server.get("host", "127.0.0.1"),
        port=int(server.get("port", 8320)),
    )
