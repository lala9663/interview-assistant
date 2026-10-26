"""FastAPI entry point.

    uv run uvicorn interview_assistant.main:app --reload

The API lives under /api (interview_assistant.api); /health reports the active providers. Which
provider serves each AI role is stored in the database and switched from the admin screen without
a restart; the providers YAML only seeds the first start (ai_models/).
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from interview_assistant import __version__
from interview_assistant.ai.scoring import score_session
from interview_assistant.api import errors
from interview_assistant.api import router as api_router
from interview_assistant.config import Settings
from interview_assistant.live.audio import AudioSource
from interview_assistant.models import AiScoringStatus, InterviewSession
from interview_assistant.runtime import (
    Providers,
    Runtime,
    build_providers,
    build_runtime,
)

__all__ = ["Providers", "build_providers", "create_app"]

log = logging.getLogger(__name__)


def _resume_scoring(runtime: Runtime) -> None:
    """AI scoring that was running when the server stopped starts again, on the providers the
    session pinned."""
    with runtime.session_factory() as db:
        ids = db.scalars(
            select(InterviewSession.id).where(
                InterviewSession.ai_scoring_status == AiScoringStatus.running
            )
        ).all()
    for session_id in ids:
        with runtime.session_factory() as db:
            session = db.get(InterviewSession, session_id)
            if session is None:
                continue
            providers = runtime.pinned(session)
            session.ai_config_revision = providers.revision
            db.commit()
        runtime.spawn(
            score_session(runtime.session_factory, providers.ai, runtime.deid, session_id),
            then=runtime.models.evict,
        )


def create_app(
    settings: Settings | None = None,
    *,
    providers: Providers | None = None,
    session_factory: sessionmaker[Session] | None = None,
    audio: AudioSource | None = None,
) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        runtime = build_runtime(
            settings, providers=providers, session_factory=session_factory, audio=audio
        )
        app.state.settings = settings
        app.state.runtime = runtime
        if runtime.deid.cipher is None:
            log.warning("IA_ENCRYPTION_KEY is not set: uploads and free-text writes will fail (503)")
        try:
            _resume_scoring(runtime)
        except Exception:  # an empty or unmigrated database must not stop the server
            log.exception("could not resume AI scoring")
        try:
            for worker in runtime.intake.start():  # site events still queued are applied again
                runtime.tasks.add(worker)
        except Exception:
            log.exception("could not start the intake queue")
        runtime.spawn(runtime.models.warm_up_active())
        yield
        for task in list(runtime.tasks):
            task.cancel()
        await asyncio.gather(*runtime.tasks, return_exceptions=True)

    app = FastAPI(title="interview-assistant", version=__version__, lifespan=lifespan)
    errors.install(app)
    app.include_router(api_router)

    @app.get("/health")
    async def health() -> dict:
        runtime: Runtime = app.state.runtime
        p = runtime.providers
        return {
            "status": "ok",
            "version": __version__,
            "ai_config_revision": runtime.models.active.revision,
            "providers": {
                "llm": {role: type(x).__name__ for role, x in p.llm.items()},
                "stt": {role: type(x).__name__ for role, x in p.stt.items()},
                "embedding": type(p.embedding).__name__,
                "diarization": type(p.diarization).__name__,
            },
        }

    return app


app = create_app()
