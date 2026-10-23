from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from interview_assistant.config import ProviderSpec, Settings, load_providers
from interview_assistant.main import create_app
from interview_assistant.providers import registry

ROOT = Path(__file__).resolve().parents[1]
FAKE = ROOT / "config" / "providers.fake.yaml"
GCP = ROOT / "config" / "providers.yaml"


def test_fake_config_loads():
    cfg = load_providers(FAKE)
    assert set(cfg.llm) == {"primary", "screening"}
    assert set(cfg.stt) == {"streaming", "batch"}
    assert cfg.embedding.options == {"dimensions": 8}


def test_gcp_config_only_names_registered_impls():
    cfg = load_providers(GCP)
    pairs = [
        *(("llm", s) for s in cfg.llm.values()),
        *(("stt", s) for s in cfg.stt.values()),
        ("embedding", cfg.embedding),
        ("diarization", cfg.diarization),
    ]
    for kind, spec in pairs:
        assert registry.is_registered(kind, spec.impl), (kind, spec.impl)


def test_unknown_impl_raises():
    with pytest.raises(registry.UnknownProviderError):
        registry.resolve("llm", ProviderSpec(impl="nope"))


def test_registered_but_unimplemented_impl_raises_clear_error():
    cfg = load_providers(GCP)
    with pytest.raises(registry.UnknownProviderError, match="not implemented"):
        registry.resolve("llm", cfg.llm["primary"])


async def test_fake_llm_generate_and_stream():
    cfg = load_providers(FAKE)
    llm = registry.resolve("llm", cfg.llm["primary"])
    result = await llm.generate("sys", "hello", schema={"properties": {"score": {}}})
    assert result.structured == {"score": None}
    chunks = [c async for c in llm.stream("sys", "hello")]
    assert "".join(chunks).strip() == result.text


async def test_fake_embedding_is_unit_norm():
    cfg = load_providers(FAKE)
    emb = registry.resolve("embedding", cfg.embedding)
    [vec] = await emb.embed(["hello"])
    assert len(vec) == 8
    assert abs(sum(v * v for v in vec) - 1.0) < 1e-6


def test_health_reports_fake_providers():
    app = create_app(Settings(providers_file=FAKE, database_url="sqlite+pysqlite:///:memory:"))
    with TestClient(app) as client:
        body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["providers"]["llm"]["primary"] == "FakeLLM"
    assert body["providers"]["stt"]["batch"] == "FakeSTT"
