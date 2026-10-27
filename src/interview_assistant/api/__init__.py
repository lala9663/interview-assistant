"""REST + SSE API under /api (docs/api-contract.md). One router per area of the contract;
`admin` (model settings) and `retrieval_admin` (embedding index, follow-up metrics) are for admins
only; `bank` holds the question bank and rubric examples. `intake` holds the recruiting site's signed endpoints
(docs/site-intake-spec.md) and 관리자 > 연동 현황."""

from fastapi import APIRouter

from interview_assistant.api.routes import (
    admin,
    bank,
    dashboard,
    evaluation,
    intake,
    live,
    postings,
    retrieval_admin,
    rounds,
    schedule,
    screening,
    sessions,
)

router = APIRouter(prefix="/api")
for module in (
    dashboard,
    postings,
    rounds,
    screening,
    sessions,
    live,
    evaluation,
    schedule,
    bank,
    admin,
    retrieval_admin,
    intake,
):
    router.include_router(module.router)
