"""REST + SSE API under /api (docs/api-contract.md). One router per area of the contract."""

from fastapi import APIRouter

from interview_assistant.api.routes import (
    dashboard,
    evaluation,
    live,
    postings,
    schedule,
    screening,
    sessions,
)

router = APIRouter(prefix="/api")
for module in (dashboard, postings, screening, sessions, live, evaluation, schedule):
    router.include_router(module.router)
