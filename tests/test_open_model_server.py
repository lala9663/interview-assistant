"""The LLM provider for in-house open-weight model servers (vLLM, Ollama): generation, streaming,
structured output, failures by cause, timeouts, the AI gateway's guard and audit log, the admin
screen's options and connection test, and the refusal of OpenAI's services. No network: the server
is an in-process ASGI app (tests/fake_model_server.py) or an httpx2 MockTransport."""

from __future__ import annotations

import json

import httpx2
import pytest
from sqlalchemy import select

from interview_assistant.ai.gateway import AiCall, AiGateway
from interview_assistant.ai.guard import IdentifierInPrompt
from interview_assistant.ai.prompts import (
    CONNECTION_TEST_SCHEMA,
    CONNECTION_TEST_SYSTEM,
    connection_test_prompt,
)
from interview_assistant.config import ProviderSpec
from interview_assistant.deid.types import KnownIdentity
from interview_assistant.models import AuditLog
from interview_assistant.providers import registry
from interview_assistant.providers.llm.open_model_server import (
    AuthFailed,
    BadOutput,
    ModelNotFound,
    OpenModelServerLLM,
    ServerTimeout,
    ServerUnreachable,
    check_base_url,
    parse_headers,
    parse_json_object,
)
from tests.api_util import P3, round_id
from tests.fake_model_server import FakeModelServer

BASE = "http://vllm.test:8000/v1"
KEY = "sk-inhouse-7f3a9c2e5b1d"
ECHO = {"echo": "모델 연결 확인 문장입니다", "sum": 42}


def _llm(server: FakeModelServer | None = None, transport=None, **options) -> OpenModelServerLLM:
    llm = OpenModelServerLLM(**{"base_url": BASE, "model": "qwen3-8b", **options})
    llm.transport = transport if transport is not None else server.transport()
    return llm


async def _probe(llm: OpenModelServerLLM):
    return await llm.generate(
        CONNECTION_TEST_SYSTEM, connection_test_prompt(), schema=CONNECTION_TEST_SCHEMA, max_tokens=200
    )


def _raising(exc: Exception) -> httpx2.MockTransport:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise exc

    return httpx2.MockTransport(handler)


# --- generation and streaming -----------------------------------------------------------------


async def test_generate_sends_the_openai_format_and_reads_the_servers_json():
    server = FakeModelServer(reported_model="Qwen/Qwen3-8B")
    result = await _probe(_llm(server, max_tokens=1024, temperature=0.2))
    assert result.structured == ECHO
    assert result.model == "Qwen/Qwen3-8B"  # what the server says it ran
    assert result.input_tokens > 0 and result.output_tokens > 0

    [body] = server.bodies()
    assert body["model"] == "qwen3-8b" and body["stream"] is False
    assert body["max_tokens"] == 200 and body["temperature"] == 0.2  # the call's 200 < the cap 1024
    system, user = body["messages"]
    assert system["role"] == "system" and system["content"].startswith(CONNECTION_TEST_SYSTEM)
    assert '"title": "ConnectionTest"' in system["content"]  # the schema is in the prompt too
    assert user == {"role": "user", "content": connection_test_prompt()}
    assert body["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "ConnectionTest", "schema": CONNECTION_TEST_SCHEMA},
    }
    # The cap applies when the app asks for more.
    await _llm(server, max_tokens=512).generate("s", "p", max_tokens=4000)
    assert server.bodies()[-1]["max_tokens"] == 512


@pytest.mark.parametrize(
    ("mode", "expected"),
    [("json_object", {"type": "json_object"}), ("prompt", None)],
)
async def test_other_structured_output_modes_and_fenced_or_reasoned_json(mode, expected):
    server = FakeModelServer()
    server.fence = server.think = True
    result = await _probe(_llm(server, structured_output=mode))
    assert result.structured == ECHO
    assert server.bodies()[-1].get("response_format") == expected
    assert not result.text.startswith("<think>")


async def test_extra_body_goes_into_the_request():
    server = FakeModelServer()
    llm = _llm(server, extra_body='{"chat_template_kwargs": {"enable_thinking": false}, "top_p": 0.9}')
    await llm.generate("s", "p")
    body = server.bodies()[-1]
    assert body["chat_template_kwargs"] == {"enable_thinking": False} and body["top_p"] == 0.9


async def test_stream_yields_the_answer_without_reasoning():
    server = FakeModelServer()
    server.think = server.reasoning_field = True
    llm = _llm(server)
    pieces = [p async for p in llm.stream("s", "<echo>\n모델 연결 확인 문장입니다\n</echo>")]
    text = "".join(pieces)
    assert "모델 연결 확인 문장입니다" in text
    assert "think" not in text and "지시를 읽는다" not in text and "먼저 문장을" not in text
    body = server.bodies()[-1]
    assert body["stream"] is True and "response_format" not in body


def test_json_is_found_in_what_models_wrap_around_it():
    assert parse_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json_object('<think>\n{"no": 1}\n</think>\n\n{"a": 1}') == {"a": 1}
    assert parse_json_object('결과입니다: {"a": {"b": 2}} 끝.') == {"a": {"b": 2}}
    with pytest.raises(BadOutput):
        parse_json_object("JSON이 아닌 답")
    with pytest.raises(BadOutput):
        parse_json_object("[1, 2]")


async def test_a_truncated_json_answer_says_so():
    def handler(request: httpx2.Request) -> httpx2.Response:
        message = {"role": "assistant", "content": '{"echo": "모델 연결'}
        return httpx2.Response(
            200, json={"model": "m", "choices": [{"message": message, "finish_reason": "length"}]}
        )

    with pytest.raises(BadOutput, match="최대 토큰"):
        await _probe(_llm(transport=httpx2.MockTransport(handler)))


# --- failures by cause --------------------------------------------------------------------------


async def test_address_failures():
    with pytest.raises(ServerUnreachable, match="연결하지 못했습니다"):
        await _probe(_llm(transport=_raising(httpx2.ConnectError("refused"))))
    with pytest.raises(ServerUnreachable, match="연결 시간 초과"):
        await _probe(_llm(transport=_raising(httpx2.ConnectTimeout("slow"))))
    # The server is there, the path is not (/v1 left out).
    server = FakeModelServer()
    with pytest.raises(ServerUnreachable, match="/v1까지"):
        await _probe(_llm(server, base_url="http://vllm.test:8000"))
    # Something answers, but not a model server.
    page = httpx2.MockTransport(lambda r: httpx2.Response(200, html="<html>사내 포털</html>"))
    with pytest.raises(ServerUnreachable, match="OpenAI 형식"):
        await _probe(_llm(transport=page))


async def test_auth_failures_never_show_the_key(monkeypatch):
    server = FakeModelServer(api_key=KEY)
    monkeypatch.setenv("IA_TEST_LLM_KEY", "wrong-" + KEY)
    with pytest.raises(AuthFailed) as exc:
        await _probe(_llm(server, api_key_env="IA_TEST_LLM_KEY"))
    assert "HTTP 401" in str(exc.value) and KEY not in str(exc.value)
    assert "■■■" in str(exc.value)  # the server echoed the key; it was scrubbed

    monkeypatch.delenv("IA_TEST_LLM_KEY")
    with pytest.raises(AuthFailed, match="IA_TEST_LLM_KEY"):
        await _probe(_llm(server, api_key_env="IA_TEST_LLM_KEY"))

    monkeypatch.setenv("IA_TEST_LLM_KEY", KEY)
    assert (await _probe(_llm(server, api_key_env="IA_TEST_LLM_KEY"))).structured == ECHO
    assert server.requests[-1]["headers"]["authorization"] == f"Bearer {KEY}"


async def test_gateway_headers_take_secrets_from_the_environment(monkeypatch):
    server = FakeModelServer()
    monkeypatch.setenv("IA_TEST_GATEWAY_KEY", "gw-secret-123")
    llm = _llm(server, headers="X-Team: hr-ai\n# comment\nX-Gateway-Key: ${IA_TEST_GATEWAY_KEY}")
    await llm.generate("s", "p")
    headers = server.requests[-1]["headers"]
    assert headers["x-team"] == "hr-ai" and headers["x-gateway-key"] == "gw-secret-123"
    assert "gw-secret-123" not in json.dumps(llm.headers)  # only the reference is kept

    with pytest.raises(ValueError, match="환경변수"):
        parse_headers("X-Api-Key: plain-secret-value")
    with pytest.raises(ValueError, match="환경변수"):
        parse_headers("Authorization: Bearer abc.def")
    assert parse_headers("Authorization: Bearer ${TOKEN}") == [("Authorization", "Bearer ${TOKEN}")]
    with pytest.raises(ValueError, match="앱이 정합니다"):
        parse_headers("Content-Type: text/plain")
    with pytest.raises(ValueError, match="형식"):
        parse_headers("no colon here")


async def test_a_missing_model_is_named_with_what_the_server_has():
    server = FakeModelServer(models=("qwen3-8b", "a.x-3.1"))
    with pytest.raises(ModelNotFound, match="gemma"):
        await _probe(_llm(server, model="gemma-3-27b"))
    llm = _llm(server, model="gemma-3-27b")
    with pytest.raises(ModelNotFound, match="qwen3-8b, a.x-3.1"):
        await llm.warm_up()
    assert llm.served_models == ["qwen3-8b", "a.x-3.1"]
    # Ollama lists tags: "qwen3" is "qwen3:latest".
    await _llm(FakeModelServer(models=("qwen3:latest",)), model="qwen3").warm_up()
    # A gateway without /models: nothing to check before the first call.
    quiet = FakeModelServer()
    quiet.list_models = False
    llm = _llm(quiet)
    await llm.warm_up()
    assert llm.served_models is None


async def test_timeouts():
    server = FakeModelServer()
    server.delay = 1.0
    with pytest.raises(ServerTimeout, match="0.2초"):
        await _probe(_llm(server, timeout=0.2))

    def slow_stream(request: httpx2.Request) -> httpx2.Response:
        class Stalls(httpx2.AsyncByteStream):
            async def __aiter__(self):
                yield b'data: {"choices": [{"delta": {"content": "\xec\xb2\xab "}}]}\n\n'
                raise httpx2.ReadTimeout("no next token")

        return httpx2.Response(200, stream=Stalls())

    llm = _llm(transport=httpx2.MockTransport(slow_stream))
    received = []
    with pytest.raises(ServerTimeout):
        async for piece in llm.stream("s", "p"):
            received.append(piece)
    assert received == ["첫 "]


async def test_server_errors_mid_stream():
    def handler(request: httpx2.Request) -> httpx2.Response:
        body = b'data: {"error": {"message": "CUDA out of memory"}}\n\n'
        return httpx2.Response(200, content=body)

    with pytest.raises(RuntimeError, match="CUDA out of memory"):
        _ = [p async for p in _llm(transport=httpx2.MockTransport(handler)).stream("s", "p")]


# --- OpenAI's services are refused ---------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://api.openai.com/v1",
        "https://API.OpenAI.com./v1",
        "http://openai.com/v1",
        "https://my-resource.openai.azure.com/openai/v1",
    ],
)
def test_openai_service_addresses_are_refused(url):
    with pytest.raises(ValueError, match="OpenAI 서비스"):
        check_base_url(url)
    with pytest.raises(ValueError, match="OpenAI 서비스"):
        OpenModelServerLLM(base_url=url, model="gpt-4o")  # stored specs are checked too


def test_in_house_addresses_pass_and_bad_ones_do_not():
    assert check_base_url(" http://10.0.0.5:8000/v1/ ") == "http://10.0.0.5:8000/v1"
    assert check_base_url("http://localhost:11434/v1") == "http://localhost:11434/v1"
    assert check_base_url("https://llm-gw.corp.example/openai-compat/v1")
    assert check_base_url("http://notopenai.com.internal/v1")
    for bad in ("", "10.0.0.5:8000/v1", "ftp://x/v1", "http://user:pw@x/v1", "http://x/v1?k=1"):
        with pytest.raises(ValueError):
            check_base_url(bad)


def test_the_default_config_builds_the_provider_without_calling_it():
    spec = ProviderSpec(impl="open_model_server", base_url=BASE, model="qwen3-8b")
    llm = registry.resolve("llm", spec)
    assert isinstance(llm, OpenModelServerLLM) and llm.model == "qwen3-8b"


# --- the AI gateway: guard first, audit always ---------------------------------------------------


async def test_the_guard_refuses_before_anything_reaches_the_server(db_factory):
    server = FakeModelServer()
    gateway = AiGateway({"primary": _llm(server)})
    known = KnownIdentity(name="강도윤")
    call = AiCall(
        action="screening.assessed",
        prompt_version="v",
        system="s",
        prompt="저는 강도윤입니다. 010-2345-6789",
        candidate_texts=["저는 강도윤입니다. 010-2345-6789"],
        known=known,
    )
    with db_factory() as db:
        with pytest.raises(IdentifierInPrompt):
            await gateway.generate(db, call)
        with pytest.raises(IdentifierInPrompt):
            gateway.stream(db, call)
        logs = db.scalars(select(AuditLog)).all()
    assert server.requests == []
    assert len(logs) == 2 and all(log.details["refused"] for log in logs)
    assert all(log.model == "qwen3-8b" for log in logs)


async def test_calls_and_failures_are_audited_by_model_and_cause(db_factory):
    server = FakeModelServer(reported_model="Qwen/Qwen3-8B")
    gateway = AiGateway({"primary": _llm(server)})
    call = AiCall(
        action="model.connection_test",
        prompt_version="connection-test-v0.2",
        system=CONNECTION_TEST_SYSTEM,
        prompt=connection_test_prompt(),
        schema=CONNECTION_TEST_SCHEMA,
    )
    with db_factory() as db:
        await gateway.generate(db, call)
        gateway.llms["primary"] = _llm(transport=_raising(httpx2.ReadTimeout("slow")))
        with pytest.raises(ServerTimeout):
            await gateway.generate(db, call)
        ok, failed = db.scalars(select(AuditLog).order_by(AuditLog.occurred_at)).all()
    assert ok.model == "Qwen/Qwen3-8B" and ok.input_tokens and ok.output_tokens
    assert ok.prompt_version == "connection-test-v0.2"
    assert failed.details == {"error": "ServerTimeout"}
    for log in (ok, failed):  # prompts and answers are not logged
        assert "모델 연결 확인" not in json.dumps(log.details or {}, ensure_ascii=False)


# --- the admin screen ------------------------------------------------------------------------------

SPEC = {"impl": "open_model_server", "options": {"base_url": BASE, "model": "qwen3-8b"}}


def _test(api, spec: dict, role: str = "llm.primary"):
    return api.post(f"/api/admin/models/{role}/test", data={"spec": json.dumps(spec)})


def _check(api, options: dict):
    return api.post(
        "/api/admin/models/llm.primary/check", json={"impl": "open_model_server", "options": options}
    )


@pytest.fixture
def server(monkeypatch):
    server = FakeModelServer(reported_model="Qwen/Qwen3-8B")
    monkeypatch.setattr(OpenModelServerLLM, "transport", server.transport())
    return server


def test_the_catalog_entry(api):
    info = next(i for i in api.get("/api/admin/models/catalog").json() if i["impl"] == "open_model_server")
    assert info["label"] == "오픈소스 모델 서버 (vLLM·Ollama 등)"
    assert info["data_location"] == "server" and set(info["roles"]) == {"llm.primary", "llm.screening"}
    assert "OpenAI 서비스로는 보내지 않습니다" in info["description"]
    options = {f["key"]: f for f in info["options"]}
    assert list(options) == [
        "base_url",
        "model",
        "api_key_env",
        "timeout",
        "max_tokens",
        "temperature",
        "structured_output",
        "headers",
        "extra_body",
    ]
    assert options["base_url"]["default"] == "" and options["model"]["default"] == ""
    vertex = next(i for i in api.get("/api/admin/models/catalog").json() if i["impl"] == "anthropic_vertex")
    assert vertex["data_location"] == "gcp"
    checked = api.post(
        "/api/admin/models/llm.primary/check", json={"impl": "anthropic_vertex", "options": {}}
    ).json()
    assert checked["external"] is True  # Google Cloud is outside the company: confirm first


def test_options_are_checked_on_the_screen(api, monkeypatch):
    def error(options: dict) -> tuple[int, str]:
        response = _check(api, options)
        return response.status_code, json.dumps(response.json(), ensure_ascii=False)

    status, body = error({"base_url": "https://api.openai.com/v1", "model": "gpt-4o"})
    assert status == 422 and "base_url" in body and "OpenAI 서비스" in body
    status, body = error({"base_url": "", "model": "m"})
    assert status == 422 and "base_url" in body
    status, body = error({"base_url": BASE, "model": "m", "api_key_env": "sk-123 456"})
    assert status == 422 and "api_key_env" in body
    status, body = error({"base_url": BASE, "model": "m", "headers": "X-Api-Key: plain"})
    assert status == 422 and "headers" in body
    status, body = error({"base_url": BASE, "model": "m", "extra_body": '{"model": "other"}'})
    assert status == 422 and "extra_body" in body
    status, body = error(
        {"base_url": BASE, "model": "m", "api_key_env": "K", "headers": "Authorization: Bearer ${K}"}
    )
    assert status == 422 and "headers" in body

    monkeypatch.delenv("IA_TEST_LLM_KEY", raising=False)
    checked = _check(
        api, {"base_url": BASE + "/", "model": "qwen3-8b", "api_key_env": "IA_TEST_LLM_KEY"}
    ).json()
    assert checked["spec"]["options"]["base_url"] == BASE  # normalized
    assert checked["spec"]["options"]["timeout"] == 120 and checked["external"] is False
    reqs = {r["key"]: r for r in checked["requirements"]}
    assert reqs["env:IA_TEST_LLM_KEY"]["ok"] is False and checked["ready"] is False
    monkeypatch.setenv("IA_TEST_LLM_KEY", KEY)
    checked = _check(api, {"base_url": BASE, "model": "qwen3-8b", "api_key_env": "IA_TEST_LLM_KEY"})
    assert checked.json()["ready"] is True and KEY not in checked.text


def test_connection_test_reports_timings_and_the_servers_model(api, server):
    result = _test(api, SPEC).json()
    assert result["ok"] is True, result
    out = result["output"]
    assert out["structured"] == ECHO and out["server_model"] == "Qwen/Qwen3-8B"
    assert out["server_models"] == ["qwen3-8b"]
    assert out["generate_ms"] >= 0 and out["first_token_ms"] is not None and out["stream_text"]
    assert "첫 토큰" in result["summary"]
    # One structured call and one stream, both through the gateway; the admin's test is recorded.
    calls = [r for r in server.requests if r["path"].endswith("/chat/completions")]
    assert [c["body"]["stream"] for c in calls] == [False, True]
    rows = sorted(
        api.runtime.session_factory().scalars(
            select(AuditLog).where(AuditLog.action == "model.connection_test")
        ),
        key=lambda r: r.occurred_at,
    )
    assert len(rows) == 2 and rows[1].details == {"stream": True}
    [tested] = api.runtime.session_factory().scalars(
        select(AuditLog).where(AuditLog.action == "model.tested")
    )
    assert tested.details["server_model"] == "Qwen/Qwen3-8B" and "first_token_ms" in tested.details
    assert tested.details["data_location"] == "server"


@pytest.mark.parametrize(
    ("change", "failure", "label"),
    [
        ({"model": "gemma-3-27b"}, "model", "모델 없음"),
        ({"base_url": "http://vllm.test:8000"}, "address", "주소 오류"),
    ],
)
def test_connection_test_names_the_cause(api, server, change, failure, label):
    spec = {"impl": "open_model_server", "options": {**SPEC["options"], **change}}
    result = _test(api, spec).json()
    assert result["ok"] is False and result["summary"] == f"테스트 실패: {label}"
    assert result["output"] == {"failure": failure} and result["error"].startswith(label)
    [tested] = api.runtime.session_factory().scalars(
        select(AuditLog).where(AuditLog.action == "model.tested")
    )
    assert tested.details["failure"] == failure


def test_connection_test_failures_by_cause_never_show_the_key(api, monkeypatch):
    server = FakeModelServer(api_key=KEY)
    monkeypatch.setattr(OpenModelServerLLM, "transport", server.transport())
    monkeypatch.setenv("IA_TEST_LLM_KEY", "wrong-" + KEY)
    spec = {"impl": "open_model_server", "options": {**SPEC["options"], "api_key_env": "IA_TEST_LLM_KEY"}}
    response = _test(api, spec)
    assert response.json()["summary"] == "테스트 실패: 인증 실패" and KEY not in response.text
    logs = api.runtime.session_factory().scalars(select(AuditLog)).all()
    assert all(KEY not in json.dumps(log.details or {}, ensure_ascii=False) for log in logs)

    monkeypatch.setattr(OpenModelServerLLM, "transport", _raising(httpx2.ReadTimeout("slow")))
    monkeypatch.setattr(OpenModelServerLLM, "warm_up", lambda self: _noop())
    result = _test(api, SPEC).json()
    assert result["summary"] == "테스트 실패: 시간 초과" and result["output"] == {"failure": "timeout"}


async def _noop() -> None:
    return None


def test_applied_it_serves_the_app_through_the_gateway(api, server):
    """Applied as the main LLM, the app's own work goes to the model server: a competency draft
    from a posting, with the draft's schema as response_format."""
    applied = api.post(
        "/api/admin/models/llm.primary/apply", json={**SPEC, "reason": "사내 vLLM 연결"}
    )
    assert applied.status_code == 200, applied.text
    state = applied.json()
    assert state["data_location"] == "server" and state["model"] == "qwen3-8b"
    before = len(server.bodies())
    response = api.post(f"/api/rounds/{round_id(api, P3)}/competency-sets/generate")
    assert response.status_code == 201, response.text
    [body] = server.bodies()[before:]
    assert body["response_format"]["json_schema"]["name"] == "CompetencyDraft"
    assert response.json()["competencies"]
    [drafted] = [
        log
        for log in api.runtime.session_factory().scalars(select(AuditLog))
        if log.prompt_version and log.prompt_version.startswith("competency")
    ]
    assert drafted.model == "Qwen/Qwen3-8B" and drafted.output_tokens
