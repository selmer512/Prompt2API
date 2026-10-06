"""Local persistent-browser transport. No cookie exports or private HTTP replay."""

import asyncio
import os
import re
from urllib.parse import urlparse

from .errors import BridgeError
from .providers.base import BrowserSettings, ProviderSpec
from .providers.grok import decode_response, is_chat_response


async def page_problem(page):
    # Examine visible UI only; never log or persist body text.
    if urlparse(page.url).path.startswith(("/sign-in", "/login", "/auth")):
        raise BridgeError(
            "Website requires an account for this session; anonymous chat is unavailable",
            "authentication_required",
            401,
        )
    checks = [
        (
            r"verify (?:that )?you are human|checking your browser|rejected by anti-bot|"
            r"unusual traffic|just a moment",
            "Website requires human verification",
            "verification_required",
            403,
        ),
        (
            r"you(?:'ve| have) reached.{0,60}(?:limit|quota)|rate limit|too many requests|"
            r"message limit reached",
            "Website chat quota is exhausted",
            "rate_limit_exceeded",
            429,
        ),
    ]
    # Scope to dialogs/alerts and challenge pages; assistant text may discuss these words.
    alerts = await page.locator('[role="alert"], [role="dialog"]').all_text_contents()
    if any(urlparse(frame.url).hostname == "challenges.cloudflare.com" for frame in page.frames):
        raise BridgeError("Website requires human verification", "verification_required", 403)
    title = await page.title()
    text = "\n".join(alerts + [title])
    for pattern, message, code, status in checks:
        if re.search(pattern, text, re.I | re.S):
            raise BridgeError(message, code, status)


async def visible_editable(locator):
    matches = []
    for candidate in await locator.all():
        if await candidate.is_visible() and await candidate.is_editable():
            matches.append(candidate)
    return matches


async def find_composer(page, spec):
    matches = await visible_editable(page.locator(spec.composer))
    if matches:
        return matches[0]
    if spec.name == "grok":
        matches = await visible_editable(
            page.get_by_role("textbox", name="Ask Grok anything", exact=True)
        )
        if matches:
            return matches[0]
        # On Grok's landing page only, tolerate a changed accessible label when
        # there is exactly one visible editable textarea. Never guess between inputs.
        location = urlparse(page.url)
        if location.hostname == "grok.com" and location.path == "/":
            matches = await visible_editable(page.locator("textarea"))
            if len(matches) == 1:
                return matches[0]
    return None


class BrowserProvider:
    def __init__(self, spec: ProviderSpec, settings: BrowserSettings):
        self.spec, self.settings = spec, settings
        self.lock = asyncio.Lock()
        self.context = None
        self.playwright = None
        self.stage = "idle"
        self.failed_page = None
        self.diagnostics = None

    async def start(self):
        if self.context:
            return
        from playwright.async_api import async_playwright

        profile = self.settings.profile_root / self.spec.name
        profile.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            profile.chmod(0o700)
        self.playwright = await async_playwright().start()
        try:
            self.context = await self.playwright.chromium.launch_persistent_context(
                str(profile),
                headless=self.settings.headless,
                channel=self.settings.channel,
                executable_path=self.settings.executable_path,
            )
            self.context.set_default_timeout(0)
            self.context.set_default_navigation_timeout(0)
        except BaseException:
            await self.playwright.stop()
            self.playwright = None
            raise

    async def close(self):
        try:
            if self.context:
                await self.context.close()
        finally:
            self.context = None
            self.failed_page = None
            if self.playwright:
                await self.playwright.stop()
                self.playwright = None

    async def complete(self, prompt: str) -> str:
        if len(prompt) > self.settings.max_prompt_chars:
            raise BridgeError(
                "Prompt exceeds the configured website input limit", "context_length_exceeded", 400
            )
        if self.lock.locked():
            raise BridgeError(
                "Provider browser is busy; retry when its current request completes",
                "provider_busy",
                429,
            )
        async with self.lock:
            self.diagnostics = None
            self.stage = "starting_browser"
            await self.start()
            if self.failed_page is not None:
                if not self.failed_page.is_closed():
                    await self.failed_page.close()
                self.failed_page = None
            self.stage = "opening_tab"
            page = await self.context.new_page()
            keep_page = False
            tasks = set()
            result = asyncio.get_running_loop().create_future()

            async def capture(response):
                try:
                    if response.status in (401, 403, 429):
                        codes = {
                            401: "authentication_required",
                            403: "access_denied",
                            429: "rate_limit_exceeded",
                        }
                        raise BridgeError(
                            "Grok chat request was rejected",
                            codes[response.status],
                            response.status,
                        )
                    if response.status >= 400:
                        raise BridgeError(
                            "Grok chat service returned an HTTP error", "upstream_http_error"
                        )
                    self.stage = "reading_response"
                    answer = decode_response(await response.body())
                    if not result.done():
                        result.set_result(answer)
                except asyncio.CancelledError:
                    raise
                except BridgeError as exc:
                    if not result.done():
                        result.set_exception(exc)
                except Exception:
                    if not result.done():
                        result.set_exception(
                            BridgeError(
                                "Could not read the completed Grok response",
                                "upstream_connection_error",
                            )
                        )

            def on_response(response):
                if is_chat_response(response.url) and response.request.method == "POST":
                    task = asyncio.create_task(capture(response))
                    tasks.add(task)
                    task.add_done_callback(tasks.discard)

            def on_failed(request):
                if is_chat_response(request.url) and request.method == "POST" and not result.done():
                    result.set_exception(
                        BridgeError("Grok chat connection failed", "upstream_connection_error")
                    )

            try:
                self.stage = "opening_website"
                await page.goto(self.spec.url, wait_until="domcontentloaded")
                self.stage = "checking_website"
                await page_problem(page)
                self.stage = "waiting_page_load"
                await page.wait_for_load_state("load")
                await page_problem(page)
                # Grok cookie notice is a separate modal from its composer.
                reject = page.get_by_role("button", name="Reject All", exact=True)
                if await reject.is_visible():
                    await reject.click()
                self.stage = "finding_composer"
                composer = await find_composer(page, self.spec)
                if composer is None:
                    visible_textareas = await visible_editable(page.locator("textarea"))
                    self.diagnostics = {
                        "host": urlparse(page.url).hostname,
                        "textareas": await page.locator("textarea").count(),
                        "visible_editable_textareas": len(visible_textareas),
                        "textboxes": await page.get_by_role("textbox").count(),
                    }
                    keep_page = not self.settings.headless
                    detail = ", ".join(f"{k}={v}" for k, v in self.diagnostics.items())
                    hint = " Failed browser tab kept open for inspection." if keep_page else ""
                    raise BridgeError(
                        f"Chat composer unavailable ({detail}).{hint}",
                        "composer_unavailable",
                        503,
                    )
                if self.spec.name == "grok":
                    page.on("response", on_response)
                    page.on("requestfailed", on_failed)
                baseline = (
                    await page.locator(self.spec.response).count() if self.spec.response else 0
                )
                self.stage = "filling_prompt"
                await composer.fill(prompt)
                submit_matches = [
                    candidate
                    for candidate in await page.locator(self.spec.submit).all()
                    if await candidate.is_visible() and await candidate.is_enabled()
                ]
                if not submit_matches:
                    raise BridgeError(
                        "Chat submit control is unavailable", "composer_unavailable", 503
                    )
                self.stage = "submitting_prompt"
                await submit_matches[0].click()
                if self.stage == "submitting_prompt":
                    self.stage = "waiting_response"
                if self.spec.name == "grok":
                    while not result.done():
                        await page_problem(page)
                        await asyncio.sleep(0.25)
                    return result.result()
                return await self.wait_dom_response(page, baseline)
            finally:
                # Cancellation closes only this request's tab, interrupting the web generation.
                for task in tasks:
                    task.cancel()
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
                if not result.done():
                    result.cancel()
                elif not result.cancelled():
                    result.exception()  # Retrieve any exception even if UI failed first.
                self.stage = "closing_tab"
                try:
                    if keep_page:
                        self.failed_page = page
                    else:
                        await page.close()
                finally:
                    self.stage = "inspection_required" if keep_page else "idle"

    async def wait_dom_response(self, page, baseline):
        """Experimental DOM adapters require an observed busy -> idle transition."""
        saw_busy = False
        while True:
            await page_problem(page)
            busy = page.locator(self.spec.busy)
            generating = await busy.count() > 0 and await busy.last.is_visible()
            saw_busy = saw_busy or generating
            replies = page.locator(self.spec.response)
            if saw_busy and not generating and await replies.count() > baseline:
                text = await replies.last.inner_text()
                if text.strip():
                    return text
            await asyncio.sleep(0.25)
