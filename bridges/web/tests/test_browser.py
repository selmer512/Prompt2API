"""Actual Chromium/UI/response-capture tests against an intercepted local fixture.

No chat is sent to Grok. All browser network requests are intercepted here.
"""

import asyncio
import json

import pytest
from prompt2api_web.browser import BrowserProvider
from prompt2api_web.errors import BridgeError
from prompt2api_web.providers.grok import SPEC

pytestmark = pytest.mark.browser

LANDING = """<!doctype html><html><head><title>Chat fixture</title></head><body>
<textarea aria-label="Ask Grok anything"></textarea><button aria-label="Submit">Send</button>
<script>document.querySelector('button').onclick = async () => {
 const prompt = document.querySelector('textarea').value;
 const r = await fetch('/rest/app-chat/conversations/new', {
 method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:prompt})});
 document.body.append(document.createTextNode(await r.text()));
};</script></body></html>"""


async def prepared(settings, reply="fixture answer", status=200):
    provider = BrowserProvider(SPEC, settings.browser)
    await provider.start()
    seen = []

    async def handle(route):
        if route.request.method == "POST":
            seen.append(json.loads(route.request.post_data)["message"])
            body = json.dumps({"result": {"response": {"modelResponse": {"message": reply}}}})
            await route.fulfill(status=status, content_type="application/x-ndjson", body=body)
        else:
            await route.fulfill(content_type="text/html", body=LANDING)

    await provider.context.route("**/*", handle)
    return provider, seen


async def test_real_browser_submission_capture_and_tab_cleanup(settings):
    provider, seen = await prepared(settings)
    try:
        initial = len(provider.context.pages)
        assert await provider.complete("hello fixture") == "fixture answer"
        assert seen == ["hello fixture"]
        assert len(provider.context.pages) == initial
    finally:
        await provider.close()


@pytest.mark.parametrize(
    "status,code",
    [(401, "authentication_required"), (403, "access_denied"), (429, "rate_limit_exceeded")],
)
async def test_real_browser_upstream_errors(settings, status, code):
    provider, _ = await prepared(settings, status=status)
    try:
        with pytest.raises(BridgeError) as err:
            await provider.complete("hello")
        assert err.value.status == status and err.value.code == code
    finally:
        await provider.close()


async def test_browser_cancellation_and_busy(settings):
    provider, _ = await prepared(settings)
    submitted = asyncio.Event()
    never = asyncio.Event()

    async def hold(route):
        submitted.set()
        await never.wait()

    await provider.context.route("**/rest/app-chat/conversations/new", hold)
    initial = len(provider.context.pages)
    task = asyncio.create_task(provider.complete("hold"))
    try:
        await asyncio.wait_for(submitted.wait(), 10)
        with pytest.raises(BridgeError) as err:
            await provider.complete("second")
        assert err.value.code == "provider_busy"
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        assert len(provider.context.pages) == initial
        assert not provider.lock.locked()
    finally:
        never.set()
        await provider.close()


async def test_verification_page_is_not_retried(settings):
    provider, _ = await prepared(settings)
    hits = []

    async def challenge(route):
        hits.append(route.request.url)
        await route.fulfill(
            content_type="text/html", body="<title>Just a moment</title><p>Verify you are human</p>"
        )

    await provider.context.route("**/*", challenge)
    try:
        with pytest.raises(BridgeError) as err:
            await provider.complete("hello")
        assert err.value.code == "verification_required"
        assert len(hits) == 1
    finally:
        await provider.close()
