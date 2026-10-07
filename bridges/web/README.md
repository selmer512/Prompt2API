# Prompt2API Web Bridge

Turns a local browser chat session into an OpenAI-compatible inference endpoint for
Hermes and other agent harnesses. This service lives alongside the existing Go
proxy; it can be used directly or configured as an upstream for that proxy.

## Provider modules

| Module | Route | Transport | Status |
| --- | --- | --- | --- |
| Grok | `grok-web` | Browser UI submission + completed website response capture | First implementation; composer inspected live, inference still needs a live account test |
| ChatGPT | `chatgpt-web` | Browser UI + DOM response extraction | Experimental, disabled; selectors not verified live |
| Claude | `claude-web` | Browser UI + DOM response extraction | Experimental, disabled; selectors not verified live |
| Gemini | `gemini-web` | Browser UI + DOM response extraction | Experimental, disabled; selectors not verified live |

Each provider has its own module, origin, browser profile and concurrency lock.
The common transport and tool protocol are shared. A route identifies a website
provider, **not a specific model version**. The website's default model for a new
chat is used; the service does not promise a particular model or upgrade access.

## Install and start (WSL/Linux/macOS)

From the repository root, Python 3.11+:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e 'bridges/web[test]'
python -m playwright install chromium
# On Linux only, if browser system libraries are missing:
# python -m playwright install-deps chromium

cp bridges/web/bridge.example.toml bridges/web/bridge.toml
# Optional: review website notices in a visible browser while staying signed out.
prompt2api-web prepare grok
```

Grok uses the website's anonymous chat path: **no Grok account or sign-in is
required by the bridge**. You can skip `prepare` and start the service directly.
The optional `prepare` command opens a visible browser to review website notices
and confirm the anonymous chat box is available. Stay signed out, then press Enter
in the terminal. Anonymous inference still requires a live test; availability and
quota follow the website. If Grok requires an account for your session, the bridge
reports that error rather than asking you to sign in automatically.
Browser session data stays under `~/.prompt2api-web/profiles/grok`; a profile also
stores anonymous site state and does not imply a logged-in account. The service
never asks you to paste cookies or provider passwords into configuration. `login`
remains an alias of `prepare` for compatibility with earlier instructions.

WSL needs WSLg or another display for optional visible setup. Alternatively,
run the bridge natively on Windows using Python and installed Chrome:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e 'bridges/web[test]'
.\.venv\Scripts\prompt2api-web.exe prepare grok --channel chrome
```

For a custom Chromium binary, set `executable_path` under `[browser]` and pass the
same path as `--executable-path` to prepare. Tests can use `PROMPT2API_TEST_BROWSER`
to select an installed binary instead of Playwright's bundled Chromium.

For installed Chrome, set `channel = "chrome"` in the `[browser]` section. Use the
same profile root for prepare and serve. Do not run two processes against one profile.
To observe requests locally, set `headless = false` before starting the service.

Set a random client bearer key and start the bridge:

```bash
export PROMPT2API_WEB_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
prompt2api-web serve --config bridges/web/bridge.toml
```

Windows equivalent:

```powershell
$env:PROMPT2API_WEB_KEY = & .\.venv\Scripts\python.exe -c 'import secrets; print(secrets.token_urlsafe(32))'
.\.venv\Scripts\prompt2api-web.exe serve --config bridges/web/bridge.toml
```

Use the same key in your client. Default listener: `127.0.0.1:8320`. The key belongs
to **your bridge**, not xAI. Browser launch is lazy; `/healthz` is liveness, not proof
that a provider can complete inference. Model listings explicitly
mark account readiness as unchecked.

## Connect Hermes

Run `hermes model` outside an active Hermes conversation. Select **Custom endpoint
(self-hosted / VLLM / etc.)**, then enter:

- API base URL: `http://127.0.0.1:8320/v1`
- API key: the value of `PROMPT2API_WEB_KEY`
- Model: `grok-web`
- If asked for transport, choose OpenAI Chat Completions.

Do not select xAI OAuth for this web-chat path. Use a reachable host address if
Hermes and the bridge run on separate machines or different WSL/Windows networks.
A loopback address works only when both processes can reach the same loopback
listener. The web adapter does not discover the website's actual context window;
configure Hermes conservatively and inspect its real requests before raising limits.

You can instead use the Go proxy on port 8317. Merge the provider entry from
[examples/cliproxy.yaml](examples/cliproxy.yaml) into your existing v8 configuration,
replacing both keys. Preserve existing providers and configuration. Run the sidecar,
then the existing Go server with that configuration. Point Hermes at
`http://127.0.0.1:8317/v1` using the Go proxy's client key and model `grok-web`.

## Verify against live Grok

In another terminal, activate the environment and set the same client key:

```bash
curl http://127.0.0.1:8320/v1/models \
  -H "Authorization: Bearer $PROMPT2API_WEB_KEY"

python bridges/web/examples/hermes-smoke.py
```

The smoke script sends **two chats**: it requires Grok to request a local fixture
function, executes that function in the harness, then verifies the next Grok reply
uses the returned verification word. It executes only that named test function.
This script tests the live model/protocol boundary; it does not claim to run Hermes.
It prints progress before each request. If it waits, query `/v1/providers` with the
same bearer key from another terminal: `stage` identifies browser startup, website
navigation, page loading, prompt entry/submission, or response capture. This status
contains no prompts, response bodies, URLs, or provider session credentials.
If the composer is missing, status includes only the page host and input counts.
With `headless = false`, the failed tab stays open for inspection; the next request
replaces that tab. The adapter chooses a visible editable input and can tolerate
a changed Grok textarea label only when the landing page has exactly one candidate.
For SSH/Termius, set `headless = true` to run without a desktop window. The same
status endpoint reports whether a chat request and response were observed, plus
the latest eight Grok REST POST route shapes and HTTP statuses. Conversation IDs,
unknown path segments, query strings, headers, and request/response bodies are
excluded. A click alone does not prove the site submitted a chat request.
The adapter reports Grok's visible service-issues notice as
`upstream_service_unavailable`. A visible continuation/signup panel is reported as
`anonymous_session_unavailable` only when there is no editable guest composer.
Neither error triggers login or bypasses the website's access controls. Anonymous
access must actually be available in the browser for inference to succeed.
For streaming calls, HTTP 200 means the SSE stream opened; a later error event can
still report website failure before any model output arrives.

## How agent tools work

1. The client sends complete conversation history and function JSON Schemas.
2. The bridge serializes role-labelled history and tool definitions into a prompt.
3. A new website chat is opened for every API call, using the same local profile.
4. The website generates a plain-text JSON envelope with content and requested tools.
5. The bridge validates names, argument schemas, `tool_choice`, and parallel-call policy.
6. It returns normal OpenAI `tool_calls` with newly assigned call IDs.
7. Hermes executes tools and sends matching `tool` messages in the next request.

The bridge **never executes tools**. It verifies complete tool-result history and
rejects malformed action output instead of trying to repair it by spending another
chat turn. System/developer roles are emulated in text, not native upstream roles.
The model may fail to follow them; the client harness retains control of tool execution.

Grok response parsing consumes the final `modelResponse.message` in the browser's
own completed NDJSON response, not reasoning/search token fragments. No standalone
requests are replayed against private endpoints. ChatGPT/Claude/Gemini currently
use DOM extraction and require an observed generation-busy to idle transition;
validate selectors locally before enabling those modules.

## API and limits

- `GET /healthz`: process liveness, no account inference check.
- `GET /v1/models`: enabled routes and explicit capabilities; bearer key required.
- `GET /v1/providers`: browser started/busy status; bearer key required.
- `POST /v1/chat/completions`: text, function calls, nonstreaming and buffered SSE.
- SSE sends keepalive comments while waiting, then validated content/tool chunks and
  `[DONE]`. Errors after streaming starts are OpenAI-style error events (HTTP is already 200).
- No token usage numbers are invented; usage is omitted. `stream_options.include_usage`
  does not manufacture counts.
- Sampling, reasoning, token-limit and cache hints are accepted for SDK compatibility
  but are **not enforceable through the website**. Unsupported fields, multimodal input,
  multiple choices, built-in provider tools and schema response formats are rejected.
- `response_format: {"type":"json_object"}` is supported via a JSON envelope; its
  assistant content must itself parse as a JSON object.
- One active request per provider/profile; concurrent submissions return 429.
- Full history is replayed each call; large prompts fail without silent truncation.
- No inference deadline is imposed, consistent with the Go repository conventions.
  Set a deadline in the client. Disconnect/cancellation closes the request tab and
  releases the provider lock. Upstream generation may still finish server-side.
- Request body limit: 2 MB. Serialized prompt limit: 200,000 characters by default.
- Free quota remains free website quota. No account rotation, CAPTCHA handling,
  fingerprint alteration or quota bypass is implemented. Verification or entitlement
  blocks return errors; provider failures do not trigger automatic resubmission.

## Add or enable providers

Each module exports a `ProviderSpec` in `prompt2api_web/providers/`; add it to `SPECS`
and configure it in TOML. For experimental providers, set both `enabled = true` and
`allow_experimental = true`. Override `composer`, `submit`, `response`, and `busy`
selectors in that provider's section when its UI changes. URLs are fixed by modules.
No experimental route appears in `/v1/models` unless explicitly enabled.

## Tests

```bash
python -m pytest bridges/web/tests -m "not browser" -q
# After installing Chromium, run actual browser fixtures:
python -m pytest bridges/web/tests -m browser -q
ruff check --config bridges/web/pyproject.toml bridges/web
```

Tests cover the API/tool round trip, JSON validation, quota/auth errors, SSE, client
cancellation and provider selection. Chromium tests intercept every browser request
with a fixture: they exercise UI submission, response capture and tab cleanup without
sending anything to a real provider. Passing fixtures alone does not prove that
current Grok inference or the other websites work with your account.

Treat browser profiles as credentials: keep them out of git and restrict local access.
The service binds to loopback by default and requires a bearer key on model/provider
and inference routes. Prompts, response bodies, provider cookies and model reasoning
are not logged. HTTP access logs contain method/path/status only.
