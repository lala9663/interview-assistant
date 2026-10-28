"""MCP server for the in-house agent platform (docs/agent-integration.md).

A thin layer over the REST API: every tool calls /api over HTTP with the asking person's token,
so the API's guard, permissions, de-identification and audit log apply exactly as they do to the
web screen. Read tools, and proposals that change nothing: a person confirms them on the web.

    uv run python -m interview_assistant.agent                      # stdio, IA_MCP_TOKEN
    uv run python -m interview_assistant.agent --transport http     # streamable HTTP, :8765/mcp

Needs the `agent` extra (the Python MCP SDK).
"""
