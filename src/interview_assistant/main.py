"""FastAPI entry point. Providers are resolved once at startup from the configured YAML."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass

from fastapi import FastAPI

from interview_assistant import __version__
from interview_assistant.config import Settings, load_providers
from interview_assistant.providers import registry
from interview_assistant.providers.base import (
    DiarizationProvider,
    EmbeddingProvider,
    LLMProvider,
    STTProvider,
)


@dataclass
class Providers:
    llm: dict[str, LLMProvider]
    stt: dict[str, STTProvider]
    embedding: EmbeddingProvider
    diarization: DiarizationProvider


def build_providers(settings: Settings) -> Providers:
    cfg = load_providers(settings.providers_file)
    return Providers(
        llm={role: registry.resolve("llm", spec) for role, spec in cfg.llm.items()},
        stt={role: registry.resolve("stt", spec) for role, spec in cfg.stt.items()},
        embedding=registry.resolve("embedding", cfg.embedding),
        diarization=registry.resolve("diarization", cfg.diarization),
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings
        app.state.providers = build_providers(settings)
        yield

    app = FastAPI(title="interview-assistant", version=__version__, lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict:
        p: Providers = app.state.providers
        return {
            "status": "ok",
            "version": __version__,
            "providers": {
                "llm": {role: type(x).__name__ for role, x in p.llm.items()},
                "stt": {role: type(x).__name__ for role, x in p.stt.items()},
                "embedding": type(p.embedding).__name__,
                "diarization": type(p.diarization).__name__,
            },
        }

    return app


app = create_app()
