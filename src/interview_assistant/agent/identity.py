"""Who is asking, as the MCP server learns it: the one place to change when the agent platform is
chosen (docs/agent-integration.md 7장).

The MCP server holds no account of its own. It passes the asking person's credential to the API,
which checks it (api/agent_access.py `AgentIdentity`). Over HTTP the platform sends it with every
request, in a header (`ForwardedHeaders`); on stdio one person runs the server with their own
token (`ConfiguredToken`). There is no fallback from one to the other. A platform that passes the
user differently (MCP OAuth, a signed user assertion) gets its own `IdentitySource` here.
"""

from __future__ import annotations

from typing import Protocol

from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError

from interview_assistant.agent.settings import AgentSettings


class IdentitySource(Protocol):
    def authorization(self, ctx: Context) -> str:
        """The `Authorization` value for the API, or ToolError when nobody is named."""
        ...


class ForwardedHeaders:
    """HTTP: the first of `headers` the request carries. `Authorization` goes on as it is; any
    other header (a platform's "API key header" setting) carries the bare token."""

    def __init__(self, headers: list[str]) -> None:
        self.headers = [h.lower() for h in headers]

    def authorization(self, ctx: Context) -> str:
        incoming = ctx.headers or {}
        for name in self.headers:
            value = (incoming.get(name) or "").strip()
            if value:
                return value if name == "authorization" else f"Bearer {value}"
        raise ToolError(
            "질문한 사람의 토큰이 없습니다. MCP 클라이언트(에이전트 플랫폼) 설정에서 요청마다 "
            f"{' 또는 '.join(self.headers)} 헤더로 그 사람의 토큰을 보내야 합니다 "
            "(개발용 토큰은 scripts/agent_token.py)."
        )


class ConfiguredToken:
    """stdio: the person who runs this MCP server, by IA_MCP_TOKEN."""

    def __init__(self, token: str) -> None:
        self.token = token

    def authorization(self, ctx: Context) -> str:
        if not self.token:
            raise ToolError(
                "IA_MCP_TOKEN이 없습니다. scripts/agent_token.py로 본인 토큰을 발급해 MCP 서버 설정에 넣으세요."
            )
        return f"Bearer {self.token}"


def credentials(ctx: Context, settings: AgentSettings) -> str:
    """HTTP requests carry headers (`ctx.headers`); stdio has none."""
    if ctx.headers is not None:
        source: IdentitySource = ForwardedHeaders(settings.identity_headers)
    else:
        source = ConfiguredToken(settings.token.get_secret_value() if settings.token else "")
    return source.authorization(ctx)
