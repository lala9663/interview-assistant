"""What a running app holds: the AI model manager (providers per role, switchable from the admin
screen), the database, de-identification, the live transcript hub and the background tasks."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from interview_assistant.ai.gateway import AiGateway
from interview_assistant.ai_models.manager import ModelManager, Providers, ProviderSet
from interview_assistant.config import Settings, load_providers
from interview_assistant.db import make_engine, make_session_factory
from interview_assistant.deid.service import DeidService
from interview_assistant.live.audio import AudioSource, ScriptedCandidate
from interview_assistant.live.hub import LiveHub
from interview_assistant.models import InterviewSession
from interview_assistant.providers import registry

__all__ = ["Providers", "Runtime", "build_providers", "build_runtime"]


def build_providers(settings: Settings) -> Providers:
    """Providers straight from the YAML, without the database (scripts, tests)."""
    cfg = load_providers(settings.providers_file)
    context = {"weights_dir": settings.weights_dir}
    return Providers(
        llm={role: registry.resolve("llm", spec, context) for role, spec in cfg.llm.items()},
        stt={role: registry.resolve("stt", spec, context) for role, spec in cfg.stt.items()},
        embedding=registry.resolve("embedding", cfg.embedding, context),
        diarization=registry.resolve("diarization", cfg.diarization, context),
    )


def default_session_factory(settings: Settings) -> sessionmaker[Session]:
    kwargs: dict[str, Any] = {}
    if settings.database_url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
    return make_session_factory(make_engine(settings.database_url, **kwargs))


@dataclass
class Runtime:
    settings: Settings
    models: ModelManager
    session_factory: sessionmaker[Session]
    deid: DeidService
    hub: LiveHub
    tasks: set[asyncio.Task[Any]] = field(default_factory=set)

    @property
    def providers(self) -> Providers:
        """The active providers (new work); a session in progress keeps its own, see `pinned`."""
        return self.models.active.providers

    @property
    def ai(self) -> AiGateway:
        """The AI gateway on the active providers, for work outside interview sessions."""
        return self.models.active.ai

    def pinned(self, session: InterviewSession) -> ProviderSet:
        """The providers an interview session uses from start to AI scoring."""
        return self.models.for_session(session)

    def spawn(
        self, coro: Coroutine[Any, Any, Any], *, then: Callable[[], None] | None = None
    ) -> asyncio.Task[Any]:
        """Run work after the response (AI scoring); kept here so it is not garbage-collected."""
        task = asyncio.create_task(coro)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        if then is not None:
            task.add_done_callback(lambda _: then())
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
    """`providers` stand in for the instances the stored (or YAML) config would build, so tests
    can run the fakes without latency; changes from the admin API still build real ones."""
    session_factory = session_factory or default_session_factory(settings)
    deid = DeidService.from_settings(settings)
    models = ModelManager(settings, session_factory, preset=providers)
    models.start()
    hub = LiveHub(
        session_factory,
        lambda session: models.for_session(session).get("stt.streaming"),
        deid,
        audio or ScriptedCandidate(speed=settings.demo_speed),
    )
    return Runtime(
        settings=settings,
        models=models,
        session_factory=session_factory,
        deid=deid,
        hub=hub,
    )
