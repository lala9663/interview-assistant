"""What a running app holds: providers from the YAML, the database, de-identification, the AI
gateway, the live transcript hub and the background tasks (AI scoring)."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from interview_assistant.ai.gateway import AiGateway
from interview_assistant.config import Settings, load_providers
from interview_assistant.db import make_engine, make_session_factory
from interview_assistant.deid.service import DeidService
from interview_assistant.live.audio import AudioSource, ScriptedCandidate
from interview_assistant.live.hub import LiveHub
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


def default_session_factory(settings: Settings) -> sessionmaker[Session]:
    kwargs: dict[str, Any] = {}
    if settings.database_url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
    return make_session_factory(make_engine(settings.database_url, **kwargs))


@dataclass
class Runtime:
    settings: Settings
    providers: Providers
    session_factory: sessionmaker[Session]
    deid: DeidService
    ai: AiGateway
    hub: LiveHub
    tasks: set[asyncio.Task[Any]] = field(default_factory=set)

    def spawn(self, coro: Coroutine[Any, Any, Any]) -> asyncio.Task[Any]:
        """Run work after the response (AI scoring); kept here so it is not garbage-collected."""
        task = asyncio.create_task(coro)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    @property
    def uploads_dir(self) -> Path:
        return self.settings.uploads_dir

    @property
    def recordings_dir(self) -> Path:
        return self.settings.recordings_dir


def build_runtime(
    settings: Settings,
    *,
    providers: Providers | None = None,
    session_factory: sessionmaker[Session] | None = None,
    audio: AudioSource | None = None,
) -> Runtime:
    providers = providers or build_providers(settings)
    session_factory = session_factory or default_session_factory(settings)
    deid = DeidService.from_settings(settings)
    stt = providers.stt.get("streaming") or next(iter(providers.stt.values()))
    hub = LiveHub(
        session_factory,
        stt,
        deid,
        audio or ScriptedCandidate(speed=settings.demo_speed),
        language=str(getattr(stt, "language", "ko-KR")),
    )
    return Runtime(
        settings=settings,
        providers=providers,
        session_factory=session_factory,
        deid=deid,
        ai=AiGateway(providers.llm),
        hub=hub,
    )
