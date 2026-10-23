"""Fill the database with the demo dataset (the frontend mock's fictional data).

    uv run alembic upgrade head
    uv run python scripts/seed_demo.py --reset

Times are laid out relative to now (an interview in progress, today's schedule ...), so seed again
with --reset on another day. Needs IA_ENCRYPTION_KEY: fictional identities are sealed like real
ones. Uses IA_DATABASE_URL like the app.
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import func, select

from interview_assistant.config import Settings
from interview_assistant.crypto import MissingEncryptionKey
from interview_assistant.deid.service import DeidService
from interview_assistant.demo.seed import clear, seed
from interview_assistant.models import Candidate
from interview_assistant.runtime import default_session_factory


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--reset", action="store_true", help="delete every row first")
    args = parser.parse_args()

    settings = Settings()
    deid = DeidService.from_settings(settings)
    if deid.cipher is None:
        print(
            "IA_ENCRYPTION_KEY is not set. Generate one and put it in .env:\n"
            '  uv run python -c "from interview_assistant.crypto import FieldCipher as F; '
            'print(F.generate_key())"',
            file=sys.stderr,
        )
        return 2
    with default_session_factory(settings)() as db:
        if db.scalar(select(func.count()).select_from(Candidate)):
            if not args.reset:
                print(
                    "The database already has data. Run with --reset to replace it.",
                    file=sys.stderr,
                )
                return 1
            clear(db)
        result = seed(db, deid, settings)
    print(f"seeded {settings.database_url}: {result}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except MissingEncryptionKey as exc:
        print(exc, file=sys.stderr)
        sys.exit(2)
