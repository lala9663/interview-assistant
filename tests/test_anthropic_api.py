"""The Claude API LLM provider (external development tests only): generation, streaming, structured
output, failures by cause, the key kept out of every message and log, the AI gateway's guard and
audit log, the admin screen's catalog, test and apply with the external-transfer confirmation, and
the app's own work once applied (a competency draft, live follow-ups). No network: the API is an
in-process ASGI app (tests/fake_anthropic_api.py) behind the real SDK, or an httpx2 MockTransport."""

from __future__ import annotations

import json

import httpx2
import pytest
from sqlalchemy import select

from interview_assistant import config
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
from interview_assistant.providers import catalog, registry
from interview_assistant.providers.llm.anthropic_api import (
    FALLBACK_BETA,
    LATENCY_NOTE,
    AnthropicLLM,
    APITimeout,
    AuthFailed,
    BadOutput,
    BadRequest,
    ClaudeAPIError,
    ModelNotFound,
    RateLimited,
    Refused,
    Unreachable,
)
from tests.api_util import P3, SCHEDULED, round_id, sse_events
from tests.fake_anthropic_api import FakeAnthropicAPI

KEY = "sk-ant-api03-test-5c1f9e7a2b8d"
ECHO = {"echo": "모델 연결 확인 문장입니다", "sum": 42}
SAMPLING = ("temperature", "top_p", "top_k")


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    """The key from the test's environment only (not the laptop's .env), no retries, and Claude
    Code's ANTHROPIC_BASE_URL set as it is on this laptop."""
    monkeypatch.setattr(config, "ENV_FILE", tmp_path / ".env")
    monkeypatch.setenv("ANTHROPIC_API_KEY", KEY)
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://127.0.0.1:9/somewhere-else")
    monkeypatch.setattr(AnthropicLLM, "max_retries", 0)


def _llm(server: FakeAnthropicAPI | None = None, transport=None, **options) -> AnthropicLLM:
    llm = AnthropicLLM(**options)
    llm.transport = transport if transport is not None else server.transport()
    return llm


async def _probe(llm: AnthropicLLM):
    return await llm.generate(
        CONNECTION_TEST_SYSTEM, connection_test_prompt(), schema=CONNECTION_TEST_SCHEMA, max_tokens=200
    )


def _raising(exc: Exception) -> httpx2.MockTransport:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise exc

    return httpx2.MockTransport(handler)


# --- generation and streaming -----------------------------------------------------------------


async def test_generate_sends_the_messages_api_format_and_reads_structured_output():
    server = FakeAnthropicAPI(reported_model="claude-opus-5-5")
    result = await _probe(_llm(server))
    assert result.structured == ECHO
    assert result.model == "claude-opus-5-5" and result.input_tokens > 0 and result.output_tokens > 0

    [request] = server.requests
    assert request["host"] == "api.anthropic.com"  # not ANTHROPIC_BASE_URL
    assert request["headers"]["x-api-key"] == KEY and "authorization" not in request["headers"]
    assert FALLBACK_BETA in request["headers"]["anthropic-beta"]
    body = request["body"]
    assert body["model"] == "claude-opus-5-5" and body["fallbacks"] == "default"
    assert body["max_tokens"] == 200 + 4096  # the answer plus room for thinking
    assert body["system"] == CONNECTION_TEST_SYSTEM
    assert body["messages"] == [{"role": "user", "content": connection_test_prompt()}]
    assert body["output_config"]["effort"] == "low"
    schema = body["output_config"]["format"]["schema"]
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert schema["title"] == "ConnectionTest" and schema["additionalProperties"] is False
    assert "thinking" not in body and not set(SAMPLING) & set(body) and "stream" not in body


async def test_the_cap_effort_and_haiku_without_fallback():
    server = FakeAnthropicAPI()
    await _llm(server, max_tokens=2048, effort="medium").generate("s", "p", max_tokens=4000)
    body = server.bodies()[-1]
    assert body["max_tokens"] == 2048 and body["output_config"] == {"effort": "medium"}

    await _llm(server, model="claude-haiku-5-5").generate("s", "p")
    request = server.requests[-1]
    assert "fallbacks" not in request["body"] and "anthropic-beta" not in request["headers"]
    await _llm(server, model="claude-sonnet-5-5").generate("s", "p")
    assert server.bodies()[-1]["fallbacks"] == "default"


async def test_limits_the_api_does_not_take_move_into_the_description():
    from interview_assistant.ai.prompts import COMPETENCY_SCHEMA

    server = FakeAnthropicAPI()
    await _llm(server).generate("s", "공고", schema=COMPETENCY_SCHEMA)
    schema = server.bodies()[-1]["output_config"]["format"]["schema"]
    competencies = schema["properties"]["competencies"]
    assert "minItems" not in competencies and "minItems: 3" in competencies["description"]
    item = competencies["items"]
    assert item["additionalProperties"] is False and item["properties"]["bars"]["additionalProperties"] is False


async def test_stream_yields_only_the_answer_and_asks_for_it_right_away():
    server = FakeAnthropicAPI()
    pieces = [p async for p in _llm(server).stream("시스템", "<echo>\n모델 연결 확인 문장입니다\n</echo>")]
    assert pieces and "모델 연결 확인 문장입니다" in "".join(pieces)
    body = server.bodies()[-1]
    assert body["stream"] is True and "output_config" in body and "format" not in body["output_config"]
    assert body["system"] == f"시스템\n\n{LATENCY_NOTE}"
    assert not set(SAMPLING) & set(body)


async def test_the_key_is_read_from_env_file_at_each_call(monkeypatch, tmp_path):
    server = FakeAnthropicAPI(api_key=KEY)
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    llm = _llm(server)
    with pytest.raises(AuthFailed, match="ANTHROPIC_API_KEY"):
        await llm.generate("s", "p")
    assert server.requests == []  # nothing sent without a key

    (tmp_path / ".env").write_text(f"IA_DEMO_SPEED=0\nANTHROPIC_API_KEY={KEY}\n", encoding="utf-8")
    assert (await _probe(llm)).structured == ECHO  # the same instance: no restart
    assert server.requests[-1]["headers"]["x-api-key"] == KEY

    info = catalog.impl_info("llm", "anthropic_api")
    [env] = [r for r in catalog.requirements(info, info.defaults("llm.primary"), weights_dir=tmp_path) if r.key.startswith("env:")]
    assert env.ok and env.detail == ".env에 있습니다." and KEY not in repr(env)


# --- failures by cause --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "kind", "headers", "error", "match"),
    [
        (401, "authentication_error", {}, AuthFailed, "HTTP 401"),
        (403, "permission_error", {}, AuthFailed, "HTTP 403"),
        (402, "billing_error", {}, AuthFailed, "크레딧"),
        (429, "rate_limit_error", {"retry-after": "17"}, RateLimited, "17초 뒤"),
        (400, "invalid_request_error", {}, BadRequest, "HTTP 400"),
        (500, "api_error", {}, ClaudeAPIError, "HTTP 500"),
        (529, "overloaded_error", {}, ClaudeAPIError, "과부하"),
        (504, "timeout_error", {}, APITimeout, "HTTP 504"),
    ],
)
async def test_api_errors_by_cause(status, kind, headers, error, match):
    server = FakeAnthropicAPI()
    server.fail = (status, kind, "something went wrong", headers)
    with pytest.raises(error, match=match) as exc:
        await _probe(_llm(server))
    assert "something went wrong" in str(exc.value) and "req_fake01" in str(exc.value)
    assert str(exc.value).startswith(exc.value.label)


async def test_connection_model_timeout_refusal_and_output_failures():
    with pytest.raises(Unreachable, match="api.anthropic.com"):
        await _probe(_llm(transport=_raising(httpx2.ConnectError("refused"))))
    with pytest.raises(APITimeout, match="1초"):
        await _probe(_llm(transport=_raising(httpx2.ReadTimeout("slow")), timeout=1))
    slow = FakeAnthropicAPI()
    slow.delay = 1.0
    with pytest.raises(APITimeout, match="0.2초"):
        await _probe(_llm(slow, timeout=0.2))

    server = FakeAnthropicAPI(models=("claude-opus-5-5",))
    with pytest.raises(ModelNotFound, match="claude-haiku-5-5"):
        await _probe(_llm(server, model="claude-haiku-5-5"))

    server.refuse = True
    with pytest.raises(Refused, match="cyber"):
        await _probe(_llm(server))
    with pytest.raises(Refused):
        _ = [p async for p in _llm(server).stream("s", "p")]
    server.refuse = False

    server.truncate = True
    with pytest.raises(BadOutput, match="최대 토큰\\(4296\\)"):
        await _probe(_llm(server))
    server.truncate, server.not_json = False, True
    with pytest.raises(BadOutput, match="JSON 객체"):
        await _probe(_llm(server))


async def test_an_error_event_mid_stream_after_the_first_piece():
    server = FakeAnthropicAPI()
    server.stream_error = True
    received = []
    with pytest.raises(ClaudeAPIError, match="과부하"):
        async for piece in _llm(server).stream("s", "<echo>\n모델 연결 확인 문장입니다\n</echo>"):
            received.append(piece)
    assert len(received) == 1


async def test_a_stream_that_stalls_after_the_first_token_is_a_timeout():
    def event(name: str, data: dict) -> bytes:
        return f"event: {name}\ndata: {json.dumps({'type': name, **data}, ensure_ascii=False)}\n\n".encode()

    def stalls(request: httpx2.Request) -> httpx2.Response:
        class Body(httpx2.AsyncByteStream):
            async def __aiter__(self):
                message = {"id": "m", "type": "message", "role": "assistant", "model": "claude-opus-5-5", "content": [],
                           "stop_reason": None, "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 1}}
                yield event("message_start", {"message": message})
                yield event("content_block_start", {"index": 0, "content_block": {"type": "text", "text": ""}})
                yield event("content_block_delta", {"index": 0, "delta": {"type": "text_delta", "text": "첫 "}})
                raise httpx2.ReadTimeout("no next token")

        return httpx2.Response(200, headers={"content-type": "text/event-stream"}, stream=Body())

    received = []
    with pytest.raises(APITimeout):
        async for piece in _llm(transport=httpx2.MockTransport(stalls)).stream("s", "p"):
            received.append(piece)
    assert received == ["첫 "]


async def test_warm_up_checks_the_key_and_the_model_without_a_prompt():
    server = FakeAnthropicAPI(api_key=KEY, models=("claude-opus-5-5",))
    await _llm(server).warm_up()
    [request] = server.requests
    assert request["path"] == "/v1/models/claude-opus-5-5" and request["body"] is None
    with pytest.raises(ModelNotFound):
        await _llm(server, model="claude-sonnet-5-5").warm_up()
    server.api_key = "another-key"
    with pytest.raises(AuthFailed, match="HTTP 401"):
        await _llm(server).warm_up()


async def test_the_key_never_shows_even_when_the_api_repeats_it(monkeypatch):
    server = FakeAnthropicAPI(api_key="right-" + KEY)
    server.echo_key = True
    with pytest.raises(AuthFailed) as exc:
        await _probe(_llm(server))
    assert KEY not in str(exc.value) and "■■■" in str(exc.value)
    server.api_key, server.fail = None, (429, "rate_limit_error", "slow down", {})
    with pytest.raises(RateLimited) as exc:
        await _probe(_llm(server))
    assert KEY not in str(exc.value) and "■■■" in str(exc.value)


def test_stored_specs_are_checked_too():
    for bad in ({"model": "gpt-4o"}, {"effort": "turbo"}, {"api_key_env": "sk-ant 123"}, {"api_key_env": ""}):
        with pytest.raises(ValueError):
            AnthropicLLM(**bad)
    spec = ProviderSpec(impl="anthropic_api", model="claude-sonnet-5-5")
    llm = registry.resolve("llm", spec)
    assert isinstance(llm, AnthropicLLM) and llm.model == "claude-sonnet-5-5" and llm.effort == "low"


# --- the AI gateway: guard first, audit always ---------------------------------------------------


async def test_the_guard_refuses_before_anything_is_sent(db_factory):
    server = FakeAnthropicAPI()
    gateway = AiGateway({"primary": _llm(server)})
    call = AiCall(
        action="screening.assessed",
        prompt_version="v",
        system="s",
        prompt="저는 강도윤입니다. 010-2345-6789",
        candidate_texts=["저는 강도윤입니다. 010-2345-6789"],
        known=KnownIdentity(name="강도윤"),
    )
    with db_factory() as db:
        with pytest.raises(IdentifierInPrompt):
            await gateway.generate(db, call)
        with pytest.raises(IdentifierInPrompt):
            gateway.stream(db, call)
        logs = db.scalars(select(AuditLog)).all()
    assert server.requests == []
    assert len(logs) == 2 and all(log.details["refused"] for log in logs)
    assert all(log.model == "claude-opus-5-5" for log in logs)


async def test_calls_and_failures_are_audited_by_model_tokens_and_cause(db_factory):
    server = FakeAnthropicAPI(reported_model="claude-opus-4-8")  # a fallback model answered
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
        server.fail = (429, "rate_limit_error", f"limit for {KEY}", {})
        server.echo_key = True
        with pytest.raises(RateLimited):
            await gateway.generate(db, call)
        ok, failed = db.scalars(select(AuditLog).order_by(AuditLog.occurred_at)).all()
    assert ok.model == "claude-opus-4-8" and ok.input_tokens and ok.output_tokens
    assert ok.prompt_version == "connection-test-v0.2" and ok.details is None
    assert failed.model == "claude-opus-5-5" and failed.details == {"error": "RateLimited"}
    for log in (ok, failed):  # no prompt, answer or key
        text = json.dumps(log.details or {}, ensure_ascii=False)
        assert "모델 연결 확인" not in text and KEY not in text


# --- the admin screen ------------------------------------------------------------------------------

SPEC = {"impl": "anthropic_api", "options": {}}


@pytest.fixture
def server(monkeypatch):
    server = FakeAnthropicAPI(api_key=KEY, reported_model="claude-opus-5-5")
    monkeypatch.setattr(AnthropicLLM, "transport", server.transport())
    return server


def _test(api, spec: dict, *, confirm: bool = True, role: str = "llm.primary"):
    data = {"spec": json.dumps(spec), "confirm_external": str(confirm).lower()}
    return api.post(f"/api/admin/models/{role}/test", data=data)


def _apply(api, spec: dict, *, confirm: bool = True, reason: str = "Claude API로 꼬리질문 품질 확인"):
    return api.post(
        "/api/admin/models/llm.primary/apply", json={**spec, "reason": reason, "confirm_external": confirm}
    )


def _everything(api) -> str:
    """Every audit row's details, for a search."""
    logs = api.runtime.session_factory().scalars(select(AuditLog)).all()
    return json.dumps([log.details for log in logs], ensure_ascii=False)


def test_the_catalog_entry(api):
    info = next(i for i in api.get("/api/admin/models/catalog").json() if i["impl"] == "anthropic_api")
    assert info["label"] == "Claude API (외부, 개발 테스트용)"
    assert info["data_location"] == "external" and set(info["roles"]) == {"llm.primary", "llm.screening"}
    assert "사내 반입 대상이 아닙니다" in info["description"] and "OpenAI" not in json.dumps(info, ensure_ascii=False)
    options = {f["key"]: f for f in info["options"]}
    assert list(options) == ["model", "effort", "max_tokens", "timeout", "api_key_env"]
    assert options["model"]["default"] == "claude-opus-5-5" and options["effort"]["default"] == "low"
    assert [c["value"] for c in options["model"]["choices"]] == ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"]
    assert "2초" in options["model"]["help"] and "2초" in options["effort"]["help"]
    assert options["api_key_env"]["default"] == "ANTHROPIC_API_KEY"


def test_options_and_requirements_on_the_screen(api, monkeypatch):
    checked = api.post("/api/admin/models/llm.primary/check", json=SPEC).json()
    assert checked["external"] is True and checked["ready"] is True
    assert checked["spec"]["options"]["model"] == "claude-opus-5-5"
    reqs = {r["key"]: r for r in checked["requirements"]}
    assert reqs["package:anthropic"]["ok"] and reqs["env:ANTHROPIC_API_KEY"]["ok"]
    assert KEY not in json.dumps(checked)
    screening = api.post("/api/admin/models/llm.screening/check", json=SPEC).json()
    assert screening["spec"]["options"]["model"] == "claude-haiku-5-5"

    monkeypatch.delenv("ANTHROPIC_API_KEY")
    checked = api.post("/api/admin/models/llm.primary/check", json=SPEC).json()
    env = {r["key"]: r for r in checked["requirements"]}["env:ANTHROPIC_API_KEY"]
    assert env["ok"] is False and ".env" in env["fix"] and checked["ready"] is False

    bad = api.post(
        "/api/admin/models/llm.primary/check",
        json={"impl": "anthropic_api", "options": {"api_key_env": KEY}},
    )
    assert bad.status_code == 422 and "api_key_env" in bad.text
    bad = api.post(
        "/api/admin/models/llm.primary/check",
        json={"impl": "anthropic_api", "options": {"temperature": 0.2}},
    )
    assert bad.status_code == 422  # no sampling parameters


def test_connection_test_needs_the_confirmation_and_reports_timings(api, server):
    refused = _test(api, SPEC, confirm=False)
    assert refused.status_code == 409 and server.requests == []

    result = _test(api, SPEC).json()
    assert result["ok"] is True, result
    out = result["output"]
    assert out["structured"] == ECHO and out["server_model"] == "claude-opus-5-5"
    assert out["first_token_ms"] is not None and out["stream_text"] and "첫 토큰" in result["summary"]
    # Warm-up (the key and the model), then one structured call and one stream.
    assert [r["path"] for r in server.requests] == ["/v1/models/claude-opus-5-5", "/v1/messages", "/v1/messages"]
    assert [b.get("stream", False) for b in server.bodies()] == [False, True]
    [tested] = api.runtime.session_factory().scalars(select(AuditLog).where(AuditLog.action == "model.tested"))
    assert tested.details["data_location"] == "external" and tested.details["server_model"] == "claude-opus-5-5"
    assert KEY not in _everything(api)


@pytest.mark.parametrize(
    ("change", "failure", "label"),
    [("key", "auth", "인증 실패"), ("limit", "rate_limit", "요청 한도 초과")],
)
def test_connection_test_names_the_cause_without_the_key(api, server, monkeypatch, change, failure, label):
    server.echo_key = True
    if change == "key":
        monkeypatch.setenv("ANTHROPIC_API_KEY", "wrong-" + KEY)
    else:
        monkeypatch.setattr(AnthropicLLM, "warm_up", _noop)
        server.fail = (429, "rate_limit_error", "rate limited", {"retry-after": "30"})
    response = _test(api, SPEC)
    result = response.json()
    assert result["ok"] is False and result["summary"] == f"테스트 실패: {label}"
    assert result["output"] == {"failure": failure} and result["error"].startswith(label)
    assert KEY not in response.text and KEY not in _everything(api)


async def _noop(self) -> None:
    return None


def test_applied_it_serves_the_app_and_rollback_asks_again(api, server):
    """Applied as the main LLM with the confirmation and a reason, the app's own work goes to the
    Claude API: a competency draft with its schema as output_config.format. Going back to it from
    another setting asks for the confirmation again."""
    assert _apply(api, SPEC, confirm=False).status_code == 409
    assert _apply(api, SPEC, reason=" ").status_code == 422
    applied = _apply(api, SPEC)
    assert applied.status_code == 200, applied.text
    state = applied.json()
    assert state["data_location"] == "external" and state["model"] == "claude-opus-5-5"

    before = len(server.bodies())
    response = api.post(f"/api/rounds/{round_id(api, P3)}/competency-sets/generate")
    assert response.status_code == 201, response.text
    [body] = server.bodies()[before:]
    assert body["output_config"]["format"]["schema"]["title"] == "CompetencyDraft"
    assert response.json()["competencies"]
    [drafted] = [
        log
        for log in api.runtime.session_factory().scalars(select(AuditLog))
        if log.prompt_version and log.prompt_version.startswith("competency")
    ]
    assert drafted.model == "claude-opus-5-5" and drafted.output_tokens

    away = _apply(api, {"impl": "fake", "options": {}}, reason="fake로 돌아감")
    assert away.status_code == 200, away.text
    history = api.get("/api/admin/models/history", params={"role": "llm.primary"}).json()
    last = history[0]["id"]
    body = {"reason": "Claude API로 다시", "confirm_external": False}
    assert api.post(f"/api/admin/models/history/{last}/revert", json=body).status_code == 409
    back = api.post(f"/api/admin/models/history/{last}/revert", json={**body, "confirm_external": True})
    assert back.status_code == 200 and back.json()["data_location"] == "external"
    assert KEY not in _everything(api)


def test_an_interview_started_after_applying_gets_follow_ups_from_the_claude_api(api, server):
    """A session pins the config in force when it starts: one started after the change streams
    its follow-ups from the Claude API (typed answer, no recording)."""
    assert _apply(api, SPEC).status_code == 200
    api.post(f"/api/sessions/{SCHEDULED}/consent", json={"consent_recording": False})
    started = api.post(f"/api/sessions/{SCHEDULED}/start").json()
    preset = started["preset_questions"][0]
    qa = api.post(
        f"/api/sessions/{SCHEDULED}/qa-items",
        json={"question": preset["question"], "question_source": "preset", "preset_question_id": preset["id"]},
    ).json()
    answer = "챔버별로 나눠 보고 DOE로 3번 검증했습니다. 수율이 2%p 올랐습니다."
    api.patch(f"/api/qa-items/{qa['id']}", json={"answer_text": answer})

    before = len(server.bodies())
    response = api.post(f"/api/sessions/{SCHEDULED}/follow-ups", json={"qa_item_id": qa["id"]})
    events = sse_events(response.text)
    assert events[0][0] == "batch.start" and events[-1][0] == "batch.done", events
    assert events[0][1]["model"] == "claude-opus-5-5"
    ai = [d for e, d in events if e == "suggestion.done" and d["source"] == "ai"]
    assert len(ai) == 3 and all(d["question"] and d["grounding"] in answer for d in ai)
    [body] = [b for b in server.bodies()[before:] if b.get("stream")]
    assert body["system"].endswith(LATENCY_NOTE) and body["output_config"] == {"effort": "low"}
    assert body["fallbacks"] == "default" and KEY not in response.text
