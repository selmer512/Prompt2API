from unittest.mock import AsyncMock, Mock

import pytest

from prompt2api_web.browser import GROK_SERVICE_NOTICE, page_problem
from prompt2api_web.errors import BridgeError


def elements(*visible):
    return Mock(
        all=AsyncMock(
            return_value=[
                Mock(
                    is_visible=AsyncMock(return_value=value),
                    is_editable=AsyncMock(return_value=True),
                )
                for value in visible
            ]
        )
    )


def website(*, service=(), continuation=(), signup=(), editors=()):
    page = Mock(url="https://grok.com/c/guest", frames=[], title=AsyncMock(return_value="Grok"))
    page.locator = Mock(
        side_effect=lambda selector: (
            elements(*editors) if selector == 'textarea, [role="textbox"]' else elements()
        )
    )
    page.get_by_text = Mock(
        side_effect=lambda text, **kwargs: (
            elements(*service) if text == GROK_SERVICE_NOTICE else elements(*continuation)
        )
    )
    page.get_by_role = Mock(return_value=elements(*signup))
    return page


async def test_visible_grok_service_notice_returns_explicit_failure():
    with pytest.raises(BridgeError) as failure:
        await page_problem(website(service=(False, True)))
    assert failure.value.code == "upstream_service_unavailable"
    assert failure.value.status == 503


async def test_signup_continuation_without_guest_composer_is_reported():
    with pytest.raises(BridgeError) as failure:
        await page_problem(website(continuation=(True,), signup=(True,), editors=(False,)))
    assert failure.value.code == "anonymous_session_unavailable"
    assert failure.value.status == 403


async def test_signup_promotion_with_working_composer_does_not_block_chat():
    await page_problem(website(continuation=(True,), signup=(True,), editors=(True,)))


async def test_hidden_service_notice_does_not_block_chat():
    await page_problem(website(service=(False,)))


async def test_grok_specific_notices_do_not_block_other_providers():
    page = website(service=(True,))
    page.url = "https://another-provider.example/chat"
    await page_problem(page)
