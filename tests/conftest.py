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


_LOOPBACK = {"127.0.0.1", "::1", "localhost"}


@pytest.fixture
def no_external_network(monkeypatch):
    """Like `no_network`, but lets loopback through: on Windows every asyncio event loop opens a
    127.0.0.1 socket pair for itself, so API tests could not start one otherwise."""
    real_connect = socket.socket.connect

    def connect(sock, address):
        host = address[0] if isinstance(address, tuple) else address
        if host not in _LOOPBACK:
            raise AssertionError(f"network access attempted: {host}")
        return real_connect(sock, address)

    def refuse(*args, **kwargs):
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)


# --- API -----------------------------------------------------------------------------------


def api_settings(db_path: Path, key: str, tmp_path: Path, **overrides):
    from interview_assistant.config import Settings

    values = dict(
        database_url=f"sqlite+pysqlite:///{db_path.as_posix()}",
        encryption_key=key,
        providers_file=ROOT / "config" / "providers.fake.yaml",
        deid_file=ROOT / "config" / "deid.yaml",
        uploads_dir=tmp_path / "uploads",
        recordings_dir=tmp_path / "recordings",
        dev_interviewer=None,
        demo_speed=0,
    )
    values.update(overrides)
    return Settings(**values)


def instant_providers():
    """The fake providers with no simulated latency."""
    from interview_assistant.providers.fake import (
        FakeDiarization,
        FakeEmbedding,
        FakeLLM,
        FakeSTT,
    )
    from interview_assistant.runtime import Providers

    return Providers(
        llm={"primary": FakeLLM(), "screening": FakeLLM(model="fake-llm-screening")},
        stt={"streaming": FakeSTT(), "batch": FakeSTT()},
        embedding=FakeEmbedding(),
        diarization=FakeDiarization(),
    )


def file_session_factory(db_path: Path):
    engine = make_engine(
        f"sqlite+pysqlite:///{db_path.as_posix()}", connect_args={"check_same_thread": False}
    )
    return make_session_factory(engine)


@pytest.fixture(scope="session")
def seeded_db(tmp_path_factory):
    """The demo dataset seeded once into a file; each API test gets its own copy."""
    from interview_assistant.deid.service import DeidService
    from interview_assistant.demo.seed import seed

    folder = tmp_path_factory.mktemp("seed")
    path = folder / "seed.db"
    key = FieldCipher.generate_key()
    factory = file_session_factory(path)
    Base.metadata.create_all(factory.kw["bind"])
    settings = api_settings(path, key, folder)
    with factory() as db:
        seed(db, DeidService.from_settings(settings), settings)
    factory.kw["bind"].dispose()
    return path, key


@pytest.fixture
def api(seeded_db, tmp_path, no_external_network):
    """TestClient on a seeded copy of the demo database, fake providers without latency.
    `api.runtime` is the app's runtime (session factory, hub, AI gateway)."""
    import shutil

    from fastapi.testclient import TestClient

    from interview_assistant.main import create_app

    template, key = seeded_db
    path = tmp_path / "api.db"
    shutil.copyfile(template, path)
    factory = file_session_factory(path)
    app = create_app(
        api_settings(path, key, tmp_path), providers=instant_providers(), session_factory=factory
    )
    with TestClient(app) as client:
        client.runtime = app.state.runtime
        yield client
    factory.kw["bind"].dispose()
