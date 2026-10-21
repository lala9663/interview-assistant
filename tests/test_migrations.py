"""The Alembic migration chain must build exactly the schema the models describe."""

from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import inspect

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
