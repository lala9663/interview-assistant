"""The Alembic migration chain must build exactly the schema the models describe."""

from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

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


def test_0006_puts_existing_postings_sets_and_sessions_in_round_one(tmp_path):
    config, url = _config(tmp_path)
    command.upgrade(config, "0005")
    engine = make_engine(url)
    now = "2026-10-26 09:00:00.000000"
    rows = [
        f"INSERT INTO job_postings (id, title, job_family, jd_text, status, created_at) VALUES ('p1', 'T', 'SW', 'JD', 'open', '{now}')",
        f"INSERT INTO job_postings (id, title, job_family, jd_text, status, created_at) VALUES ('p2', 'U', 'SW', 'JD', 'draft', '{now}')",
        f"INSERT INTO competency_sets (id, posting_id, version, competencies, approved_at, created_at) VALUES ('cs1', 'p1', 1, '[]', '{now}', '{now}')",
        f"INSERT INTO competency_sets (id, posting_id, version, competencies, created_at) VALUES ('cs2', 'p1', 2, '[]', '{now}')",
        f"INSERT INTO preset_questions (id, competency_set_id, position, competency, question, intent, created_at) VALUES ('pq1', 'cs1', 1, 'c', 'Q?', '', '{now}')",
        f"INSERT INTO candidates (id, pseudonym, consent_recording, created_at) VALUES ('c1', 'CAND-1', 0, '{now}')",
        f"INSERT INTO candidates (id, pseudonym, consent_recording, created_at) VALUES ('c2', 'CAND-2', 0, '{now}')",
        f"INSERT INTO applications (id, candidate_id, posting_id, channel, created_at) VALUES ('a1', 'c1', 'p1', 'upload', '{now}')",
        f"INSERT INTO applications (id, candidate_id, posting_id, channel, created_at) VALUES ('a2', 'c2', 'p1', 'upload', '{now}')",
        f"INSERT INTO interview_sessions (id, application_id, mode, status, ai_scoring_status, competency_set_id, created_at) VALUES ('s1', 'a1', 'remote', 'completed', 'completed', 'cs1', '{now}')",
        f"INSERT INTO interview_sessions (id, application_id, mode, status, ai_scoring_status, created_at) VALUES ('s2', 'a2', 'onsite', 'scheduled', 'not_started', '{now}')",
        f"INSERT INTO qa_items (id, session_id, seq, question, question_source, preset_question_id, created_at) VALUES ('q1', 's1', 1, 'Q?', 'preset', 'pq1', '{now}')",
    ]
    try:
        with engine.begin() as conn:
            for sql in rows:
                conn.execute(text(sql))
        command.upgrade(config, "head")
        with engine.connect() as conn:
            rounds = conn.execute(
                text("SELECT posting_id, id, position, name, default_mode, show_previous_scores FROM interview_rounds")
            ).all()
            assert sorted((r[0], r[2], r[3], r[4], r[5]) for r in rounds) == [
                ("p1", 1, "면접", "remote", 0),
                ("p2", 1, "면접", "remote", 0),
            ]
            first = {r[0]: r[1] for r in rounds}
            sets = dict(conn.execute(text("SELECT id, round_id FROM competency_sets")).all())
            assert sets == {"cs1": first["p1"], "cs2": first["p1"]}
            sessions = {
                r[0]: (r[1], r[2])
                for r in conn.execute(text("SELECT id, round_id, active_round_id FROM interview_sessions"))
            }
            # Only the open (scheduled) session holds its round open.
            assert sessions == {"s1": (first["p1"], None), "s2": (first["p1"], first["p1"])}
            assert conn.execute(text("SELECT competency_set_id, session_id FROM preset_questions")).one() == ("cs1", None)
            assert conn.execute(text("SELECT preset_question_id FROM qa_items")).scalar() == "pq1"
        # A second open session of the same round is refused by the database too.
        with pytest.raises(IntegrityError), engine.begin() as conn:
            conn.execute(text(f"INSERT INTO interview_sessions (id, application_id, mode, status, ai_scoring_status, round_id, active_round_id, created_at) VALUES ('s3', 'a2', 'remote', 'scheduled', 'not_started', '{first['p1']}', '{first['p1']}', '{now}')"))

        # A later round with its own set and a carry-over question disappears on downgrade.
        with engine.begin() as conn:
            conn.execute(text(f"INSERT INTO interview_rounds (id, posting_id, position, name, default_mode, recommended_interviewers, show_previous_scores, created_at) VALUES ('r2', 'p1', 2, '임원 면접', 'onsite', 3, 0, '{now}')"))
            conn.execute(text(f"INSERT INTO competency_sets (id, posting_id, round_id, version, competencies, created_at) VALUES ('cs3', 'p1', 'r2', 1, '[]', '{now}')"))
            conn.execute(text(f"INSERT INTO preset_questions (id, competency_set_id, position, competency, question, intent, created_at) VALUES ('pq2', 'cs3', 1, 'c', 'Q2?', '', '{now}')"))
            conn.execute(text(f"INSERT INTO preset_questions (id, session_id, position, competency, question, intent, created_at) VALUES ('pq3', 's2', 1, 'c', 'Q3?', '', '{now}')"))
        command.downgrade(config, "0005")
        with engine.connect() as conn:
            assert sorted(conn.execute(text("SELECT id FROM competency_sets")).scalars()) == ["cs1", "cs2"]
            assert conn.execute(text("SELECT id FROM preset_questions")).scalars().all() == ["pq1"]
            assert sorted(conn.execute(text("SELECT id FROM interview_sessions")).scalars()) == ["s1", "s2"]
            assert conn.execute(text("SELECT preset_question_id FROM qa_items")).scalar() == "pq1"
    finally:
        engine.dispose()
