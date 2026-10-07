import os

import pytest

from prompt2api_web.config import Settings
from prompt2api_web.providers.base import BrowserSettings
from prompt2api_web.providers.grok import SPEC


@pytest.fixture
def settings(tmp_path):
    return Settings(
        api_key="test-key",
        browser=BrowserSettings(
            profile_root=tmp_path, executable_path=os.environ.get("PROMPT2API_TEST_BROWSER")
        ),
        providers=[SPEC],
        keepalive_seconds=0.01,
    )


@pytest.fixture
def tool():
    return {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    }
