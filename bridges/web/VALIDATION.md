# Validation of the initial Grok web bridge

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

ChatGPT, Claude and Gemini selector modules are experimental and have not been
verified against live sessions. They are disabled by default and omitted from model
listings unless explicitly enabled. Their existence is not evidence of live support.

The entire inherited Go test suite was not run: the change adds a Python sidecar,
routing example and documentation; it does not edit Go implementation files.
