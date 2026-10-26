"""REST + SSE API under /api (docs/api-contract.md). One router per area of the contract;
`admin` (model settings) is for admins only. `intake` holds the recruiting site's signed endpoints
(docs/site-intake-spec.md) and 관리자 > 연동 현황."""

from fastapi import APIRouter

from interview_assistant.api.routes import (
    admin,
    dashboard,
    evaluation,
    intake,
    live,
    postings,
    schedule,
    screening,
    sessions,
)

router = APIRouter(prefix="/api")
for module in (dashboard, postings, screening, sessions, live, evaluation, schedule, admin, intake):
    router.include_router(module.router)
