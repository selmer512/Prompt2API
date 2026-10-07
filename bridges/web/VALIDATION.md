# Web bridge validation

## ChatGPT adapter update (2026-10-07 UTC)

The live ChatGPT page exposed a signed-out `Chat with ChatGPT` textarea and an
enabled `Send message` button after filling a synthetic draft. The page's read-only
conversation state reported `authenticated=false` and `canSubmit=true`.
No prompt was submitted: the page states that use agrees to its Terms, and live
submission is pending user confirmation under the browser confirmation policy.
The inspected guest screen is saved as [composer evidence](validation/chatgpt-guest-composer.jpg).

The ChatGPT module now handles this composer variant, completion controls for fast
replies, and Markdown-only assistant output where available. It remains opt-in and
experimental. A ChatGPT-only config listens on 8321, with a separate browser profile.
The smoke script can select the model and endpoint rather than assuming Grok.

Non-browser tests cover the ChatGPT API/tool-result loop, partial output suppression,
fast completion, stale completion controls, cancellation and config selection. A
Chromium fixture exercises the new textarea/send/completion controls, but Chromium
cannot launch here: Unix socket creation returns `Operation not permitted`.
These checks do not establish that the live ChatGPT response DOM matches the module.
Validation passed: 39 non-browser tests, Ruff check/format check, and the required
Go server build using Go 1.26.1. Ten Chromium tests were excluded for the socket restriction.

## Initial Grok implementation

Tested on 2026-10-05 with Python 3.12.14, Playwright 1.58.0 and Go 1.26.0.

## Passed

- 26 protocol/API/config tests using the actual FastAPI application in-process.
- Tool request -> validated OpenAI call -> harness tool result -> next model response.
- Named/required/disabled tool selection, argument JSON Schema validation, parallel
  policy, malformed output, orphan tool results and text-only input validation.
- SSE tool chunks, error events, quota/auth response mapping, request size limit,
  bearer authentication, error redaction and client cancellation.
- Ruff check and formatting check for the new Python package.
- Existing Go server compilation: `go build -o /tmp/prompt2api-core-check ./cmd/server`.
- Relevant existing Go configuration tests:
  `go test ./internal/config -run 'Test.*(OpenAI|Compatibility|V8)' -count=1`.
- Live read-only inspection of Grok's composer confirmed
  `textarea[aria-label="Ask Grok anything"]` and `button[aria-label="Submit"]`.

## Blocked or not yet verified

Six actual Chromium fixture tests are included but could not run in this workspace.
The local Chrome process aborts with `socket() failed: Operation not permitted`
while creating its process-singleton socket. This occurs before any fixture navigation;
it is an execution-environment limitation, not a passing transport test.

No live chat was submitted to Grok. Live inference, its current completed response
shape and the full Grok -> Hermes tool loop therefore remain unverified. Run the
provided `examples/hermes-smoke.py` after initializing the local browser profile.
The script makes two live model requests and validates the returned tool-result loop.

Claude and Gemini selector modules are experimental and have not been verified
against live sessions. ChatGPT's current validation is documented above. All three
are disabled in the default config and omitted from model listings unless explicitly
enabled. Their existence is not evidence of live inference support.

The entire inherited Go test suite was not run: the change adds a Python sidecar,
routing example and documentation; it does not edit Go implementation files.
