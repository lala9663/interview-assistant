"""Streaming (docs/api-contract.md 3장): the live transcript and follow-up suggestions over SSE."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from interview_assistant.ai.followups import follow_up_events
from interview_assistant.api import schemas as s
from interview_assistant.api import views
from interview_assistant.api.deps import Db, RuntimeDep
from interview_assistant.api.routes.sessions import get_session
from interview_assistant.models import TranscriptSegment

router = APIRouter(tags=["live"])

SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


def sse(events: AsyncIterator[tuple[str, dict[str, Any]]]) -> StreamingResponse:
    async def body() -> AsyncIterator[str]:
        try:
            async for name, data in events:
                yield f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
        finally:
            await events.aclose()  # type: ignore[attr-defined]

    return StreamingResponse(body(), media_type="text/event-stream", headers=SSE_HEADERS)


@router.get("/sessions/{session_id}/transcript", response_model=s.TranscriptHistory)
def transcript(session_id: str, db: Db) -> s.TranscriptHistory:
    get_session(db, session_id)
    rows = db.scalars(
        select(TranscriptSegment)
        .where(TranscriptSegment.session_id == session_id)
        .order_by(TranscriptSegment.start_ms, TranscriptSegment.created_at)
    ).all()
    return views.transcript(rows)


@router.get("/sessions/{session_id}/transcript/stream")
def transcript_stream(session_id: str, db: Db, runtime: RuntimeDep) -> StreamingResponse:
    get_session(db, session_id)
    return sse(runtime.hub.events(session_id))


@router.post("/sessions/{session_id}/follow-ups")
def follow_ups(
    session_id: str, body: s.FollowUpRequest, db: Db, runtime: RuntimeDep
) -> StreamingResponse:
    get_session(db, session_id)
    return sse(
        follow_up_events(
            runtime.session_factory,
            runtime.ai,
            runtime.deid,
            session_id=session_id,
            qa_item_id=body.qa_item_id,
        )
    )
