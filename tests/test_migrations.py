"""The Alembic migration chain must build exactly the schema the models describe."""

from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import inspect, text

from interview_assistant.db import make_engine
from interview_assistant.models import Base

ROOT = Path(__file__).resolve().parents[1]


def _config(tmp_path: Path) -> tuple[Config, str]:
    url = f"sqlite+pysqlite:///{(tmp_path / 'migrations.db').as_posix()}"
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    return config, url


def test_upgrade_matches_models_and_downgrade_is_clean(tmp_path):
    config, url = _config(tmp_path)

    command.upgrade(config, "head")
    engine = make_engine(url)
    try:
        with engine.connect() as conn:
            tables = set(inspect(conn).get_table_names())
            assert set(Base.metadata.tables) <= tables
            context = MigrationContext.configure(conn, opts={"compare_type": True})
            assert compare_metadata(context, Base.metadata) == []

        command.downgrade(config, "base")
        with engine.connect() as conn:
            assert set(inspect(conn).get_table_names()) <= {"alembic_version"}
    finally:
        engine.dispose()


def test_0003_moves_scores_onto_the_session_and_marks_scored_sessions(tmp_path):
    config, url = _config(tmp_path)
    command.upgrade(config, "0002")
    engine = make_engine(url)
    now = "2026-10-21 09:00:00.000000"
    rows = [
        f"INSERT INTO job_postings VALUES ('T', 'SW', 'JD', 'open', 'p1', '{now}')",
        f"INSERT INTO candidates VALUES ('CAND-1', NULL, 0, NULL, NULL, 'c1', '{now}')",
        f"INSERT INTO applications VALUES ('c1', 'p1', NULL, NULL, NULL, 'a1', '{now}')",
        f"INSERT INTO interview_sessions VALUES ('a1', 'remote', 'completed', NULL, NULL, NULL, NULL, 's1', '{now}')",
        f"INSERT INTO interview_sessions VALUES ('a1', 'remote', 'scheduled', NULL, NULL, NULL, NULL, 's2', '{now}')",
        f"INSERT INTO qa_items VALUES ('s1', 1, 'Q', 'preset', 'A', 'A', NULL, NULL, 'q1', '{now}')",
        f"INSERT INTO scores VALUES ('q1', 'c', 4, 'A', 0.8, 'ai', NULL, 'm', 'v', 'x1', '{now}')",
        f"INSERT INTO scores VALUES ('q1', 'c', 3, NULL, NULL, 'interviewer', 'i1', NULL, NULL, 'x2', '{now}')",
    ]
    try:
        with engine.begin() as conn:
            for sql in rows:
                conn.execute(text(sql))
        command.upgrade(config, "head")
        with engine.connect() as conn:
            assert conn.execute(text("SELECT DISTINCT session_id FROM scores")).scalars().all() == ["s1"]
            status = dict(conn.execute(text("SELECT id, ai_scoring_status FROM interview_sessions")).all())
            assert status == {"s1": "completed", "s2": "not_started"}
        command.downgrade(config, "0002")
        with engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM scores")).scalar() == 2
    finally:
        engine.dispose()
