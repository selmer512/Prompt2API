import asyncio
import hmac
import json
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse

from .browser import BrowserProvider
from .config import Settings
from .errors import BridgeError
from .protocol import ChatRequest, build_prompt, parse_reply


def frame(value):
    return "data: " + json.dumps(value, ensure_ascii=False) + "\n\n"


def completion(model, message, request_id, created):
    return {
        "id": request_id,
        "object": "chat.completion",
        "created": created,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": "tool_calls" if message.get("tool_calls") else "stop",
            }
        ],
    }


def chunks(model, message, request_id, created):
    base = {"id": request_id, "object": "chat.completion.chunk", "created": created, "model": model}
    yield frame(
        {**base, "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]}
    )
    if message.get("content"):
        text = message["content"]
        for start in range(0, len(text), 256):
            yield frame(
                {
                    **base,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": text[start : start + 256]},
                            "finish_reason": None,
                        }
                    ],
                }
            )
    for index, call in enumerate(message.get("tool_calls", [])):
        yield frame(
            {
                **base,
                "choices": [
                    {
                        "index": 0,
                        "delta": {"tool_calls": [{"index": index, **call}]},
                        "finish_reason": None,
                    }
                ],
            }
        )
    finish = "tool_calls" if message.get("tool_calls") else "stop"
    yield frame({**base, "choices": [{"index": 0, "delta": {}, "finish_reason": finish}]})
    yield "data: [DONE]\n\n"


async def await_connected(task, request):
    try:
        while not task.done():
            await asyncio.wait({task}, timeout=0.25)
            if await request.is_disconnected():
                raise BridgeError("Client disconnected", "client_disconnected", 499)
        return task.result()
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


def create_app(settings: Settings, providers=None):
    if not settings.api_key:
        raise ValueError("A bridge client key is required")
    providers = (
        providers
        if providers is not None
        else {spec.model: BrowserProvider(spec, settings.browser) for spec in settings.providers}
    )

    @asynccontextmanager
    async def lifespan(app):
        yield
        for provider in providers.values():
            await provider.close()

    app = FastAPI(
        title="Prompt2API Web Bridge",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
    )

    async def authorize(request: Request):
        expected = "Bearer " + settings.api_key
        if not hmac.compare_digest(request.headers.get("authorization", ""), expected):
            raise BridgeError("Invalid bridge bearer key", "invalid_api_key", 401)

    @app.exception_handler(BridgeError)
    async def bridge_error(request, exc):
        return JSONResponse(exc.payload(), status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # Do not echo request input/prompt/tool arguments in error bodies.
        return JSONResponse(
            {
                "error": {
                    "message": "Invalid chat request",
                    "type": "invalid_request_error",
                    "code": "invalid_request_error",
                }
            },
            status_code=400,
        )

    @app.get("/healthz")
    async def health():
        return {"status": "ok", "browser_readiness": "not_checked"}

    @app.get("/v1/models", dependencies=[Depends(authorize)])
    async def models():
        return {
            "object": "list",
            "data": [
                {
                    "id": model,
                    "object": "model",
                    "created": 0,
                    "owned_by": provider.spec.name,
                    "metadata": {
                        "transport": "browser",
                        "tool_calling": "prompt_emulated",
                        "model_selection": "website_default",
                        "experimental": provider.spec.experimental,
                        "readiness": "not_checked",
                        "streaming": "buffered_validated",
                    },
                }
                for model, provider in providers.items()
            ],
        }

    @app.get("/v1/providers", dependencies=[Depends(authorize)])
    async def provider_status():
        return {
            "providers": [
                {
                    "name": p.spec.name,
                    "model": model,
                    "experimental": p.spec.experimental,
                    "busy": getattr(p, "lock", asyncio.Lock()).locked(),
                    "browser_started": getattr(p, "context", None) is not None,
                    "stage": getattr(p, "stage", "unknown"),
                    "diagnostics": getattr(p, "diagnostics", None),
                }
                for model, p in providers.items()
            ]
        }

    @app.post("/v1/chat/completions", dependencies=[Depends(authorize)])
    async def chat(request: Request):
        # Bound request memory before JSON parsing, including chunked transfer bodies.
        body = bytearray()
        async for piece in request.stream():
            body.extend(piece)
            if len(body) > settings.max_body_bytes:
                raise BridgeError("Request body is too large", "request_too_large", 413)
        try:
            req = ChatRequest.model_validate_json(bytes(body))
        except ValueError as exc:
            raise BridgeError(
                "Invalid chat request: check message/tool format and supported fields",
                "invalid_request_error",
                400,
            ) from exc
        if req.model not in providers:
            raise BridgeError("Requested web provider model is not enabled", "model_not_found", 404)
        prompt = build_prompt(req)
        if len(prompt) > settings.browser.max_prompt_chars:
            raise BridgeError(
                "Prompt exceeds the website input limit", "context_length_exceeded", 400
            )
        provider = providers[req.model]
        request_id, created = "chatcmpl-" + uuid.uuid4().hex, int(time.time())

        async def generate():
            try:
                text = await provider.complete(prompt)
                return parse_reply(text, req)
            except (BridgeError, asyncio.CancelledError):
                raise
            except Exception as exc:
                # Browser exceptions can contain locators, cookies, and page contents.
                raise BridgeError(
                    "Browser provider failed; check the local session and installation",
                    "browser_error",
                ) from exc

        if not req.stream:
            task = asyncio.create_task(generate())
            message = await await_connected(task, request)
            return completion(req.model, message, request_id, created)

        async def events():
            task = asyncio.create_task(generate())
            try:
                while not task.done():
                    done, _ = await asyncio.wait({task}, timeout=settings.keepalive_seconds)
                    if await request.is_disconnected():
                        return
                    if not done:
                        yield ": waiting for validated web response\n\n"
                for event in chunks(req.model, task.result(), request_id, created):
                    yield event
                # Token usage is omitted: browser UI does not report reliable counts.
            except BridgeError as exc:
                yield frame(exc.payload())
                yield "data: [DONE]\n\n"
            finally:
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return app
