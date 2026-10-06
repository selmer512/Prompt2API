import pytest
from prompt2api_web.config import load_settings


def test_grok_only_default_requires_key(monkeypatch):
    monkeypatch.delenv("PROMPT2API_WEB_KEY", raising=False)
    with pytest.raises(ValueError):
        load_settings()
    monkeypatch.setenv("PROMPT2API_WEB_KEY", "test-key")
    assert [p.name for p in load_settings().providers] == ["grok"]


def test_provider_opt_in_and_profile_isolation(monkeypatch, tmp_path):
    monkeypatch.setenv("PROMPT2API_WEB_KEY", "test-key")
    config = tmp_path / "bridge.toml"
    config.write_text("[providers.chatgpt]\nenabled=true\n")
    with pytest.raises(ValueError):
        load_settings(str(config))
    config.write_text(
        "[providers.chatgpt]\nenabled=true\nallow_experimental=true\n"
        'composer="local-selector"\n[providers.grok]\nenabled=true\n'
    )
    settings = load_settings(str(config))
    assert [p.name for p in settings.providers] == ["chatgpt", "grok"]
    assert settings.providers[0].composer == "local-selector"
    assert settings.providers[0].url == "https://chatgpt.com/"
    assert len({settings.browser.profile_root / p.name for p in settings.providers}) == 2
