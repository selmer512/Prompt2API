import json

import pytest
from prompt2api_web.errors import BridgeError
from prompt2api_web.protocol import ChatRequest, build_prompt, parse_reply
from prompt2api_web.providers.grok import decode_response, is_chat_response
from pydantic import ValidationError


def request(tool, **kwargs):
    return ChatRequest(
        model="grok-web",
        messages=[{"role": "user", "content": "Fix the file"}],
        tools=[tool],
        **kwargs,
    )


def test_tool_round_trip(tool):
    req = request(tool)
    msg = parse_reply(
        '{"content":null,"tool_calls":[{"name":"read_file","arguments":{"path":"app.py"}}]}', req
    )
    call = msg["tool_calls"][0]
    followup = ChatRequest(
        model="grok-web",
        tools=[tool],
        messages=req.messages
        + [msg, {"role": "tool", "tool_call_id": call["id"], "content": "print('hello')"}],
    )
    prompt = build_prompt(followup)
    assert call["id"] in prompt and "print('hello')" in prompt
    assert parse_reply('{"content":"The file prints hello.","tool_calls":[]}', followup) == {
        "role": "assistant",
        "content": "The file prints hello.",
    }


@pytest.mark.parametrize(
    "text",
    [
        "not json",
        '{"content":null,"tool_calls":[{"name":"delete_everything","arguments":{}}]}',
        '{"tool_calls":[{"name":"read_file","arguments":{"path":1}}]}',
        '{"tool_calls":[{"name":"read_file","arguments":{"path":"x","extra":true}}]}',
        '{"content": null}',
        '[{"content":"hi"}]',
        '{"content":"hi","extra":"ignored?"}',
    ],
)
def test_invalid_tool_output_never_dispatches(tool, text):
    with pytest.raises(BridgeError):
        parse_reply(text, request(tool))


def test_named_required_none_and_parallel(tool):
    action = '{"content":null,"tool_calls":[{"name":"read_file","arguments":{"path":"x"}}]}'
    assert parse_reply(
        action, request(tool, tool_choice={"type": "function", "function": {"name": "read_file"}})
    )["tool_calls"]
    with pytest.raises(BridgeError):
        parse_reply(action, request(tool, tool_choice="none"))
    with pytest.raises(BridgeError):
        parse_reply('{"content":"done"}', request(tool, tool_choice="required"))
    obj = json.loads(action)
    obj["tool_calls"] *= 2
    with pytest.raises(BridgeError):
        parse_reply(json.dumps(obj), request(tool, parallel_tool_calls=False))


def test_text_and_json_mode():
    req = ChatRequest(model="grok-web", messages=[{"role": "user", "content": "hi"}])
    assert parse_reply("hello", req)["content"] == "hello"
    req.response_format = {"type": "json_object"}
    assert (
        parse_reply('{"content":"{\\"ok\\":true}","tool_calls":[]}', req)["content"]
        == '{"ok":true}'
    )
    with pytest.raises(BridgeError):
        parse_reply('{"content":"not JSON"}', req)


@pytest.mark.parametrize(
    "changes",
    [
        {"messages": [{"role": "tool", "content": "x", "tool_call_id": "orphan"}]},
        {
            "messages": [
                {"role": "user", "content": [{"type": "image_url", "image_url": {"url": "x"}}]}
            ]
        },
        {"tools": [{"type": "function", "function": "bad"}]},
        {"tool_choice": {"type": "function", "function": "bad"}},
        {"messages": [{"role": "assistant", "tool_calls": "bad"}]},
        {"stop": ["no"]},
        {"n": 2},
    ],
)
def test_invalid_requests(changes):
    with pytest.raises(ValidationError):
        ChatRequest.model_validate(
            {"model": "grok-web", "messages": [{"role": "user", "content": "hi"}], **changes}
        )


def test_grok_final_message_excludes_thinking_tokens():
    body = b"\n".join(
        [
            b'{"result":{"response":{"token":"private reasoning"}}}',
            b'{"result":{"response":{"modelResponse":{"message":"answer"}}}}',
        ]
    )
    assert decode_response(body) == "answer"
    assert decode_response(b'{"result":{"modelResponse":{"message":"followup"}}}') == "followup"
    with pytest.raises(BridgeError):
        decode_response(b'{"result":{"response":{"token":"incomplete"}}}')
    with pytest.raises(BridgeError):
        decode_response(b'{"error":{"message":"internal token"}}')


def test_capture_only_chat_response():
    assert is_chat_response("https://grok.com/rest/app-chat/conversations/new")
    assert is_chat_response("https://grok.com/rest/app-chat/conversations/123/responses")
    assert not is_chat_response("https://grok.com.evil/rest/app-chat/conversations/new")
    assert not is_chat_response("https://grok.com/rest/user-settings")
