"""REST + SSE API under /api (docs/api-contract.md). One router per area of the contract;
`admin` (model settings) and `retrieval_admin` (embedding index, follow-up metrics) are for admins
only; `bank` holds the question bank and rubric examples. `intake` holds the recruiting site's signed endpoints
(docs/site-intake-spec.md) and 관리자 > 연동 현황. `agent` records what agents propose; every
route runs behind `agent_guard`, which lets agent calls read only (docs/agent-integration.md)."""

from fastapi import APIRouter, Depends

from interview_assistant.api.agent_access import agent_guard
from interview_assistant.api.routes import (
    admin,
    agent,
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

router = APIRouter(prefix="/api", dependencies=[Depends(agent_guard)])
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
    agent,
):
    router.include_router(module.router)
