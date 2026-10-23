"""Every LLM call of the app goes through here: guard, provider, audit log.

The provider comes from config/providers.yaml by role (`primary`, `screening`); business code
never names an implementation, so switching to a real model is a config change. Each call writes
one AuditLog row (actor ai, model, prompt version, token counts when the provider reports them)
whether it succeeds, fails or is refused by the guard. Prompts and responses are not logged.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from interview_assistant.ai.guard import IdentifierInPrompt, check_prompt
from interview_assistant.deid.types import KnownIdentity
from interview_assistant.models import ActorType, AuditLog
from interview_assistant.providers.base import LLMProvider, LLMResult


@dataclass
class AiCall:
    action: str  # audit action, e.g. "followup.generated"
    prompt_version: str
    system: str
    prompt: str
    role: str = "primary"
    schema: dict[str, Any] | None = None
    max_tokens: int = 4000
    # Candidate-derived inputs placed in the prompt (de-identified) and the candidate's identity,
    # for the guard. Empty for prompts without candidate data (e.g. a JD-only task).
    candidate_texts: Sequence[str] = ()
    known: KnownIdentity | None = None
    target_type: str | None = None
    target_id: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


def model_name(llm: LLMProvider) -> str:
    return str(getattr(llm, "model", None) or type(llm).__name__)


class AiGateway:
    def __init__(self, llms: dict[str, LLMProvider]) -> None:
        self.llms = llms

    def llm(self, role: str) -> LLMProvider:
        return self.llms.get(role) or self.llms["primary"]

    def _audit(self, db: Session, call: AiCall, model: str, **extra: Any) -> None:
        tokens = {k: extra.pop(k) for k in ("input_tokens", "output_tokens") if k in extra}
        db.add(
            AuditLog(
                actor_type=ActorType.ai,
                action=call.action,
                target_type=call.target_type,
                target_id=call.target_id,
                model=model,
                prompt_version=call.prompt_version,
                details={**call.details, **extra} or None,
                **tokens,
            )
        )
        db.flush()

    def _guard(self, db: Session, call: AiCall, model: str) -> None:
        try:
            check_prompt(call.prompt, call.candidate_texts, call.known)
        except IdentifierInPrompt as exc:
            self._audit(db, call, model, refused=list(exc.kinds))
            raise

    async def generate(self, db: Session, call: AiCall) -> LLMResult:
        llm = self.llm(call.role)
        self._guard(db, call, model_name(llm))
        try:
            result = await llm.generate(
                call.system, call.prompt, schema=call.schema, max_tokens=call.max_tokens
            )
        except Exception as exc:
            self._audit(db, call, model_name(llm), error=type(exc).__name__)
            raise
        self._audit(
            db,
            call,
            result.model,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
        )
        return result

    def stream(self, db: Session, call: AiCall) -> tuple[str, AsyncIterator[str]]:
        """Guard and audit now, then hand back the model name and the provider's text stream.
        Token counts are not reported by streaming providers yet."""
        llm = self.llm(call.role)
        model = model_name(llm)
        self._guard(db, call, model)
        self._audit(db, call, model)
        return model, llm.stream(call.system, call.prompt, max_tokens=call.max_tokens)
