"""Exercise a real browser-provider tool round trip, without Hermes installed.

Uses the standard library. Run after serve (no login step for guest chat):
PROMPT2API_WEB_KEY=... python bridges/web/examples/hermes-smoke.py
PROMPT2API_WEB_KEY=... python bridges/web/examples/hermes-smoke.py --model chatgpt-web \
    --base-url http://127.0.0.1:8321/v1
"""

import argparse
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--model", default=os.environ.get("PROMPT2API_WEB_MODEL", "grok-web"))
parser.add_argument(
    "--base-url", default=os.environ.get("PROMPT2API_WEB_URL", "http://127.0.0.1:8320/v1")
)
args = parser.parse_args()
url = args.base_url.rstrip("/")
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
            "model": args.model,
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


print(
    f"[1/2] Asking {args.model} to request the fixture tool; waiting for the bridge...", flush=True
)
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
print(
    f"[2/2] Tool call received and executed; asking {args.model} to use its result...", flush=True
)
final = invoke("none")
if final.get("tool_calls") or "ORCHID" not in (final.get("content") or ""):
    raise SystemExit("FAIL: final response did not use the actual tool result")
print(f"PASS: {args.model} selected a function; local harness executed it; model used the result.")
print(final["content"])
