import asyncio
import json

import pytest
from httpx import ASGITransport, AsyncClient

from prompt2api_web.app import await_connected, create_app
from prompt2api_web.errors import BridgeError
from prompt2api_web.providers.grok import SPEC

AUTH = {"Authorization": "Bearer test-key"}


class ScriptedProvider:
    spec = SPEC

    def __init__(self, replies):
        self.replies = iter(replies)
        self.prompts = []

    async def complete(self, prompt):
        self.prompts.append(prompt)
        value = next(self.replies)
        if isinstance(value, Exception):
            raise value
        return value

    async def close(self):
        pass


async def test_api_harness_tool_loop(settings, tool):
    provider = ScriptedProvider(
        [
            '{"content":null,"tool_calls":[{"name":"read_file","arguments":{"path":"app.py"}}]}',
            '{"content":"Verified hello","tool_calls":[]}',
        ]
    )
    app = create_app(settings, {"grok-web": provider})
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://bridge") as client:
        first = {
            "model": "grok-web",
            "messages": [{"role": "user", "content": "Read app.py"}],
            "tools": [tool],
        }
        response = await client.post("/v1/chat/completions", headers=AUTH, json=first)
        assert response.status_code == 200
        payload = response.json()
        assert payload["choices"][0]["finish_reason"] == "tool_calls"
        message = payload["choices"][0]["message"]
        # Simulated harness executes the requested function and sends the matching ID.
        call = message["tool_calls"][0]
        first["messages"] += [
            message,
            {"role": "tool", "tool_call_id": call["id"], "content": "hello"},
        ]
        response = await client.post("/v1/chat/completions", headers=AUTH, json=first)
        assert response.json()["choices"][0]["message"]["content"] == "Verified hello"
        assert call["id"] in provider.prompts[1]


async def test_auth_models_limits_and_unsupported_input(settings):
    provider = ScriptedProvider([])
    app = create_app(settings, {"grok-web": provider})
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://bridge") as client:
        assert (await client.get("/v1/models")).status_code == 401
        models = (await client.get("/v1/models", headers=AUTH)).json()
        assert [m["id"] for m in models["data"]] == ["grok-web"]
        assert models["data"][0]["metadata"]["readiness"] == "not_checked"
        assert (
            await client.post("/v1/chat/completions", headers=AUTH, json={"messages": []})
        ).status_code == 400
        settings.max_body_bytes = 10
        assert (
            await client.post("/v1/chat/completions", headers=AUTH, content="x" * 11)
        ).status_code == 413
        assert not provider.prompts


async def test_sse_tool_calls_and_quota_error(settings, tool):
    provider = ScriptedProvider(
        [
            '{"content":null,"tool_calls":[{"name":"read_file","arguments":{"path":"x"}}]}',
            BridgeError("Quota exhausted", "rate_limit_exceeded", 429),
        ]
    )
    app = create_app(settings, {"grok-web": provider})
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://bridge") as client:
        body = {
            "model": "grok-web",
            "messages": [{"role": "user", "content": "read"}],
            "tools": [tool],
            "stream": True,
        }
        response = await client.post("/v1/chat/completions", headers=AUTH, json=body)
        events = [
            json.loads(line[6:])
            for line in response.text.splitlines()
            if line.startswith("data: {")
        ]
        call = events[1]["choices"][0]["delta"]["tool_calls"][0]
        assert call["index"] == 0 and json.loads(call["function"]["arguments"]) == {"path": "x"}
        assert events[-1]["choices"][0]["finish_reason"] == "tool_calls"
        assert response.text.endswith("data: [DONE]\n\n")
        response = await client.post("/v1/chat/completions", headers=AUTH, json=body)
        assert "rate_limit_exceeded" in response.text and '"tool_calls": [' not in response.text


async def test_error_redaction(settings):
    provider = ScriptedProvider([RuntimeError("secret-session-cookie")])
    app = create_app(settings, {"grok-web": provider})
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://bridge") as client:
        response = await client.post(
            "/v1/chat/completions",
            headers=AUTH,
            json={"model": "grok-web", "messages": [{"role": "user", "content": "secret-prompt"}]},
        )
        assert response.status_code == 502
        assert "secret" not in response.text


async def test_disconnect_cancels_generation():
    cancelled = asyncio.Event()

    async def generation():
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    class Disconnected:
        async def is_disconnected(self):
            return True

    task = asyncio.create_task(generation())
    with pytest.raises(BridgeError):
        await await_connected(task, Disconnected())
    assert task.cancelled() and cancelled.is_set()


async def test_status_remains_available_while_generation_waits(settings):
    entered = asyncio.Event()

    class WaitingProvider(ScriptedProvider):
        def __init__(self):
            super().__init__([])
            self.lock = asyncio.Lock()
            self.context = object()
            self.stage = "waiting_response"

        async def complete(self, prompt):
            async with self.lock:
                entered.set()
                await asyncio.Event().wait()

    provider = WaitingProvider()
    app = create_app(settings, {"grok-web": provider})
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://bridge") as client:
        pending = asyncio.create_task(
            client.post(
                "/v1/chat/completions",
                headers=AUTH,
                json={"model": "grok-web", "messages": [{"role": "user", "content": "hello"}]},
            )
        )
        try:
            await entered.wait()
            assert (await client.get("/v1/providers")).status_code == 401
            status = (await client.get("/v1/providers", headers=AUTH)).json()["providers"][0]
            assert status["busy"] and status["browser_started"]
            assert status["stage"] == "waiting_response"
        finally:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        assert not provider.lock.locked()
