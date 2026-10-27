"""관리자: the embedding index behind retrieval (what searches use, a rebuild in progress) and the
follow-up metrics that compare question-bank and AI suggestions. Admins only."""

from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import timedelta

from fastapi import APIRouter, Query
from sqlalchemy import select

from interview_assistant.api import schemas as s
from interview_assistant.api.deps import Admin, Db, RuntimeDep, audit
from interview_assistant.models import FollowUpSuggestion, SuggestionSource
from interview_assistant.models.base import utcnow
from interview_assistant.runtime import Runtime

router = APIRouter(prefix="/admin", tags=["admin"])


def index_status(runtime: Runtime) -> s.EmbeddingIndexStatus:
    retrieval = runtime.retrieval
    active = retrieval.active_provider()
    served = retrieval.serving
    counts = (
        {kind: served.index.count(kind) for kind in ("question", "rubric", "competency_set")}
        if served is not None
        else {}
    )
    return s.EmbeddingIndexStatus(
        active_model=str(getattr(active, "model", "")) if active is not None else None,
        active_index_key=active.index_key if active is not None else None,
        serving_index_key=served.key if served is not None else None,
        counts=counts,
        indexes=[
            s.EmbeddingIndexState(
                index_key=i.key,
                model=i.model,
                dimensions=i.dimensions,
                status=i.status,
                total=i.total,
                done=i.done,
                started_at=i.started_at,
                finished_at=i.finished_at,
                error=i.error,
                serving=served is not None and served.key == i.key,
            )
            for i in retrieval.states()
        ],
    )


@router.get("/embedding-index", response_model=s.EmbeddingIndexStatus)
def embedding_index(admin: Admin, runtime: RuntimeDep) -> s.EmbeddingIndexStatus:
    return index_status(runtime)


@router.post("/embedding-index/rebuild", response_model=s.EmbeddingIndexStatus, status_code=202)
async def rebuild_index(db: Db, admin: Admin, runtime: RuntimeDep) -> s.EmbeddingIndexStatus:
    """Embed every approved text again with the embedding role's model (after a failure, or to
    start over). Searches keep the current index until the new one is ready."""
    runtime.retrieval.rebuild()
    active = runtime.retrieval.active_provider()
    audit(db, admin, "embedding.rebuild_requested", "embedding_index", getattr(active, "index_key", None))
    db.commit()
    return index_status(runtime)


def _percentile(values: list[int], q: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(q * (len(ordered) - 1)))]


@router.get("/follow-up-metrics", response_model=s.FollowUpMetrics)
def follow_up_metrics(
    db: Db, admin: Admin, runtime: RuntimeDep, days: int = Query(30, ge=1, le=365)
) -> s.FollowUpMetrics:
    """Per source: how many suggestions were shown and used, and how long the first card of each
    source took per batch; how many candidates were dropped as already asked."""
    since = utcnow() - timedelta(days=days)
    rows = db.scalars(select(FollowUpSuggestion).where(FollowUpSuggestion.created_at >= since)).all()
    batches = {r.batch_id for r in rows}
    sources = []
    for source in (SuggestionSource.bank, SuggestionSource.ai):
        mine = [r for r in rows if r.source is source]
        shown = [r for r in mine if r.discarded is None]
        used = [r for r in shown if r.used_qa_item_id is not None]
        first: dict[str, int] = {}
        for r in shown:
            if r.latency_ms is not None:
                first[r.batch_id] = min(first.get(r.batch_id, r.latency_ms), r.latency_ms)
        timings = list(first.values())
        sources.append(
            s.SourceMetrics(
                source=source.value,
                shown=len(shown),
                used=len(used),
                edited=sum(1 for r in used if r.edited),
                adoption_rate=round(len(used) / len(shown), 3) if shown else None,
                batches=len({r.batch_id for r in shown}),
                first_ms_median=round(statistics.median(timings)) if timings else None,
                first_ms_p90=_percentile(timings, 0.9),
            )
        )
    duplicates: dict[str, int] = defaultdict(int)
    for r in rows:
        if r.discarded == "duplicate":
            duplicates[r.source.value] += 1
    return s.FollowUpMetrics(
        since=since,
        days=days,
        batches=len(batches),
        sources=sources,
        duplicates={
            "bank": duplicates["bank"],
            "ai": duplicates["ai"],
            "total": duplicates["bank"] + duplicates["ai"],
        },
        retrieval_model=runtime.retrieval.model,
    )
