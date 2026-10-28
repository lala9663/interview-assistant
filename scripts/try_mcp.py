"""Call every MCP tool once against a running MCP server, with the SDK's client: a check before
connecting the agent platform (docs/agent-integration.md).

    uv run python scripts/try_mcp.py --url http://127.0.0.1:8765/mcp --token <토큰>
    uv run python scripts/try_mcp.py --stdio --token <토큰>      # starts the server itself

Read tools run with arguments taken from earlier answers (the first posting, its top applicant, …).
Proposal tools only record a proposal and change nothing. Prints one line per tool; --json writes
every answer to a file.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import httpx2
from mcp import Client, StdioServerParameters
from mcp.client.streamable_http import streamable_http_client


def _line(name: str, result: Any) -> str:
    if result.is_error:
        return f"  {name:<28} 오류: {' '.join(getattr(c, 'text', '') for c in result.content)[:160]}"
    body = result.structured_content or {}
    keys = ", ".join(f"{k}={len(v)}" if isinstance(v, list) else k for k, v in list(body.items())[:5])
    return f"  {name:<28} ok  {keys}"


async def run(client: Client, out: dict[str, Any]) -> None:
    async def call(name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        result = await client.call_tool(name, args or {})
        print(_line(name, result))
        out[name] = {"error": result.is_error, "result": result.structured_content}
        return {} if result.is_error else (result.structured_content or {})

    tools = (await client.list_tools()).tools
    print(f"도구 {len(tools)}개: {', '.join(t.name for t in tools)}")
    tasks = await call("get_my_tasks")
    postings = (await call("list_postings")).get("postings", [])
    posting = postings[0]["posting_id"] if postings else None
    applicant = None
    if posting:
        await call("get_posting", {"posting_id": posting})
        found = (await call("search_applicants", {"posting_id": posting, "limit": 5})).get("applicants", [])
        applicant = found[0]["application_id"] if found else None
    if applicant:
        await call("get_applicant_summary", {"applicant": applicant})
        await call("get_evaluation_summary", {"applicant": applicant})
    monday = date.today() + timedelta(days=7 - date.today().weekday())
    me = (tasks.get("me") or {}).get("name", "")
    await call(
        "find_common_free_time",
        {"interviewers": [me] if me else [], "date_from": monday.isoformat(), "date_to": (monday + timedelta(days=4)).isoformat()},
    )
    waiting = (await call("list_schedulable_applicants")).get("applicants", [])
    interviews = (await call("list_interviews", {"limit": 10})).get("interviews", [])
    await call("search_question_bank", {"limit": 3})
    await call("check_interview_question", {"question": "결혼 계획이 있으신가요?"})
    await call("get_intake_failures")
    if interviews:
        await call("get_web_link", {"screen": "live_interview", "target": interviews[0]["session_id"]})
    if waiting and me:
        await call(
            "propose_interview_booking",
            {
                "applicant": waiting[0]["application_id"],
                "interviewers": [me],
                "start_at": f"{(monday + timedelta(days=1)).isoformat()} 10:00",
            },
        )
    if applicant:
        await call(
            "propose_screening_decision",
            {"applicant": applicant, "decision": "hold", "reason": "도구 점검(scripts/try_mcp.py)"},
        )
    deciding = [d for d in tasks.get("decisions_waiting", []) if d["status"] == "결정 대기"]
    if deciding:
        await call(
            "propose_round_decision",
            {"applicant": deciding[0]["application_id"], "decision": "hold", "reason": "도구 점검(scripts/try_mcp.py)"},
        )


async def main_async(args: argparse.Namespace) -> int:
    out: dict[str, Any] = {}
    if args.stdio:
        env = {"IA_MCP_TOKEN": args.token}
        for key in ("IA_MCP_API_URL", "IA_MCP_WEB_URL", "IA_MCP_AGENT_NAME"):
            if os.environ.get(key):
                env[key] = os.environ[key]
        params = StdioServerParameters(command=sys.executable, args=["-m", "interview_assistant.agent"], env=env)
        async with Client(params) as client:
            await run(client, out)
    else:
        http = httpx2.AsyncClient(headers={"Authorization": f"Bearer {args.token}"}, timeout=60)
        async with http, Client(streamable_http_client(args.url, http_client=http)) as client:
            await run(client, out)
    if args.json:
        Path(args.json).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"answers: {args.json}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--url", default="http://127.0.0.1:8765/mcp")
    parser.add_argument("--stdio", action="store_true", help="start the MCP server over stdio")
    parser.add_argument("--token", default=os.environ.get("IA_MCP_TOKEN", ""), help="agent token (scripts/agent_token.py)")
    parser.add_argument("--json", help="write every answer to this file")
    args = parser.parse_args()
    if not args.token:
        print("--token (or IA_MCP_TOKEN) is required", file=sys.stderr)
        return 1
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
