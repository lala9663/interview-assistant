"""Agent calls (docs/agent-integration.md): who is asking, what an agent may do, the audit row.

The in-house agent platform reaches this API through the MCP server (interview_assistant/agent),
which forwards the asking person's credential. `AgentIdentity` turns it into an interviewer: for
now the development token signed here with IA_AGENT_TOKEN_SECRET (scripts/agent_token.py), which
names one interviewer and carries the scope `agent`. An agent call runs with that interviewer's
permissions; there is no shared service account.

- Reads only: GET, plus the routes marked `agent_may_call` (they compute an answer without
  storing anything: schedule suggestions, the prohibited-question check; or record a proposal).
  Every other write is 403: changes are made by a person on the web screen.
- Every agent call leaves one audit row: `agent.request`, or `agent.refused` when the guard turned
  it away. Agent name, tool, client, method, path (no query string, no body) and status.

When the platform and SSO are known, add an `AgentIdentity` for their credential (an IdP token
check, a signed user assertion from the platform) and pick it with IA_AGENT_IDENTITY; the guard,
the read-only rule and the audit stay as they are.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

import anyio
from fastapi import HTTPException, Request
from sqlalchemy import select

from interview_assistant.api.deps import RuntimeDep
from interview_assistant.models import ActorType, AuditLog, Interviewer
from interview_assistant.models.base import utcnow

log = logging.getLogger(__name__)

TOKEN_PREFIX = "iaa1"
SCOPE = "agent"
MAX_HOURS = 24 * 30

AGENT_HEADER = "x-agent-name"
TOOL_HEADER = "x-agent-tool"
CLIENT_HEADER = "x-agent-client"

READ_METHODS = frozenset({"GET", "HEAD"})


def agent_may_call(endpoint: Any) -> Any:
    """Marks a non-GET route an agent may call: it computes an answer and stores nothing
    (schedule suggestions, the prohibited-question check), or records a proposal."""
    endpoint.agent_may_call = True
    return endpoint


# --- development tokens (until SSO) ----------------------------------------------------------


class TokenError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class AgentToken:
    employee_no: str
    scope: str
    expires_at: datetime


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _signature(secret: str, signed: str) -> str:
    return _b64(hmac.new(secret.encode("utf-8"), signed.encode("ascii"), hashlib.sha256).digest())


def issue_token(
    secret: str, employee_no: str, *, hours: float = 24 * 7, now: datetime | None = None
) -> str:
    """`iaa1.<payload>.<HMAC-SHA256>`: the interviewer's employee number, scope `agent`, expiry."""
    if not 0 < hours <= MAX_HOURS:
        raise ValueError(f"hours must be in (0, {MAX_HOURS}]")
    now = now or utcnow()
    payload = {
        "sub": employee_no,
        "scope": SCOPE,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=hours)).timestamp()),
    }
    body = _b64(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signed = f"{TOKEN_PREFIX}.{body}"
    return f"{signed}.{_signature(secret, signed)}"


def verify_token(secret: str, token: str, *, now: datetime | None = None) -> AgentToken:
    parts = token.split(".")
    if len(parts) != 3 or parts[0] != TOKEN_PREFIX:
        raise TokenError("malformed_token", "에이전트 토큰 형식이 아닙니다.")
    signed = f"{parts[0]}.{parts[1]}"
    if not hmac.compare_digest(_signature(secret, signed), parts[2]):
        raise TokenError("bad_signature", "에이전트 토큰 서명이 맞지 않습니다.")
    try:
        payload = json.loads(_unb64(parts[1]))
        employee_no, scope, expires = str(payload["sub"]), payload["scope"], int(payload["exp"])
    except (ValueError, KeyError, TypeError) as exc:
        raise TokenError("malformed_token", "에이전트 토큰 형식이 아닙니다.") from exc
    if scope != SCOPE:
        raise TokenError("wrong_scope", "에이전트용 토큰이 아닙니다.")
    expires_at = datetime.fromtimestamp(expires, tz=timezone.utc)
    if expires_at <= (now or utcnow()):
        raise TokenError("expired_token", "에이전트 토큰이 만료되었습니다. 새로 발급하세요.")
    return AgentToken(employee_no=employee_no, scope=scope, expires_at=expires_at)


# --- who is asking: the replaceable part --------------------------------------------------------


class AgentIdentity(Protocol):
    """The credential of an agent call -> the employee number of the person asking. Raises
    TokenError (401) when the credential is missing, malformed, forged or expired."""

    def employee_no(self, credential: str) -> str: ...


class DevTokenIdentity:
    """Development tokens (scripts/agent_token.py), until the platform's or SSO's identity."""

    def __init__(self, secret: str) -> None:
        self._secret = secret

    def employee_no(self, credential: str) -> str:
        return verify_token(self._secret, credential).employee_no


def agent_identity(settings: Any) -> AgentIdentity:
    """IA_AGENT_IDENTITY picks how agent calls prove who is asking. Raises TokenError
    `not_configured` (503) when the chosen way is not set up."""
    if settings.agent_identity == "dev_token":
        secret = settings.agent_token_secret
        if secret is None or not secret.get_secret_value():
            raise TokenError(
                "not_configured", "에이전트 토큰 키(IA_AGENT_TOKEN_SECRET)가 설정되지 않았습니다."
            )
        return DevTokenIdentity(secret.get_secret_value())
    raise TokenError("not_configured", f"모르는 에이전트 신원 방식입니다: {settings.agent_identity}")


# --- the guard on /api -----------------------------------------------------------------------


@dataclass
class AgentCall:
    """Set on `request.state.agent_call` for every agent request, read by the audit middleware."""

    agent: str
    tool: str | None
    client: str | None
    interviewer_id: str | None = None
    refused: str | None = None  # the guard's reason code when it turned the call away


def _label(value: str | None) -> str | None:
    """Header values go into the audit log: printable characters, 64 at most."""
    if value is None:
        return None
    value = "".join(ch for ch in value if ch.isprintable()).strip()[:64]
    return value or None


def agent_call(request: Request) -> AgentCall | None:
    return getattr(request.state, "agent_call", None)


def agent_guard(request: Request, runtime: RuntimeDep) -> None:
    """Runs before every /api route. The web screen sends neither header and passes untouched.
    A request with `X-Agent-Name` or `Authorization` is an agent call: it needs a valid token of
    an existing interviewer and may only read."""
    headers = request.headers
    authorization = headers.get("authorization")
    name = headers.get(AGENT_HEADER)
    if authorization is None and name is None:
        return
    call = AgentCall(
        agent=_label(name) or "unnamed",
        tool=_label(headers.get(TOOL_HEADER)),
        client=_label(headers.get(CLIENT_HEADER)),
    )
    request.state.agent_call = call

    def refuse(status: int, code: str, message: str) -> HTTPException:
        call.refused = code
        return HTTPException(status, message)

    if authorization is None:
        raise refuse(
            401,
            "missing_token",
            "에이전트 호출에는 질문한 사람의 토큰(Authorization: Bearer …)이 필요합니다.",
        )
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise refuse(401, "malformed_token", "Authorization 헤더는 'Bearer <토큰>' 형식이어야 합니다.")
    try:
        identity = agent_identity(runtime.settings)
    except TokenError as exc:
        raise refuse(503, exc.code, exc.message) from exc
    try:
        employee_no = identity.employee_no(token.strip())
    except TokenError as exc:
        raise refuse(401, exc.code, exc.message) from exc
    with runtime.session_factory() as db:
        me = db.scalar(select(Interviewer).where(Interviewer.employee_no == employee_no))
    if me is None:
        raise refuse(401, "unknown_interviewer", "토큰의 면접관을 찾을 수 없습니다.")
    call.interviewer_id = me.id
    endpoint = getattr(request.scope.get("route"), "endpoint", None)
    if request.method not in READ_METHODS and not getattr(endpoint, "agent_may_call", False):
        raise refuse(
            403,
            "write_refused",
            "에이전트는 조회와 제안만 할 수 있습니다. 바꾸는 일은 웹 화면에서 사람이 확인해 반영합니다.",
        )


# --- one audit row per agent call ------------------------------------------------------------


def _record(factory: Any, call: AgentCall, method: str, path: str, status: int) -> None:
    details: dict[str, Any] = {
        "agent": call.agent,
        "tool": call.tool,
        "client": call.client,
        "method": method,
        "path": path,
        "status": status,
    }
    if call.refused:
        details["refused"] = call.refused
    with factory() as db:
        db.add(
            AuditLog(
                actor_type=ActorType.user if call.interviewer_id else ActorType.system,
                actor_id=call.interviewer_id,
                action="agent.refused" if call.refused else "agent.request",
                details={k: v for k, v in details.items() if v is not None},
            )
        )
        db.commit()


class AgentAuditMiddleware:
    """Writes an agent call's audit row (status included) before the response leaves: the
    caller gets no data the log does not show. If the row cannot be written, the answer is 503
    instead. Web requests carry no `agent_call` and pass through."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        recorded = False
        withheld = False

        async def record(status: int) -> bool:
            nonlocal recorded
            call = (scope.get("state") or {}).get("agent_call")
            if recorded or not isinstance(call, AgentCall):
                return True
            recorded = True
            runtime = scope["app"].state.runtime
            try:
                await anyio.to_thread.run_sync(
                    _record, runtime.session_factory, call, scope["method"], scope["path"], status
                )
            except Exception:
                log.exception("could not write the audit row of an agent call")
                return False
            return True

        async def send_after_audit(message: dict[str, Any]) -> None:
            nonlocal withheld
            if withheld:
                return
            if message["type"] == "http.response.start" and not await record(message["status"]):
                withheld = True
                body = json.dumps(
                    {"detail": "감사 로그를 남기지 못해 응답하지 않았습니다. 잠시 후 다시 시도하세요."},
                    ensure_ascii=False,
                ).encode("utf-8")
                await send(
                    {
                        "type": "http.response.start",
                        "status": 503,
                        "headers": [(b"content-type", b"application/json")],
                    }
                )
                await send({"type": "http.response.body", "body": body})
                return
            await send(message)

        try:
            await self.app(scope, receive, send_after_audit)
        finally:
            await record(500)  # the app failed before answering
