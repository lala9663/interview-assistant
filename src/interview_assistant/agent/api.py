"""Calling the REST API for one tool call, as the person who asked (agent/identity.py says who).

API errors come back as tool errors carrying the API's Korean message, so the agent can tell the
person why (403 관리자만, 409 rules, …).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx2
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError

from interview_assistant.agent.identity import credentials
from interview_assistant.agent.settings import AgentSettings


def _client_name(ctx: Context) -> str | None:
    """The MCP client's name and version when it sent them (kept in the audit log)."""
    try:
        info = ctx.session.client_params.client_info  # type: ignore[union-attr]
    except Exception:
        return None
    if info is None:
        return None
    return f"{info.name}/{info.version}" if getattr(info, "version", None) else info.name


def _detail(response: httpx2.Response) -> str:
    try:
        detail = response.json().get("detail")
    except Exception:
        return response.text[:300] or f"HTTP {response.status_code}"
    if isinstance(detail, list):  # 422: [{"loc": [...], "msg": "..."}]
        return " ".join(
            f"{'.'.join(str(p) for p in item.get('loc', [])[1:])}: {item.get('msg', '')}".strip(": ")
            for item in detail
            if isinstance(item, dict)
        )
    return str(detail)


class ApiCall:
    """The API as seen from one tool call."""

    def __init__(self, client: httpx2.AsyncClient, settings: AgentSettings) -> None:
        self._client = client
        self._settings = settings

    async def request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = await self._client.request(method, path, **kwargs)
        except httpx2.HTTPError as exc:
            raise ToolError(
                f"API 서버({self._settings.api_url})에 연결할 수 없습니다: {type(exc).__name__}"
            ) from exc
        if response.status_code == 401:
            raise ToolError(f"인증되지 않았습니다: {_detail(response)}")
        if response.status_code >= 500:
            raise ToolError(f"API 서버 오류 ({response.status_code}): {_detail(response)}")
        if response.status_code >= 400:
            raise ToolError(_detail(response))
        return None if response.status_code == 204 else response.json()

    async def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        clean = {k: v for k, v in (params or {}).items() if v is not None}
        return await self.request("GET", path, params=clean)

    async def post(self, path: str, body: dict[str, Any]) -> Any:
        return await self.request("POST", path, json=body)


def _header(value: str) -> str:
    """Header values travel as ASCII: anything else becomes '?'."""
    return value.encode("ascii", "replace").decode("ascii")[:64]


@asynccontextmanager
async def api_call(ctx: Context, settings: AgentSettings, tool: str) -> AsyncIterator[ApiCall]:
    headers = {
        "Authorization": credentials(ctx, settings),
        "X-Agent-Name": _header(settings.agent_name),
        "X-Agent-Tool": tool,
        "Accept": "application/json",
    }
    client_name = _client_name(ctx)
    if client_name:
        headers["X-Agent-Client"] = _header(client_name)
    async with httpx2.AsyncClient(
        base_url=settings.api_url.rstrip("/"), headers=headers, timeout=settings.timeout
    ) as client:
        yield ApiCall(client, settings)
