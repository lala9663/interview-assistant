"""An in-process stand-in for an open-weight model server's OpenAI-format API (vLLM, Ollama), so
the open_model_server provider is tested without a network: GET /v1/models and POST
/v1/chat/completions, with and without streaming (SSE). Answers come from FakeLLM's rules, so the
app's own prompts get schema-valid JSON. Every request is kept for the tests to inspect; switches
make it fail the ways real servers do (vLLM's and Ollama's own error bodies)."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx2
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from interview_assistant.providers.fake import FakeLLM


class FakeModelServer:
    def __init__(
        self,
        models: tuple[str, ...] = ("qwen3-8b",),
        *,
        api_key: str | None = None,
        reported_model: str | None = None,
    ) -> None:
        self.models = list(models)
        self.api_key = api_key
        self.reported_model = reported_model  # the name the server answers with (vLLM: the HF path)
        self.requests: list[dict[str, Any]] = []
        self.delay = 0.0  # seconds before answering
        self.think = False  # put a <think>...</think> block before the answer
        self.reasoning_field = False  # stream reasoning in `reasoning_content` first (vLLM parser)
        self.fence = False  # wrap JSON answers in a ```json fence
        self.list_models = True  # GET /v1/models exists
        self.llm = FakeLLM(model="fake-on-server")
        self.app = self._build()

    def transport(self) -> httpx2.ASGITransport:
        return httpx2.ASGITransport(app=self.app)

    def bodies(self, path: str = "/v1/chat/completions") -> list[dict[str, Any]]:
        return [r["body"] for r in self.requests if r["path"] == path]

    def _refusal(self, request: Request) -> JSONResponse | None:
        if self.api_key is None:
            return None
        given = request.headers.get("authorization", "")
        if given != f"Bearer {self.api_key}":
            # Some gateways echo what they got: the provider must not pass it on.
            return JSONResponse(
                {"error": {"message": f"invalid api key: {given}", "type": "auth_error"}},
                status_code=401,
            )
        return None

    def _build(self) -> FastAPI:
        app = FastAPI()

        @app.get("/v1/models")
        async def models(request: Request) -> Any:
            self.requests.append({"path": request.url.path, "headers": dict(request.headers), "body": None})
            if not self.list_models:
                return JSONResponse({"detail": "Not Found"}, status_code=404)
            refused = self._refusal(request)
            if refused is not None:
                return refused
            return {"object": "list", "data": [{"id": m, "object": "model"} for m in self.models]}

        @app.post("/v1/chat/completions")
        async def chat(request: Request) -> Any:
            body = await request.json()
            self.requests.append({"path": request.url.path, "headers": dict(request.headers), "body": body})
            refused = self._refusal(request)
            if refused is not None:
                return refused
            if body["model"] not in self.models:
                return JSONResponse(
                    {
                        "object": "error",
                        "message": f"The model `{body['model']}` does not exist.",
                        "type": "NotFoundError",
                        "code": 404,
                    },
                    status_code=404,
                )
            if self.delay:
                await asyncio.sleep(self.delay)
            system = body["messages"][0]["content"]
            prompt = body["messages"][1]["content"]
            model = self.reported_model or body["model"]
            if body.get("stream"):
                return StreamingResponse(self._stream(system, prompt, model), media_type="text/event-stream")
            schema = _schema(body, system)
            result = await self.llm.generate(system, prompt, schema=schema)
            text = result.text
            if schema is not None and self.fence:
                text = f"```json\n{text}\n```"
            if self.think:
                text = f"<think>\n사용자가 JSON을 원한다. {{\"echo\": 1}}\n</think>\n\n{text}"
            return {
                "id": "chatcmpl-1",
                "object": "chat.completion",
                "model": model,
                "choices": [
                    {"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}
                ],
                "usage": {"prompt_tokens": len(prompt), "completion_tokens": len(text), "total_tokens": 0},
            }

        return app

    async def _stream(self, system: str, prompt: str, model: str):
        def chunk(delta: dict[str, Any]) -> str:
            data = {"object": "chat.completion.chunk", "model": model, "choices": [{"index": 0, "delta": delta}]}
            return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

        yield chunk({"role": "assistant", "content": ""})
        if self.reasoning_field:
            yield chunk({"reasoning_content": "먼저 문장을 찾는다."})
        if self.think:
            for piece in ("<th", "ink>\n지시를 읽는다.", " 짧게 답한다.\n</thi", "nk>\n\n"):
                yield chunk({"content": piece})
        async for piece in self.llm.stream(system, prompt):
            yield chunk({"content": piece})
        yield "data: [DONE]\n\n"


def _schema(body: dict[str, Any], system: str) -> dict[str, Any] | None:
    """The JSON Schema the client asked for: from response_format, else from the system prompt
    (the provider puts it on the last line)."""
    response_format = body.get("response_format") or {}
    if response_format.get("type") == "json_schema":
        return response_format["json_schema"]["schema"]
    last = system.rstrip().rsplit("\n", 1)[-1]
    if last.startswith("{"):
        return json.loads(last)
    return None
