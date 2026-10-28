"""LLM through the Claude API (Anthropic), called directly with the official Python SDK.

For tests with made-up (seed) data on the external development laptop only, not for in-house
import: the in-house target is the open-weight model server (open_model_server.py). Data leaves
the company, so the admin screen asks for confirmation before a test and a reason to apply. Only
de-identified text reaches it (the AI gateway's guard runs first); prompts and answers are not
logged.

The API key is never an option. An option names the environment variable, read at each call from
the server's environment or `.env` (config.env_value), handed to the SDK and scrubbed from any
error text. The address is fixed to api.anthropic.com, so an ANTHROPIC_BASE_URL in the server's
environment (Claude Code sets one for its own processes) does not send the data elsewhere.

Requests follow the current models' rules: no sampling parameters (temperature, top_p), thinking
left to the model (adaptive; Claude Opus 5.5 cannot turn it off) and `output_config.effort` as the
control for latency and depth. Thinking counts toward max_tokens, so room for it is added to what
the app asks for. Streams (follow-ups) add a line asking for the visible answer right away.
Structured output is `output_config.format` with the schema made strict by the SDK's
`transform_schema` (limits the API does not take, such as minItems 3, move into the description;
callers validate as before). Claude Opus 5.5 and Sonnet 5.5 requests opt into the server-side
refusal fallback (`fallbacks: "default"`); the answer's `model` names the model that answered.

Failures are split by cause for the admin screen and the audit log (which keeps the class name):
the connection, authentication, the model, the rate limit, a timeout, the request, the API
itself, a refusal or the output.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Mapping
from typing import Any

import anthropic
import httpx2

from interview_assistant.config import env_value
from interview_assistant.providers.base import LLMProvider, LLMResult
from interview_assistant.providers.llm.open_model_server import OptionError, check_env_name

API_URL = "https://api.anthropic.com"
MODELS = ("claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5")
EFFORTS = ("low", "medium", "high")
# Anthropic's recommended substitute per refusal category. Claude Haiku 5.5 has no server-side
# fallback (a list of fallback models is refused), so its requests go without.
FALLBACK_BETA = "server-side-fallback-2026-07-01"
FALLBACK_MODELS = frozenset({"claude-opus-5-5", "claude-sonnet-5-5"})
# Thinking counts toward max_tokens: added to what the app asks for the answer.
THINKING_ROOM = 4096
# Follow-ups stream to the interviewer's screen: less thinking before the first visible token.
LATENCY_NOTE = "Latency-sensitive; begin your visible answer immediately."


# --- errors -----------------------------------------------------------------------------------


class ClaudeAPIError(RuntimeError):
    """A failed call to the Claude API. The message starts with the cause and never holds the
    key."""

    kind = "server"
    label = "서버 오류"

    def __init__(self, message: str) -> None:
        super().__init__(f"{self.label}: {message}")


class Unreachable(ClaudeAPIError):
    kind = "connection"
    label = "연결 실패"


class AuthFailed(ClaudeAPIError):
    kind = "auth"
    label = "인증 실패"


class ModelNotFound(ClaudeAPIError):
    kind = "model"
    label = "모델 없음"


class RateLimited(ClaudeAPIError):
    kind = "rate_limit"
    label = "요청 한도 초과"


class APITimeout(ClaudeAPIError):
    kind = "timeout"
    label = "시간 초과"


class BadRequest(ClaudeAPIError):
    kind = "request"
    label = "요청 오류"


class Refused(ClaudeAPIError):
    kind = "refusal"
    label = "응답 거부"


class BadOutput(ClaudeAPIError):
    kind = "output"
    label = "응답 형식 오류"


# --- options ----------------------------------------------------------------------------------


def check_options(options: Mapping[str, Any]) -> dict[str, Any]:
    """The options checked together (stored specs skip the admin screen's validation). Raises
    OptionError naming the field."""
    values = dict(options)
    try:
        values["api_key_env"] = check_env_name(str(values.get("api_key_env") or ""))
    except ValueError as exc:
        raise OptionError("api_key_env", str(exc)) from exc
    if not values["api_key_env"]:
        raise OptionError("api_key_env", "API 키가 든 환경변수의 이름을 적어 주세요 (예: ANTHROPIC_API_KEY).")
    if values.get("model") not in MODELS:
        raise OptionError("model", f"고를 수 있는 모델: {', '.join(MODELS)}")
    if values.get("effort") not in EFFORTS:
        raise OptionError("effort", f"effort는 {', '.join(EFFORTS)} 중 하나입니다.")
    return values


def _scrub(text: str, secret: str) -> str:
    return text.replace(secret, "■■■") if secret else text


def _detail(exc: anthropic.APIStatusError, secret: str) -> str:
    """The API's own error message and request id, short."""
    error = exc.body.get("error") if isinstance(exc.body, dict) else None
    message = str(error.get("message") or "") if isinstance(error, dict) else ""
    said = f" API 응답: {_scrub(' '.join(message.split()), secret)[:300]}" if message else ""
    return said + (f" (요청 ID {exc.request_id})" if exc.request_id else "")


# --- the provider -----------------------------------------------------------------------------


class AnthropicLLM(LLMProvider):
    # Tests swap in an in-process transport (httpx2.ASGITransport, MockTransport) and no retries.
    transport: httpx2.AsyncBaseTransport | None = None
    max_retries: int = 2

    def __init__(
        self,
        model: str = "claude-opus-5-5",
        effort: str = "low",
        max_tokens: int = 16000,
        timeout: float = 60,
        api_key_env: str = "ANTHROPIC_API_KEY",
        **_: Any,
    ) -> None:
        values = check_options({"model": model, "effort": effort, "api_key_env": api_key_env})
        self.model = model
        self.effort = effort
        self.api_key_env = values["api_key_env"]
        self.max_tokens = int(max_tokens)
        self.timeout = float(timeout)
        # One SDK client per event loop, key and transport: connections are reused between calls
        # (a new TLS handshake would cost the follow-up's first token), not across event loops.
        self._sdk: anthropic.AsyncAnthropic | None = None
        self._sdk_for: tuple[Any, ...] = ()

    # --- requests -------------------------------------------------------------------------------

    def _key(self) -> str:
        key = env_value(self.api_key_env)
        if not key:
            raise AuthFailed(f"API 키 환경변수 {self.api_key_env}이(가) 서버 환경과 .env에 없습니다.")
        return key

    def _client(self) -> tuple[anthropic.AsyncAnthropic, str]:
        key = self._key()
        wanted = (asyncio.get_running_loop(), key, self.transport, self.max_retries)
        if self._sdk is None or self._sdk_for != wanted:
            # The previous client is left to the garbage collector, not closed: a call on it may
            # still be running (scoring samples run side by side).
            timeout = httpx2.Timeout(self.timeout, connect=min(10.0, self.timeout))
            self._sdk = anthropic.AsyncAnthropic(
                api_key=key,  # given explicitly: no other credential source is consulted
                base_url=API_URL,
                timeout=timeout,
                max_retries=self.max_retries,
                http_client=anthropic.DefaultAsyncHttpxClient(transport=self.transport, timeout=timeout),
            )
            self._sdk_for = wanted
        return self._sdk, key

    def _params(self, system: str, prompt: str, max_tokens: int) -> dict[str, Any]:
        params: dict[str, Any] = {
            "model": self.model,
            "max_tokens": min(self.max_tokens, max_tokens + THINKING_ROOM),
            "system": system,
            "messages": [{"role": "user", "content": prompt}],
            "output_config": {"effort": self.effort},
        }
        if self.model in FALLBACK_MODELS:
            params |= {"betas": [FALLBACK_BETA], "fallbacks": "default"}
        return params

    def _failure(self, exc: BaseException, secret: str) -> ClaudeAPIError:
        if isinstance(exc, (anthropic.APITimeoutError, TimeoutError, httpx2.TimeoutException)):
            return APITimeout(
                f"{self.timeout:g}초 안에 응답이 끝나지 않았습니다. 타임아웃을 늘리거나 effort를 낮추세요."
            )
        if isinstance(exc, anthropic.APIConnectionError):
            return Unreachable(
                "api.anthropic.com에 연결하지 못했습니다. 인터넷 연결과 프록시·방화벽을 확인하세요."
            )
        if isinstance(exc, httpx2.HTTPError):  # mid-stream: the SDK wraps only the request itself
            return Unreachable(f"응답을 받는 중에 연결이 끊겼습니다 ({type(exc).__name__}).")
        if not isinstance(exc, anthropic.APIStatusError):
            return ClaudeAPIError(f"응답을 읽지 못했습니다 ({type(exc).__name__}).")
        status, error = exc.status_code, exc.type  # a stream's error event comes with HTTP 200
        said = _detail(exc, secret)
        if status == 401 or error == "authentication_error":
            return AuthFailed(f"API 키가 거부되었습니다 (HTTP 401). {self.api_key_env}의 값을 확인하세요.{said}")
        if status == 403 or error == "permission_error":
            return AuthFailed(f"이 키로는 허용되지 않는 요청입니다 (HTTP 403).{said}")
        if status == 402 or error == "billing_error":
            return AuthFailed(f"키의 조직에 결제 정보나 크레딧이 없습니다 (HTTP 402).{said}")
        if status == 404 or error == "not_found_error":
            return ModelNotFound(f"이 키로 '{self.model}' 모델을 쓸 수 없습니다 (HTTP 404).{said}")
        if status == 429 or error == "rate_limit_error":
            wait = exc.response.headers.get("retry-after")
            after = f" {wait}초 뒤에 다시 하세요." if wait else " 잠시 뒤에 다시 하세요."
            return RateLimited(f"요청 한도를 넘었습니다 (HTTP 429).{after}{said}")
        if status in (408, 504) or error == "timeout_error":
            return APITimeout(f"API가 시간 초과로 끊었습니다 (HTTP {status}).{said}")
        if status in (400, 413, 422) or error in ("invalid_request_error", "request_too_large"):
            return BadRequest(f"API가 요청을 받지 않았습니다 (HTTP {status}).{said}")
        if status == 529 or error == "overloaded_error":
            return ClaudeAPIError(f"API가 과부하 상태입니다. 잠시 뒤에 다시 하세요.{said}")
        return ClaudeAPIError(f"HTTP {status}.{said}")

    @staticmethod
    def _refused(message: Any) -> Refused:
        details = getattr(message, "stop_details", None)
        category = getattr(details, "category", None)
        return Refused(
            f"모델이 답하지 않았습니다 (분류: {category or '없음'}). 프롬프트나 모델을 바꿔 보세요."
        )

    # --- LLMProvider ----------------------------------------------------------------------------

    async def warm_up(self) -> None:
        """One GET /v1/models/{model}: the key is accepted and may use the model. Sends no
        prompt; the admin screen applies a setting only after this passes."""
        client, key = self._client()
        try:
            async with asyncio.timeout(self.timeout):
                await client.models.retrieve(self.model)
        except (anthropic.APIError, httpx2.HTTPError, TimeoutError) as exc:
            raise self._failure(exc, key) from exc

    async def generate(
        self,
        system: str,
        prompt: str,
        *,
        schema: dict[str, Any] | None = None,
        max_tokens: int = 16000,
    ) -> LLMResult:
        client, key = self._client()
        params = self._params(system, prompt, max_tokens)
        if schema is not None:
            params["output_config"]["format"] = {
                "type": "json_schema",
                "schema": anthropic.transform_schema(schema),
            }
        try:
            async with asyncio.timeout(self.timeout):
                message = await client.beta.messages.create(**params)
        except (anthropic.APIError, httpx2.HTTPError, TimeoutError) as exc:
            raise self._failure(exc, key) from exc
        if message.stop_reason == "refusal":
            raise self._refused(message)
        text = "".join(block.text for block in message.content if block.type == "text")
        structured = None
        if schema is not None:
            if message.stop_reason == "max_tokens":
                raise BadOutput(
                    f"출력이 최대 토큰({params['max_tokens']})에서 잘려 JSON이 끝나지 않았습니다. "
                    "최대 출력 토큰을 늘리세요."
                )
            try:
                structured = json.loads(text)
            except json.JSONDecodeError:
                structured = None
            if not isinstance(structured, dict):
                raise BadOutput("JSON 객체로 답하지 않았습니다.")
        return LLMResult(
            text=text,
            structured=structured,
            model=str(message.model or self.model),
            input_tokens=int(message.usage.input_tokens or 0),
            output_tokens=int(message.usage.output_tokens or 0),
        )

    async def stream(
        self,
        system: str,
        prompt: str,
        *,
        max_tokens: int = 16000,
    ) -> AsyncIterator[str]:
        client, key = self._client()
        params = self._params(f"{system}\n\n{LATENCY_NOTE}", prompt, max_tokens)
        try:
            async with client.beta.messages.stream(**params) as stream:
                async for text in stream.text_stream:  # answer text only, no thinking
                    if text:
                        yield text
                message = await stream.get_final_message()
        except (anthropic.APIError, httpx2.HTTPError, TimeoutError) as exc:
            raise self._failure(exc, key) from exc
        if message.stop_reason == "refusal":
            raise self._refused(message)
