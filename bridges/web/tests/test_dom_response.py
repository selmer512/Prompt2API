"""Test response settlement without requiring Chromium process permissions."""

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from prompt2api_web.browser import BrowserProvider
from prompt2api_web.providers.chatgpt import SPEC


class Transcript:
    def __init__(self, frames):
        self.frames = iter(frames)
        self.state = next(self.frames)

    async def advance(self, delay):
        try:
            self.state = next(self.frames)
        except StopIteration:
            # A pending, unproven completion must remain cancellable.
            raise asyncio.CancelledError

    def locator(self, selector):
        if selector == SPEC.busy:
            visible = self.state.get("busy", False)
            nodes = [Mock(is_visible=AsyncMock(return_value=visible))]
        elif selector == SPEC.finished:
            nodes = [Mock(is_visible=AsyncMock(return_value=True))] * self.state.get("finished", 0)
        elif selector == SPEC.response:
            text = self.state.get("text")
            nodes = (
                []
                if text is None
                else [
                    Mock(
                        is_visible=AsyncMock(return_value=True),
                        inner_text=AsyncMock(return_value=text + "\nCopy response"),
                        locator=Mock(return_value=self.locator(SPEC.response_content)),
                    )
                ]
            )
        elif selector == SPEC.response_content:
            nodes = [Mock(inner_text=AsyncMock(return_value=self.state.get("text", "")))]
        else:
            raise AssertionError(selector)
        return Mock(
            all=AsyncMock(return_value=nodes),
            count=AsyncMock(return_value=len(nodes)),
            last=nodes[-1] if nodes else None,
        )


async def settle(monkeypatch, settings, frames, completed_baseline=0):
    page = Transcript(frames)
    monkeypatch.setattr("prompt2api_web.browser.page_problem", AsyncMock())
    monkeypatch.setattr("prompt2api_web.browser.asyncio.sleep", page.advance)
    provider = BrowserProvider(SPEC, settings.browser)
    return await provider.wait_dom_response(page, 0, completed_baseline)


async def test_partial_answer_is_not_returned_while_generating(monkeypatch, settings):
    answer = await settle(
        monkeypatch,
        settings,
        [
            {"busy": True, "text": "partial", "finished": 1},
            {"busy": True, "text": "still partial", "finished": 1},
            {"busy": False, "text": '{"content":"complete","tool_calls":[]}', "finished": 1},
        ],
    )
    assert answer == '{"content":"complete","tool_calls":[]}'


async def test_fast_answer_can_finish_without_observing_stop_button(monkeypatch, settings):
    assert await settle(monkeypatch, settings, [{"text": "complete", "finished": 1}]) == "complete"


async def test_old_completion_controls_do_not_finalize_new_partial_answer(monkeypatch, settings):
    with pytest.raises(asyncio.CancelledError):
        await settle(
            monkeypatch, settings, [{"text": "partial", "finished": 1}], completed_baseline=1
        )


async def test_text_stability_alone_is_not_proof_of_completion(monkeypatch, settings):
    with pytest.raises(asyncio.CancelledError):
        await settle(monkeypatch, settings, [{"text": "paused output"}, {"text": "paused output"}])
