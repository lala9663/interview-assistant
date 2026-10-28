"""MCP server settings (IA_MCP_* environment variables or .env). The API's own settings are not
read here: the MCP server knows the API only by its URL."""

from __future__ import annotations

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="IA_MCP_", env_file=".env", extra="ignore")

    # The REST API the tools call, and the web screen the links point at.
    api_url: str = "http://127.0.0.1:8000"
    web_url: str = "http://localhost:5173"
    # Sent as X-Agent-Name and kept in the audit log: which platform or agent made the call.
    agent_name: str = "mcp-local"
    # Who is asking (agent/identity.py). HTTP: the headers the platform sends each user's token
    # in, first found wins (`Authorization` as is, others carry the bare token). stdio: the token
    # of the one person running this server (scripts/agent_token.py), never used over HTTP.
    identity_headers: list[str] = ["authorization", "x-ia-token"]
    token: SecretStr | None = None
    timeout: float = 30.0
