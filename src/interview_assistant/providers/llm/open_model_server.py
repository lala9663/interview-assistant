"""LLM on an open-weight model server inside the company (vLLM, Ollama, SGLang ...).

These servers speak the OpenAI chat-completions format (`POST {base_url}/chat/completions`,
`GET {base_url}/models`), so that is the format used here, over httpx2. Nothing goes to OpenAI's
own services: addresses on openai.com and Azure OpenAI are refused, and the address is the in-house
server the admin enters. Only de-identified text reaches a provider (the AI gateway's guard runs
first); prompts and answers are not logged.

Secrets are never options. The API key, when the server wants one, is read from the environment
variable whose *name* is an option (the server's environment, else .env); a header value takes one
as `${NAME}`. Values are read at each call, sent only as headers and scrubbed from any error text.

Structured output: the JSON Schema goes into the system prompt (the model sees the field
descriptions) and, by default, also as `response_format` json_schema, which vLLM, SGLang and Ollama
use to constrain decoding. The answer is parsed as one JSON object; callers validate it with their
own models.

Reasoning models (Qwen3, DeepSeek-R1, gpt-oss): reasoning a server returns in its own field
(`reasoning_content`, `reasoning`) is ignored, and a leading `<think>...</think>` block in the text
is dropped, so a follow-up stream shows only the answer. The first token is fast only when
reasoning is off on the server side (`extra_body`, docs/ai-models.md).

Failures are split by cause for the admin screen and the audit log (which keeps the class name):
the address, authentication, the model name, a timeout, the server itself, or its output.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator, Iterable, Mapping
from typing import Any
from urllib.parse import urlsplit

import httpx2

from interview_assistant.config import env_value
from interview_assistant.providers.base import LLMProvider, LLMResult

# OpenAI's services, also through Azure: company policy keeps data away from them.
OPENAI_DOMAINS = ("openai.com", "openai.azure.com")
STRUCTURED_MODES = ("json_schema", "json_object", "prompt")

_ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_ENV_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_HEADER_NAME = re.compile(r"[A-Za-z0-9!#$%&'*+.^_`|~-]+")
# Headers carrying credentials take their value from the environment: "${NAME}" or "Bearer ${NAME}".
_SECRET_HEADER = re.compile(r"auth|key|token|secret|cookie|password|credential", re.I)
_SECRET_PREFIX = re.compile(r"(?:[A-Za-z]+ )?")
# Set by this client.
_RESERVED_HEADERS = {"content-type", "content-length", "host", "accept", "transfer-encoding"}
# What `extra_body` may not override: the request itself, and tool calling (not in scope).
_RESERVED_FIELDS = {
    "model",
    "messages",
    "stream",
    "stream_options",
    "max_tokens",
    "max_completion_tokens",
    "temperature",
    "response_format",
    "n",
    "tools",
    "tool_choice",
    "functions",
    "function_call",
}
# vLLM: "The model `x` does not exist."; Ollama: 'model "x" not found, try pulling it first'.
_MODEL_MISSING = re.compile(
    r"model.{0,80}(not found|does not exist|not exist|unknown|invalid|not available)"
    r"|(unknown|invalid|no such) model",
    re.I | re.S,
)
_THINK_OPEN, _THINK_CLOSE = "<think>", "</think>"


# --- errors -----------------------------------------------------------------------------------


class ModelServerError(RuntimeError):
    """A failed call to the model server. The message starts with the cause and never holds a
    secret value."""

    kind = "server"
    label = "서버 오류"

    def __init__(self, message: str) -> None:
        super().__init__(f"{self.label}: {message}")


class ServerUnreachable(ModelServerError):
    kind = "address"
    label = "주소 오류"


class AuthFailed(ModelServerError):
    kind = "auth"
    label = "인증 실패"


class ModelNotFound(ModelServerError):
    kind = "model"
    label = "모델 없음"


class ServerTimeout(ModelServerError):
    kind = "timeout"
    label = "시간 초과"


class BadOutput(ModelServerError):
    kind = "output"
    label = "응답 형식 오류"


# --- options ----------------------------------------------------------------------------------


class OptionError(ValueError):
    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field


def check_base_url(url: str) -> str:
    """The server address without a trailing slash. Refuses what is not an http(s) URL,
    credentials in the URL, and OpenAI's services."""
    url = url.strip().rstrip("/")
    if not url:
        raise ValueError("서버 주소를 적어 주세요 (예: http://10.0.0.5:8000/v1).")
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("http:// 또는 https://로 시작하는 주소를 적어 주세요 (예: http://10.0.0.5:8000/v1).")
    if parts.username or parts.password:
        raise ValueError("주소에 사용자 이름·비밀번호를 넣지 않습니다. 키는 API 키 환경변수로 줍니다.")
    if parts.query or parts.fragment:
        raise ValueError("주소에 ?나 #를 붙이지 않습니다.")
    try:
        parts.port  # noqa: B018 - raises for a port out of range
    except ValueError as exc:
        raise ValueError("포트 번호가 올바르지 않습니다.") from exc
    host = parts.hostname.lower().rstrip(".")
    if any(host == d or host.endswith("." + d) for d in OPENAI_DOMAINS):
        raise ValueError(
            "OpenAI 서비스 주소는 쓸 수 없습니다. 사내에 설치한 모델 서버의 주소를 적어 주세요."
        )
    return url


def check_env_name(name: str) -> str:
    name = name.strip()
    if name and not _ENV_NAME.fullmatch(name):
        raise ValueError(
            "환경변수의 이름만 적습니다 (영문·숫자·밑줄, 예: IA_LLM_API_KEY). 키 값은 적지 않습니다."
        )
    return name


def parse_headers(text: str) -> list[tuple[str, str]]:
    """'Name: value' lines (blank lines and # comments skipped)."""
    headers: list[tuple[str, str]] = []
    for number, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, sep, value = line.partition(":")
        name, value = name.strip(), value.strip()
        if not sep or not _HEADER_NAME.fullmatch(name) or not value:
            raise ValueError(f"{number}번째 줄: '이름: 값' 형식으로 적어 주세요.")
        if name.lower() in _RESERVED_HEADERS:
            raise ValueError(f"{name} 헤더는 앱이 정합니다.")
        if _SECRET_HEADER.search(name) and not (
            _ENV_REF.search(value) and _SECRET_PREFIX.fullmatch(_ENV_REF.sub("", value))
        ):
            raise ValueError(
                f"{name} 헤더의 값은 ${{환경변수}} 형태로만 적습니다 (예: Bearer ${{IA_GATEWAY_TOKEN}}). "
                "키·토큰 값은 화면에 적지 않습니다."
            )
        headers.append((name, value))
    return headers


def header_env_names(text: str) -> list[str]:
    """Environment variables the header lines refer to (`${NAME}`)."""
    try:
        headers = parse_headers(text)
    except ValueError:
        return []
    return [name for _, value in headers for name in _ENV_REF.findall(value)]


def parse_extra_body(text: str) -> dict[str, Any]:
    text = text.strip()
    if not text:
        return {}
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON 객체로 적어 주세요 ({exc.lineno}번째 줄: {exc.msg}).") from exc
    if not isinstance(value, dict):
        raise ValueError("JSON 객체({ ... })로 적어 주세요.")
    reserved = sorted(set(value) & _RESERVED_FIELDS)
    if reserved:
        raise ValueError(f"앱이 정하는 필드는 넣을 수 없습니다: {', '.join(reserved)}")
    return value


def check_options(options: Mapping[str, Any]) -> dict[str, Any]:
    """The connection options checked together (the admin screen's validation and the
    constructor, since stored specs skip the screen). Raises OptionError naming the field."""
    values = dict(options)
    checks = (
        ("base_url", check_base_url),
        ("api_key_env", check_env_name),
        ("headers", parse_headers),
        ("extra_body", parse_extra_body),
    )
    for key, check in checks:
        try:
            checked = check(str(values.get(key) or ""))
        except ValueError as exc:
            raise OptionError(key, str(exc)) from exc
        if isinstance(checked, str):
            values[key] = checked
    if not str(values.get("model") or "").strip():
        raise OptionError("model", "서버에 올린 모델 이름을 적어 주세요.")
    if values.get("api_key_env") and any(
        name.lower() == "authorization" for name, _ in parse_headers(str(values.get("headers") or ""))
    ):
        raise OptionError(
            "headers", "API 키 환경변수를 쓰면 Authorization 헤더는 앱이 만듭니다. 둘 중 하나만 적어 주세요."
        )
    if values.get("structured_output", "json_schema") not in STRUCTURED_MODES:
        raise OptionError("structured_output", "구조화 출력 방식이 올바르지 않습니다.")
    return values


# --- text -------------------------------------------------------------------------------------


def strip_reasoning(text: str) -> str:
    """The answer without its reasoning: a leading <think>...</think> block, or everything up to
    a lone </think> (chat templates that open the block in the prompt)."""
    if _THINK_CLOSE in text:
        head, _, tail = text.partition(_THINK_CLOSE)
        if _THINK_OPEN not in head or head.lstrip().startswith(_THINK_OPEN):
            return tail.lstrip()
    return text


def parse_json_object(text: str) -> dict[str, Any]:
    """One JSON object from a model's answer, tolerating a code fence or words around it."""
    text = strip_reasoning(text).strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, re.S)
    if fenced:
        text = fenced.group(1)
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        try:
            value = json.loads(text[start : end + 1]) if 0 <= start < end else None
        except json.JSONDecodeError:
            value = None
    if not isinstance(value, dict):
        raise BadOutput("JSON 객체로 답하지 않았습니다. 구조화 출력 방식을 바꾸거나 더 큰 모델을 쓰세요.")
    return value


def schema_instruction(schema: Mapping[str, Any]) -> str:
    return (
        "답은 아래 JSON 스키마를 따르는 JSON 객체 하나뿐입니다. 설명이나 코드 블록 없이 JSON만 "
        "쓰세요.\n" + json.dumps(schema, ensure_ascii=False)
    )


class _LeadingThink:
    """Drops a leading <think>...</think> block from streamed text, piece by piece."""

    def __init__(self) -> None:
        self.state = "start"  # start -> text, or start -> thinking -> text
        self.buffer = ""

    def feed(self, piece: str) -> str:
        if self.state == "text":
            return piece
        self.buffer += piece
        if self.state == "start":
            head = self.buffer.lstrip()
            if len(head) < len(_THINK_OPEN) and _THINK_OPEN.startswith(head):
                return ""  # cannot tell yet
            if not head.startswith(_THINK_OPEN):
                self.state = "text"
                out, self.buffer = self.buffer, ""
                return out
            self.state = "thinking"
        end = self.buffer.find(_THINK_CLOSE)
        if end < 0:
            self.buffer = self.buffer[-len(_THINK_CLOSE) :]
            return ""
        out = self.buffer[end + len(_THINK_CLOSE) :].lstrip()
        self.state, self.buffer = "text", ""
        return out

    def flush(self) -> str:
        out = self.buffer if self.state == "start" else ""
        self.buffer = ""
        return out


def _detail(response: httpx2.Response) -> str:
    """The server's own error message, short."""
    try:
        body = response.json()
    except ValueError:
        text = re.sub(r"<[^>]+>", " ", response.text)
    else:
        error = body.get("error") if isinstance(body, dict) else None
        if isinstance(error, dict):
            text = str(error.get("message") or "")
        elif isinstance(error, str):
            text = error
        elif isinstance(body, dict):
            text = str(body.get("message") or body.get("detail") or "")
        else:
            text = ""
    return re.sub(r"\s+", " ", text).strip()[:300]


def _scrub(text: str, secrets: Iterable[str]) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, "■■■")
    return text


def _serves(models: list[str], model: str) -> bool:
    return model in models or f"{model}:latest" in models  # Ollama names carry a tag


# --- the provider -----------------------------------------------------------------------------


class OpenModelServerLLM(LLMProvider):
    # Tests swap in an in-process transport (httpx2.ASGITransport, MockTransport).
    transport: httpx2.AsyncBaseTransport | None = None

    def __init__(
        self,
        base_url: str = "",
        model: str = "",
        api_key_env: str = "",
        timeout: float = 120,
        max_tokens: int = 4096,
        temperature: float = 0.3,
        structured_output: str = "json_schema",
        headers: str = "",
        extra_body: str = "",
        **_: Any,
    ) -> None:
        values = check_options(
            {
                "base_url": base_url,
                "model": model,
                "api_key_env": api_key_env,
                "headers": headers,
                "extra_body": extra_body,
                "structured_output": structured_output,
            }
        )
        self.base_url = values["base_url"]
        self.model = model.strip()
        self.api_key_env = values["api_key_env"]
        self.headers = parse_headers(headers)
        self.extra_body = parse_extra_body(extra_body)
        self.structured_output = structured_output
        self.timeout = float(timeout)
        self.max_tokens = int(max_tokens)
        self.temperature = float(temperature)
        self.served_models: list[str] | None = None  # the server's list at the last warm-up

    # --- requests -------------------------------------------------------------------------------

    def _url(self, path: str) -> str:
        return f"{self.base_url}/{path}"

    def _client(self) -> httpx2.AsyncClient:
        # One client per call: instances outlive event loops (tests) and have no close hook.
        return httpx2.AsyncClient(
            timeout=httpx2.Timeout(self.timeout, connect=min(10.0, self.timeout)),
            transport=self.transport,
        )

    def _credentials(self) -> tuple[dict[str, str], list[str]]:
        """Request headers with the credentials read from the environment now, and the values
        read (scrubbed from any text shown)."""
        headers: dict[str, str] = {}
        secrets: list[str] = []

        def env(name: str, what: str) -> str:
            value = env_value(name)
            if not value:
                raise AuthFailed(f"{what}의 환경변수 {name}이(가) 서버 환경과 .env에 없습니다.")
            secrets.append(value)
            return value

        if self.api_key_env:
            headers["Authorization"] = f"Bearer {env(self.api_key_env, 'API 키')}"
        for name, value in self.headers:
            headers[name] = _ENV_REF.sub(lambda m, n=name: env(m.group(1), f"{n} 헤더"), value)
        return headers, secrets

    def _body(
        self,
        system: str,
        prompt: str,
        max_tokens: int,
        *,
        schema: dict[str, Any] | None = None,
        stream: bool = False,
    ) -> dict[str, Any]:
        if schema is not None:
            system = f"{system}\n\n{schema_instruction(schema)}"
        body: dict[str, Any] = {
            **self.extra_body,
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": min(max_tokens, self.max_tokens),
            "temperature": self.temperature,
            "stream": stream,
        }
        if schema is not None and self.structured_output == "json_schema":
            name = re.sub(r"[^A-Za-z0-9_-]", "_", str(schema.get("title") or "answer"))[:64]
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": name, "schema": schema},
            }
        elif schema is not None and self.structured_output == "json_object":
            body["response_format"] = {"type": "json_object"}
        return body

    def _failure(self, exc: Exception) -> ModelServerError:
        if isinstance(exc, httpx2.ConnectTimeout):
            return ServerUnreachable(
                f"{self.base_url}에 연결되지 않습니다 (연결 시간 초과). 주소·포트·방화벽을 확인하세요."
            )
        if isinstance(exc, (httpx2.TimeoutException, TimeoutError)):
            return ServerTimeout(
                f"{self.timeout:g}초 안에 응답이 끝나지 않았습니다. 타임아웃을 늘리거나 최대 출력 토큰을 줄이세요."
            )
        if isinstance(
            exc, (httpx2.ConnectError, httpx2.UnsupportedProtocol, httpx2.InvalidURL, httpx2.ProxyError)
        ):
            return ServerUnreachable(
                f"{self.base_url}에 연결하지 못했습니다. 주소·포트·방화벽을 확인하세요."
            )
        return ModelServerError(f"연결이 중간에 끊겼습니다 ({type(exc).__name__}).")

    def _check_status(self, response: httpx2.Response, secrets: list[str]) -> None:
        status = response.status_code
        if status < 300:
            return
        detail = _scrub(_detail(response), secrets)
        said = f" 서버 응답: {detail}" if detail else ""
        if status in (401, 403):
            raise AuthFailed(
                f"서버가 요청을 거부했습니다 (HTTP {status}). API 키 환경변수와 게이트웨이 헤더를 확인하세요.{said}"
            )
        if status in (400, 404, 422) and _MODEL_MISSING.search(detail):
            raise ModelNotFound(f"서버에 '{self.model}' 모델이 없습니다.{said}")
        if status < 400:
            raise ServerUnreachable(
                f"서버가 다른 주소로 넘깁니다 (HTTP {status}). 넘겨받는 주소를 그대로 적어 주세요."
            )
        if status in (404, 405):
            raise ServerUnreachable(
                f"{response.request.url} 경로가 없습니다 (HTTP {status}). 주소가 /v1까지 맞는지 확인하세요."
            )
        if status in (408, 504):
            raise ServerTimeout(f"서버나 게이트웨이가 시간 초과로 끊었습니다 (HTTP {status}).")
        raise ModelServerError(f"HTTP {status}.{said}")

    # --- LLMProvider ----------------------------------------------------------------------------

    async def warm_up(self) -> None:
        """One GET /models: the server answers, takes the credentials and serves the model. The
        admin screen applies a setting only after this passes."""
        models = await self.list_models()
        self.served_models = models
        if models is not None and not _serves(models, self.model):
            listed = ", ".join(models[:10]) or "없음"
            raise ModelNotFound(f"서버에 '{self.model}' 모델이 없습니다. 서버가 가진 모델: {listed}.")

    async def list_models(self) -> list[str] | None:
        """Model ids the server serves, or None when it does not list them (some gateways)."""
        headers, secrets = self._credentials()
        try:
            async with asyncio.timeout(self.timeout), self._client() as client:
                response = await client.get(self._url("models"), headers=headers)
        except (httpx2.HTTPError, httpx2.InvalidURL, TimeoutError) as exc:
            raise self._failure(exc) from exc
        if response.status_code in (404, 405):
            return None
        self._check_status(response, secrets)
        try:
            return [str(m["id"]) for m in response.json()["data"]]
        except (ValueError, KeyError, TypeError) as exc:
            raise ServerUnreachable(
                "모델 목록(/models)이 OpenAI 형식이 아닙니다. 주소가 모델 서버의 /v1을 가리키는지 확인하세요."
            ) from exc

    async def generate(
        self,
        system: str,
        prompt: str,
        *,
        schema: dict[str, Any] | None = None,
        max_tokens: int = 16000,
    ) -> LLMResult:
        body = self._body(system, prompt, max_tokens, schema=schema)
        headers, secrets = self._credentials()
        try:
            async with asyncio.timeout(self.timeout), self._client() as client:
                response = await client.post(self._url("chat/completions"), json=body, headers=headers)
        except (httpx2.HTTPError, httpx2.InvalidURL, TimeoutError) as exc:
            raise self._failure(exc) from exc
        self._check_status(response, secrets)
        try:
            data = response.json()
            choice = data["choices"][0]
            text = choice["message"].get("content") or ""
        except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
            raise ServerUnreachable(
                "chat/completions 응답이 OpenAI 형식이 아닙니다. 주소가 모델 서버의 /v1을 가리키는지 확인하세요."
            ) from exc
        text = strip_reasoning(text)
        structured = None
        if schema is not None:
            try:
                structured = parse_json_object(text)
            except BadOutput:
                if choice.get("finish_reason") == "length":
                    raise BadOutput(
                        f"출력이 최대 토큰({body['max_tokens']})에서 잘려 JSON이 끝나지 않았습니다."
                    ) from None
                raise
        usage = data.get("usage") or {}
        return LLMResult(
            text=text,
            structured=structured,
            model=str(data.get("model") or self.model),
            input_tokens=int(usage.get("prompt_tokens") or 0),
            output_tokens=int(usage.get("completion_tokens") or 0),
        )

    async def stream(
        self,
        system: str,
        prompt: str,
        *,
        max_tokens: int = 16000,
    ) -> AsyncIterator[str]:
        body = self._body(system, prompt, max_tokens, stream=True)
        headers, secrets = self._credentials()
        think = _LeadingThink()
        try:
            async with (
                self._client() as client,
                client.stream("POST", self._url("chat/completions"), json=body, headers=headers) as response,
            ):
                if response.status_code >= 300:
                    await response.aread()
                    self._check_status(response, secrets)
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        break
                    piece = think.feed(_delta(payload, secrets))
                    if piece:
                        yield piece
        except (httpx2.HTTPError, httpx2.InvalidURL) as exc:
            raise self._failure(exc) from exc
        tail = think.flush()
        if tail:
            yield tail


def _delta(payload: str, secrets: list[str]) -> str:
    """The answer text of one streamed chunk (reasoning fields are left out)."""
    try:
        chunk = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise BadOutput("스트리밍 응답을 읽을 수 없습니다.") from exc
    if not isinstance(chunk, dict):
        raise BadOutput("스트리밍 응답을 읽을 수 없습니다.")
    if chunk.get("error") or chunk.get("object") == "error":
        error = chunk.get("error")
        message = error.get("message") if isinstance(error, dict) else error or chunk.get("message")
        raise ModelServerError(f"스트리밍 중 서버가 오류를 보냈습니다: {_scrub(str(message), secrets)[:300]}")
    pieces = []
    for choice in chunk.get("choices") or []:
        content = (choice.get("delta") or {}).get("content")
        if isinstance(content, str):
            pieces.append(content)
    return "".join(pieces)
