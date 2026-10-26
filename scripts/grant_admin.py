"""Give (or take back) the admin flag that opens 관리자 > 모델 설정, until SSO sets it.

    uv run python scripts/grant_admin.py E24017
    uv run python scripts/grant_admin.py E24017 --revoke

Uses IA_DATABASE_URL like the app. The demo seed already makes 김서연 (E24017) an admin; this is for
databases migrated from before Alembic 0004, where nobody is.
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import select

from interview_assistant.config import Settings
from interview_assistant.models import ActorType, AuditLog, Interviewer
from interview_assistant.runtime import default_session_factory


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("employee_no")
    parser.add_argument("--revoke", action="store_true")
    args = parser.parse_args()

    with default_session_factory(Settings())() as db:
        person = db.scalar(select(Interviewer).where(Interviewer.employee_no == args.employee_no))
        if person is None:
            print(f"no interviewer with employee number {args.employee_no}", file=sys.stderr)
            return 1
        person.is_admin = not args.revoke
        db.add(
            AuditLog(
                actor_type=ActorType.system,
                action="interviewer.admin_revoked" if args.revoke else "interviewer.admin_granted",
                target_type="interviewer",
                target_id=person.id,
                details={"via": "scripts/grant_admin.py"},
            )
        )
        db.commit()
        print(f"{person.name} ({person.employee_no}): admin = {person.is_admin}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
