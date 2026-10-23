"""FR-06: stream 2-3 follow-up suggestions for one answer (POST /api/sessions/{id}/follow-ups).

The model writes tagged blocks (prompts.FOLLOWUP_FORMAT); `SuggestionParser` turns its token
stream into the SSE events of docs/api-contract.md 3.2 as text arrives, so the question appears
while it is being written. Every finished suggestion is stored (FollowUpSuggestion) whether or not
the interviewer uses it. Suggestions are never turned into questions here.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from interview_assistant.ai.gateway import AiCall, AiGateway
from interview_assistant.ai.guard import IdentifierInPrompt
from interview_assistant.ai.prompts import (
    FOLLOWUP_PROMPT,
    FOLLOWUP_SYSTEM,
    followup_prompt,
)
from interview_assistant.deid.service import DeidService
from interview_assistant.interviews import session_competency_set
from interview_assistant.models import FollowUpSuggestion, QAItem
from interview_assistant.models.base import new_id

MAX_SUGGESTIONS = 3
CONTEXT_ANSWERS = 2  # earlier answers given to the model as context

Event = tuple[str, dict[str, Any]]

_FIELDS = ("competency", "question", "rationale", "grounding")


@dataclass
class ParsedEvent:
    kind: str  # "start" | "delta" | "done"
    fields: dict[str, str] = field(default_factory=dict)
    text: str = ""


class SuggestionParser:
    """Incremental parser for `<suggestion><competency>…</competency><question>…</question>…`.

    Chunks may split tags anywhere. `start` fires once the competency is known (or when the
    question begins without one), `delta` carries question text as soon as it cannot be part of
    the closing tag, `done` carries all four fields.
    """

    def __init__(self) -> None:
        self.buffer = ""
        self.inside = False
        self.current: str | None = None  # field being read
        self.fields: dict[str, str] = {}
        self.started = False

    def feed(self, chunk: str) -> list[ParsedEvent]:
        self.buffer += chunk
        events: list[ParsedEvent] = []
        while True:
            if not self.inside:
                at = self.buffer.find("<suggestion>")
                if at < 0:
                    self.buffer = self.buffer[-len("<suggestion>") :]
                    return events
                self.buffer = self.buffer[at + len("<suggestion>") :]
                self.inside, self.fields, self.started = True, {}, False
            elif self.current is None:
                m = re.search(
                    r"<(/?)(suggestion|competency|question|rationale|grounding)>", self.buffer
                )
                if m is None:
                    return events
                self.buffer = self.buffer[m.end() :]
                if m.group(2) == "suggestion":
                    if m.group(1):
                        if not self.started:
                            events.append(self._start())
                        events.append(ParsedEvent("done", dict(self.fields)))
                        self.inside = False
                    continue
                self.current = m.group(2)
                if self.current == "question" and not self.started:
                    events.append(self._start())
            else:
                closing = f"</{self.current}>"
                end = self.buffer.find(closing)
                if end < 0:
                    safe = len(self.buffer) - _partial_suffix(self.buffer, closing)
                    if self.current == "question" and safe > 0:
                        self._append(self.buffer[:safe], events)
                        self.buffer = self.buffer[safe:]
                    return events
                text, self.buffer = self.buffer[:end], self.buffer[end + len(closing) :]
                if self.current == "question":
                    self._append(text, events)
                else:
                    self.fields[self.current] = self.fields.get(self.current, "") + text
                if self.current == "competency" and not self.started:
                    events.append(self._start())
                self.current = None

    def _start(self) -> ParsedEvent:
        self.started = True
        return ParsedEvent("start", {"competency": self.fields.get("competency", "").strip()})

    def _append(self, text: str, events: list[ParsedEvent]) -> None:
        if text:
            self.fields["question"] = self.fields.get("question", "") + text
            events.append(ParsedEvent("delta", text=text))


def _partial_suffix(text: str, tag: str) -> int:
    """Length of the longest suffix of `text` that is a prefix of `tag`."""
    for n in range(min(len(tag) - 1, len(text)), 0, -1):
        if tag.startswith(text[-n:]):
            return n
    return 0


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def ground(grounding: str, answer: str) -> str:
    """The quote shown under a suggestion must be verbatim from the de-identified answer. If the
    model paraphrased, fall back to the answer sentence that shares the most with its quote."""
    quote = _squash(grounding).strip("\"'“”‘’ ")
    if quote and quote in _squash(answer):
        return quote
    sentences = [s.strip() for s in re.split(r"(?<=[.?!])\s+", answer) if s.strip()]
    if not sentences:
        return ""

    def overlap(sentence: str) -> int:
        grams = {quote[i : i + 2] for i in range(len(quote) - 1)}
        return sum(1 for i in range(len(sentence) - 1) if sentence[i : i + 2] in grams)

    return max(sentences, key=overlap).rstrip(".")


def _pick_competency(name: str, names: Sequence[str], target: str | None) -> str:
    if not names or name in names:
        return name or (target or "")
    return target if target in names else names[0]


async def follow_up_events(
    session_factory: sessionmaker[Session],
    ai: AiGateway,
    deid: DeidService,
    *,
    session_id: str,
    qa_item_id: str,
) -> AsyncIterator[Event]:
    batch_id = new_id()
    with session_factory() as db:
        qa = db.get(QAItem, qa_item_id)
        if qa is None or qa.session_id != session_id:
            yield "error", {"message": "이 면접의 질문이 아닙니다."}
            return
        if not qa.answer_deidentified:
            yield "error", {"message": "답변이 아직 없어 꼬리질문을 만들 수 없습니다."}
            return
        session = qa.session
        competency_set = session_competency_set(db, session)
        competencies = competency_set.competencies if competency_set else []
        names = [c["name"] for c in competencies]
        earlier = [
            (q.question, q.answer_deidentified)
            for q in session.qa_items
            if q.seq < qa.seq and q.answer_deidentified
        ][-CONTEXT_ANSWERS:]
        answer = qa.answer_deidentified
        target = qa.target_competency
        call = AiCall(
            action="followup.generated",
            prompt_version=FOLLOWUP_PROMPT,
            system=FOLLOWUP_SYSTEM,
            prompt=followup_prompt(
                competencies=competencies,
                target_competency=target,
                previous=earlier,
                question=qa.question,
                answer=answer,
            ),
            candidate_texts=[answer, qa.question, *(t for pair in earlier for t in pair)],
            known=deid.identity(session.application.candidate),
            target_type="interview_session",
            target_id=session_id,
            details={"qa_item_id": qa.id, "batch_id": batch_id},
        )
        try:
            model, stream = ai.stream(db, call)
        except IdentifierInPrompt:
            db.commit()
            yield "error", {"message": "답변에 식별 정보가 남아 있어 AI에 보내지 않았습니다."}
            return
        db.commit()

    yield (
        "batch.start",
        {
            "batch_id": batch_id,
            "qa_item_id": qa_item_id,
            "model": model,
            "prompt_version": FOLLOWUP_PROMPT,
        },
    )
    parser = SuggestionParser()
    index = 0
    suggestion_id = ""
    competency = ""
    try:
        async for chunk in stream:
            for event in parser.feed(chunk):
                if index >= MAX_SUGGESTIONS:
                    break
                if event.kind == "start":
                    suggestion_id = new_id()
                    competency = _pick_competency(event.fields["competency"], names, target)
                    yield (
                        "suggestion.start",
                        {
                            "batch_id": batch_id,
                            "suggestion_id": suggestion_id,
                            "index": index,
                            "competency": competency,
                        },
                    )
                elif event.kind == "delta":
                    yield (
                        "suggestion.delta",
                        {
                            "batch_id": batch_id,
                            "suggestion_id": suggestion_id,
                            "text": event.text,
                        },
                    )
                else:
                    done = {
                        "batch_id": batch_id,
                        "suggestion_id": suggestion_id,
                        "index": index,
                        "competency": competency,
                        "question": _squash(event.fields.get("question", "")),
                        "rationale": _squash(event.fields.get("rationale", "")),
                        "grounding": ground(event.fields.get("grounding", ""), answer),
                    }
                    _store(session_factory, done, qa_item_id, model)
                    yield "suggestion.done", done
                    index += 1
            if index >= MAX_SUGGESTIONS:
                break
    except Exception:
        yield "error", {"message": "꼬리질문 생성 중 오류가 발생했습니다."}
        return
    finally:
        aclose = getattr(stream, "aclose", None)
        if aclose is not None:
            await aclose()  # stops the model call when the client goes away
    yield "batch.done", {"batch_id": batch_id}


def _store(
    session_factory: sessionmaker[Session], done: dict[str, Any], qa_item_id: str, model: str
) -> None:
    with session_factory() as db:
        db.add(
            FollowUpSuggestion(
                id=done["suggestion_id"],
                batch_id=done["batch_id"],
                qa_item_id=qa_item_id,
                position=done["index"],
                competency=done["competency"],
                question=done["question"],
                rationale=done["rationale"],
                grounding=done["grounding"],
                model=model,
                prompt_version=FOLLOWUP_PROMPT,
            )
        )
        db.commit()
