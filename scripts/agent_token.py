"""Issue a development token for agent calls (the MCP server), until SSO replaces it.

    uv run python scripts/agent_token.py E24017
    uv run python scripts/agent_token.py E24031 --hours 8

The token names one interviewer: an agent that forwards it can read what that person can read in
the web screen, and nothing more. It cannot change anything (docs/agent-integration.md). Signed
with IA_AGENT_TOKEN_SECRET; rotating that key invalidates every token issued before. Uses
IA_DATABASE_URL like the app to check that the interviewer exists, and writes an audit row.
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import select

from interview_assistant.api.agent_access import MAX_HOURS, issue_token
from interview_assistant.config import Settings
from interview_assistant.models import ActorType, AuditLog, Interviewer
from interview_assistant.runtime import default_session_factory


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("employee_no")
    parser.add_argument("--hours", type=float, default=24 * 7, help=f"valid for (max {MAX_HOURS})")
    args = parser.parse_args()

    settings = Settings()
    secret = settings.agent_token_secret.get_secret_value() if settings.agent_token_secret else ""
    if not secret:
        print("IA_AGENT_TOKEN_SECRET is not set (.env)", file=sys.stderr)
        return 1
    if not 0 < args.hours <= MAX_HOURS:
        print(f"--hours must be in (0, {MAX_HOURS}]", file=sys.stderr)
        return 1
    with default_session_factory(settings)() as db:
        person = db.scalar(select(Interviewer).where(Interviewer.employee_no == args.employee_no))
        if person is None:
            print(f"no interviewer with employee number {args.employee_no}", file=sys.stderr)
            return 1
        db.add(
            AuditLog(
                actor_type=ActorType.system,
                action="agent.token_issued",
                target_type="interviewer",
                target_id=person.id,
                details={"hours": args.hours, "via": "scripts/agent_token.py"},
            )
        )
        db.commit()
        print(f"# {person.name} ({person.employee_no}), {args.hours:g} hours", file=sys.stderr)
    print(issue_token(secret, args.employee_no, hours=args.hours))
    return 0


if __name__ == "__main__":
    sys.exit(main())
