import socket
from pathlib import Path

import pytest
from sqlalchemy.pool import StaticPool

from interview_assistant.crypto import FieldCipher
from interview_assistant.db import make_engine, make_session_factory
from interview_assistant.deid import load_deid_config
from interview_assistant.models import Base

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)


@pytest.fixture(scope="session")
def deid_config():
    return load_deid_config(ROOT / "config" / "deid.yaml")


@pytest.fixture
def cipher():
    return FieldCipher(FieldCipher.generate_key())


@pytest.fixture
def db_factory():
    """Session factory on a fresh in-memory SQLite database with every table created."""
    engine = make_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield make_session_factory(engine)
    engine.dispose()
