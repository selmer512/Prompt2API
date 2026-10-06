"""Exercise the real bridge -> Grok -> tool -> Grok round trip, without Hermes installed.

Uses the standard library. Run after login and serve:
PROMPT2API_WEB_KEY=... python bridges/web/examples/hermes-smoke.py
"""

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

url = os.environ.get("PROMPT2API_WEB_URL", "http://127.0.0.1:8320/v1")
key = os.environ["PROMPT2API_WEB_KEY"]
fixture = Path(__file__).parent / "smoke-input.txt"
fixture.write_text("The verification word is ORCHID.\n", encoding="utf-8")
messages = [
    {
        "role": "user",
        "content": "Call read_fixture, then report the verification word from its result. Do not guess it.",
    }
]
tools = [
    {
        "type": "function",
        "function": {
            "name": "read_fixture",
            "description": "Read the local test fixture",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    }
]


def invoke(choice):
    body = json.dumps(
        {
            "model": "grok-web",
            "messages": messages,
            "tools": tools,
            "tool_choice": choice,
            "parallel_tool_calls": False,
        }
    ).encode()
    request = urllib.request.Request(
        url + "/chat/completions",
        data=body,
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request) as response:
            return json.load(response)["choices"][0]["message"]
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"Bridge returned HTTP {exc.code}: {exc.read().decode()}") from exc


print("[1/2] Asking anonymous Grok to request the fixture tool; waiting for the bridge...", flush=True)
message = invoke({"type": "function", "function": {"name": "read_fixture"}})
calls = message.get("tool_calls", [])
if len(calls) != 1 or calls[0]["function"]["name"] != "read_fixture":
    raise SystemExit("FAIL: expected one read_fixture call")
if json.loads(calls[0]["function"]["arguments"]) != {}:
    raise SystemExit("FAIL: unexpected function arguments")
messages.append(message)
messages.append(
    {"role": "tool", "tool_call_id": calls[0]["id"], "content": fixture.read_text(encoding="utf-8")}
)
print("[2/2] Tool call received and executed; asking Grok to use its result...", flush=True)
final = invoke("none")
if final.get("tool_calls") or "ORCHID" not in (final.get("content") or ""):
    raise SystemExit("FAIL: final response did not use the actual tool result")
print("PASS: Grok selected a function; local harness executed it; Grok used the matching result.")
print(final["content"])
