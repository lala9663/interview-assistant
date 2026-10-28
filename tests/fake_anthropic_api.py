"""An in-process stand-in for the Claude API (api.anthropic.com), so the anthropic_api provider is
tested through the real SDK without a network: GET /v1/models/{id} and POST /v1/messages, with and
without streaming (SSE events). Answers come from FakeLLM's rules, so the app's own prompts get
schema-valid JSON; every answer starts with an (omitted) thinking block as Claude Opus 5.5 sends
one. Every request is kept for the tests to inspect; switches make it fail the ways the API does
(its own error bodies)."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx2
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from interview_assistant.providers.fake import FakeLLM

THINKING = {"type": "thinking", "thinking": "", "signature": "sig-fake"}


REQUEST_ID = {"request-id": "req_fake01"}  # the API names each request in this header


def error(status: int, kind: str, message: str, headers: dict[str, str] | None = None) -> JSONResponse:
    body = {"type": "error", "error": {"type": kind, "message": message}, "request_id": "req_fake01"}
    return JSONResponse(body, status_code=status, headers={**REQUEST_ID, **(headers or {})})


class FakeAnthropicAPI:
    def __init__(
        self,
        models: tuple[str, ...] = ("claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"),
        *,
        api_key: str | None = None,
        reported_model: str | None = None,
    ) -> None:
        self.models = list(models)
        self.api_key = api_key  # None: any key is accepted
        self.reported_model = reported_model  # the model the answer names (a fallback model)
        self.requests: list[dict[str, Any]] = []
        self.delay = 0.0  # seconds before answering
        self.echo_key = False  # error messages repeat the key they got (the provider must not)
        self.fail: tuple[int, str, str, dict[str, str]] | None = None  # status, type, message, headers
        self.refuse = False  # stop_reason "refusal" with stop_details
        self.truncate = False  # structured answers cut off at max_tokens
        self.not_json = False  # structured answers in prose
        self.stream_error = False  # an error event after the first streamed piece
        self.llm = FakeLLM(model="fake-on-claude-api")
        self.app = self._build()

    def transport(self) -> httpx2.ASGITransport:
        return httpx2.ASGITransport(app=self.app)

    def bodies(self, path: str = "/v1/messages") -> list[dict[str, Any]]:
        return [r["body"] for r in self.requests if r["path"] == path]

    def _refusal(self, request: Request) -> JSONResponse | None:
        given = request.headers.get("x-api-key", "")
        if self.api_key is not None and given != self.api_key:
            said = f"invalid x-api-key: {given}" if self.echo_key else "invalid x-api-key"
            return error(401, "authentication_error", said)
        if self.fail is not None:
            status, kind, message, headers = self.fail
            if self.echo_key:
                message = f"{message} (key {given})"
            return error(status, kind, message, headers)
        return None

    def _keep(self, request: Request, body: Any) -> None:
        self.requests.append(
            {
                "path": request.url.path,
                "query": request.url.query,
                "host": request.headers.get("host"),
                "headers": dict(request.headers),
                "body": body,
            }
        )

    def _build(self) -> FastAPI:
        app = FastAPI()

        @app.get("/v1/models/{model_id}")
        async def model(model_id: str, request: Request) -> Any:
            self._keep(request, None)
            refused = self._refusal(request)
            if refused is not None:
                return refused
            if model_id not in self.models:
                return error(404, "not_found_error", f"model: {model_id}")
            return {"type": "model", "id": model_id, "display_name": model_id, "created_at": "2026-09-01T00:00:00Z"}

        @app.post("/v1/messages")
        async def messages(request: Request) -> Any:
            body = await request.json()
            self._keep(request, body)
            refused = self._refusal(request)
            if refused is not None:
                return refused
            if body["model"] not in self.models:
                return error(404, "not_found_error", f"model: {body['model']}")
            if self.delay:
                await asyncio.sleep(self.delay)
            system, prompt = body["system"], body["messages"][0]["content"]
            model = self.reported_model or body["model"]
            if body.get("stream"):
                return StreamingResponse(self._stream(system, prompt, model), media_type="text/event-stream")
            if self.refuse:
                return self._message(model, [], "refusal", prompt, "")
            schema = ((body.get("output_config") or {}).get("format") or {}).get("schema")
            result = await self.llm.generate(system, prompt, schema=schema)
            text, stop = result.text, "end_turn"
            if schema is not None and self.truncate:
                text, stop = text[: len(text) // 2], "max_tokens"
            elif schema is not None and self.not_json:
                text = "JSON이 아닌 답입니다."
            return self._message(model, [THINKING, {"type": "text", "text": text}], stop, prompt, text)

        return app

    def _message(self, model: str, content: list, stop: str, prompt: str, text: str) -> dict[str, Any]:
        return {
            "id": "msg_fake01",
            "type": "message",
            "role": "assistant",
            "model": model,
            "content": content,
            "stop_reason": stop,
            "stop_sequence": None,
            "stop_details": {"type": "refusal", "category": "cyber", "explanation": None}
            if stop == "refusal"
            else None,
            "usage": {"input_tokens": len(prompt), "output_tokens": len(text) + 7},
        }

    async def _stream(self, system: str, prompt: str, model: str):
        def event(name: str, data: dict[str, Any]) -> str:
            return f"event: {name}\ndata: {json.dumps({'type': name, **data}, ensure_ascii=False)}\n\n"

        start = self._message(model, [], None, prompt, "")  # type: ignore[arg-type]
        yield event("message_start", {"message": start})
        yield event("ping", {})
        if self.refuse:
            yield event("message_delta", {"delta": {"stop_reason": "refusal", "stop_sequence": None}, "usage": {"output_tokens": 0}})
            yield event("message_stop", {})
            return
        yield event("content_block_start", {"index": 0, "content_block": {**THINKING, "signature": ""}})
        yield event("content_block_delta", {"index": 0, "delta": {"type": "signature_delta", "signature": "sig-fake"}})
        yield event("content_block_stop", {"index": 0})
        yield event("content_block_start", {"index": 1, "content_block": {"type": "text", "text": ""}})
        sent = 0
        async for piece in self.llm.stream(system, prompt):
            yield event("content_block_delta", {"index": 1, "delta": {"type": "text_delta", "text": piece}})
            sent += len(piece)
            if self.stream_error:
                yield event("error", {"error": {"type": "overloaded_error", "message": "Overloaded"}})
                return
        yield event("content_block_stop", {"index": 1})
        yield event("message_delta", {"delta": {"stop_reason": "end_turn", "stop_sequence": None}, "usage": {"output_tokens": sent}})
        yield event("message_stop", {})
