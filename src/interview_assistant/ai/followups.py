"""FR-06: follow-up suggestions for one answer (POST /api/sessions/{id}/follow-ups, SSE).

First the question bank: the de-identified answer is embedded (after the guard cleared it) and up
to two approved bank questions or follow-up examples close to it are shown at once, marked as such.
Then the LLM streams its own 2-3, with the closest bank questions in the prompt as examples. The
model writes tagged blocks (prompts.FOLLOWUP_FORMAT); `SuggestionParser` turns its token stream into
the SSE events of docs/api-contract.md 3.2 as text arrives.

A candidate that means the same as a question already asked in this interview or an earlier round,
or as a suggestion shown before it (dense similarity at or above the embedding role's
`duplicate_threshold`), is left out: a bank one before it is shown, a model one once it is complete
(`suggestion.discarded` takes back the card that was being written). Every candidate is stored
(FollowUpSuggestion) with its source, timing and, if dropped, what it duplicated. Suggestions are
never turned into questions here.

In round 2 and later the prompt also carries the earlier rounds' Q&A (de-identified, as stored),
so the model does not ask again what an earlier round asked and digs deeper instead. Those texts
are declared to the guard like the current answer.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from interview_assistant.ai.gateway import AiCall, AiGateway
from interview_assistant.ai.guard import IdentifierInPrompt, check_prompt
from interview_assistant.ai.prompts import (
    FOLLOWUP_PROMPT,
    FOLLOWUP_SYSTEM,
    RETRIEVAL_VERSION,
    followup_prompt,
)
from interview_assistant.deid.service import DeidService
from interview_assistant.interviews import (
    earlier_round_qa,
    earlier_sessions,
    session_competency_set,
)
from interview_assistant.models import (
    ActorType,
    AuditLog,
    FollowUpSuggestion,
    QAItem,
    SuggestionSource,
)
from interview_assistant.models.base import new_id
from interview_assistant.retrieval.bank import BankMatch, bank_matches, duplicate_of
from interview_assistant.retrieval.service import Retrieval

log = logging.getLogger(__name__)

MAX_SUGGESTIONS = 3  # from the model, shown (duplicates do not count)
BANK_SUGGESTIONS = 2  # from the question bank, shown first
BANK_EXAMPLES = 4  # bank questions given to the model as examples
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


@dataclass
class _Shown:
    """A question the interviewer already has in front of them: asked, or suggested in this batch."""

    text: str
    vector: list[float]


async def _retrieve(
    retrieval: Retrieval | None,
    session_factory: sessionmaker[Session],
    *,
    answer: str,
    asked: list[str],
    job_family: str,
    competencies: list[str],
    round_position: int,
) -> tuple[list[BankMatch], list[_Shown], int]:
    """Bank questions close to the answer, and the asked questions' vectors (for duplicates)."""
    if retrieval is None or retrieval.serving is None:
        return [], [], 0
    started = time.perf_counter()
    try:
        embeddings = await retrieval.encode([answer, *asked])
        with session_factory() as db:
            matches = await bank_matches(
                retrieval,
                db,
                embeddings[0],
                job_family=job_family,
                competencies=competencies,
                round_position=round_position,
            )
    except Exception:
        log.exception("question-bank retrieval failed; follow-ups continue without it")
        return [], [], round((time.perf_counter() - started) * 1000)
    shown = [_Shown(q, e.dense) for q, e in zip(asked, embeddings[1:], strict=True)]
    return matches, shown, round((time.perf_counter() - started) * 1000)


async def follow_up_events(
    session_factory: sessionmaker[Session],
    ai: AiGateway,
    deid: DeidService,
    *,
    session_id: str,
    qa_item_id: str,
    retrieval: Retrieval | None = None,
) -> AsyncIterator[Event]:
    started = time.perf_counter()

    def elapsed() -> int:
        return round((time.perf_counter() - started) * 1000)

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
        earlier_rounds = earlier_round_qa(session)
        # Every question the candidate already heard: this interview and earlier rounds.
        asked = list(
            dict.fromkeys(
                [q.question for q in session.qa_items]
                + [q.question for s in earlier_sessions(session) for q in s.qa_items]
            )
        )
        answer = qa.answer_deidentified
        target = qa.target_competency
        question = qa.question
        job_family = session.application.posting.job_family
        round_position = session.round.position
        known = deid.identity(session.application.candidate)
        candidate_texts = [
            answer,
            question,
            *(t for pair in earlier for t in pair),
            *(t for _, q, a in earlier_rounds for t in (q, a)),
        ]

    # Candidate text is embedded only once the guard passed it (as it would for the LLM).
    try:
        check_prompt("", [*candidate_texts, *asked], known)
        cleared = True
    except IdentifierInPrompt:
        cleared = False
    matches, shown, retrieval_ms = (
        await _retrieve(
            retrieval,
            session_factory,
            answer=answer,
            asked=asked,
            job_family=job_family,
            competencies=names,
            round_position=round_position,
        )
        if cleared
        else ([], [], 0)
    )
    retrieved = retrieval is not None and retrieval.serving is not None and cleared
    retrieval_model = retrieval.model if retrieved and retrieval is not None else None
    threshold = retrieval.threshold("duplicate_threshold", 0.9) if retrieval else 1.0
    minimum = retrieval.threshold("min_score", 0.5) if retrieval else 0.0
    picks: list[tuple[BankMatch, _Shown]] = []
    rows: list[dict[str, Any]] = []  # every candidate, stored at the end of its life
    for match in matches:
        if match.score < minimum or len(picks) >= BANK_SUGGESTIONS:
            continue
        same = duplicate_of(match.embedding, [(s.text, s.vector) for s in shown], threshold)
        if same is not None:
            rows.append(_bank_row(match, answer, batch_id, None, retrieval_model, discarded=same))
            continue
        picks.append((match, _Shown(match.text, match.embedding)))
        shown.append(_Shown(match.text, match.embedding))
    examples = [
        (m.item.competency, m.item.question, list(m.item.follow_ups or []))
        for m in matches[:BANK_EXAMPLES]
    ]

    with session_factory() as db:
        call = AiCall(
            action="followup.generated",
            prompt_version=FOLLOWUP_PROMPT,
            system=FOLLOWUP_SYSTEM,
            prompt=followup_prompt(
                competencies=competencies,
                target_competency=target,
                previous=earlier,
                earlier_rounds=earlier_rounds,
                question=question,
                answer=answer,
                examples=examples,
                already_suggested=[m.text for m, _ in picks],
            ),
            candidate_texts=candidate_texts,
            known=known,
            target_type="interview_session",
            target_id=session_id,
            details={
                "qa_item_id": qa_item_id,
                "batch_id": batch_id,
                "earlier_round_answers": len(earlier_rounds),
                "bank_examples": len(examples),
            },
        )
        try:
            model, stream = ai.stream(db, call)
        except IdentifierInPrompt:
            db.commit()
            yield "error", {"message": "답변에 식별 정보가 남아 있어 AI에 보내지 않았습니다."}
            return
        if retrieved and retrieval is not None and retrieval.serving is not None:
            db.add(
                AuditLog(
                    actor_type=ActorType.ai,
                    action="followup.retrieved",
                    target_type="interview_session",
                    target_id=session_id,
                    model=retrieval.model,
                    prompt_version=RETRIEVAL_VERSION,
                    details={
                        "qa_item_id": qa_item_id,
                        "batch_id": batch_id,
                        "index_key": retrieval.serving.key,
                        "matches": len(matches),
                        "shown": len(picks),
                        "duplicates": len(rows),
                        "retrieval_ms": retrieval_ms,
                    },
                )
            )
        db.commit()

    yield (
        "batch.start",
        {
            "batch_id": batch_id,
            "qa_item_id": qa_item_id,
            "model": model,
            "prompt_version": FOLLOWUP_PROMPT,
            "retrieval_model": retrieval_model,
        },
    )
    index = 0
    for match, _ in picks:
        row = _bank_row(match, answer, batch_id, index, retrieval_model)
        row["latency_ms"] = elapsed()
        competency = match.item.competency
        yield (
            "suggestion.start",
            {
                "batch_id": batch_id,
                "suggestion_id": row["id"],
                "index": index,
                "competency": competency,
                "source": "bank",
            },
        )
        done = {
            "batch_id": batch_id,
            "suggestion_id": row["id"],
            "index": index,
            "competency": competency,
            "question": row["question"],
            "rationale": row["rationale"],
            "grounding": row["grounding"],
            "source": "bank",
            "bank_item_id": match.item.id,
            "score": round(match.score, 3),
        }
        rows.append(row)
        yield "suggestion.done", done
        index += 1
    _store(session_factory, rows, qa_item_id)
    rows = []

    parser = SuggestionParser()
    written = 0  # model suggestions shown (duplicates do not count)
    suggestion_id = ""
    competency = ""
    shown_at = 0
    discarded = 0
    try:
        async for chunk in stream:
            for event in parser.feed(chunk):
                if written >= MAX_SUGGESTIONS:
                    break
                if event.kind == "start":
                    suggestion_id = new_id()
                    competency = _pick_competency(event.fields["competency"], names, target)
                    shown_at = elapsed()
                    yield (
                        "suggestion.start",
                        {
                            "batch_id": batch_id,
                            "suggestion_id": suggestion_id,
                            "index": index,
                            "competency": competency,
                            "source": "ai",
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
                        "source": "ai",
                    }
                    row = {
                        "id": suggestion_id,
                        "batch_id": batch_id,
                        "position": index,
                        "competency": competency,
                        "question": done["question"],
                        "rationale": done["rationale"],
                        "grounding": done["grounding"],
                        "model": model,
                        "prompt_version": FOLLOWUP_PROMPT,
                        "source": SuggestionSource.ai,
                        "latency_ms": shown_at,
                    }
                    index += 1
                    vector = await _vector(retrieval, done["question"], known) if cleared else None
                    same = (
                        duplicate_of(vector, [(s.text, s.vector) for s in shown], threshold)
                        if vector is not None
                        else None
                    )
                    if same is not None:
                        row |= {"discarded": "duplicate", "duplicate_of": same[0], "similarity": round(same[1], 3)}
                        _store(session_factory, [row], qa_item_id)
                        discarded += 1
                        yield (
                            "suggestion.discarded",
                            {
                                "batch_id": batch_id,
                                "suggestion_id": suggestion_id,
                                "reason": "duplicate",
                                "duplicate_of": same[0],
                                "similarity": round(same[1], 3),
                            },
                        )
                        continue
                    if vector is not None:
                        shown.append(_Shown(done["question"], vector))
                    _store(session_factory, [row], qa_item_id)
                    yield "suggestion.done", done
                    written += 1
            if written >= MAX_SUGGESTIONS:
                break
    except Exception:
        log.exception("follow-up stream failed")
        yield "error", {"message": "꼬리질문 생성 중 오류가 발생했습니다."}
        return
    finally:
        aclose = getattr(stream, "aclose", None)
        if aclose is not None:
            await aclose()  # stops the model call when the client goes away
    yield "batch.done", {"batch_id": batch_id, "discarded": discarded}


async def _vector(retrieval: Retrieval | None, text: str, known: Any) -> list[float] | None:
    """A model-written question's vector for the duplicate check (guarded like candidate text)."""
    if retrieval is None or retrieval.serving is None or not text:
        return None
    try:
        check_prompt("", [text], known)
        [embedding] = await retrieval.encode([text])
    except Exception:
        return None
    return embedding.dense


def _bank_row(
    match: BankMatch,
    answer: str,
    batch_id: str,
    index: int | None,
    model: str | None,
    *,
    discarded: tuple[str, float] | None = None,
) -> dict[str, Any]:
    item = match.item
    if match.part == 0:
        rationale = f"질문 은행 · {item.intent}" if item.intent else "질문 은행의 검수된 질문"
    else:
        rationale = f"질문 은행 '{_squash(item.question)}'의 꼬리질문 예시"
    row: dict[str, Any] = {
        "id": new_id(),
        "batch_id": batch_id,
        "position": index if index is not None else -1,
        "competency": item.competency,
        "question": _squash(match.text),
        "rationale": rationale,
        "grounding": ground(match.text, answer),
        "model": model,
        "prompt_version": RETRIEVAL_VERSION,
        "source": SuggestionSource.bank,
        "bank_item_id": item.id,
        "retrieval_score": round(match.score, 4),
    }
    if discarded is not None:
        row |= {
            "discarded": "duplicate",
            "duplicate_of": discarded[0],
            "similarity": round(discarded[1], 3),
        }
    return row


def _store(session_factory: sessionmaker[Session], rows: list[dict[str, Any]], qa_item_id: str) -> None:
    if not rows:
        return
    with session_factory() as db:
        for row in rows:
            db.add(FollowUpSuggestion(qa_item_id=qa_item_id, **row))
        db.commit()
