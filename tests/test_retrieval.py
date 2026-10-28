"""질문 은행, 검색, 꼬리질문 출처·중복 거르기, 재색인, 평점 기준 예시 (retrieval/, api/routes/bank.py).

Runs on the fake embedding (words and character pairs hashed): enough lexical meaning for the
rules under test, no model files, no network. tests/test_bge_m3.py checks the real model.
"""

from __future__ import annotations

import asyncio
import csv
import io
import re
from collections.abc import AsyncIterator
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from interview_assistant.models import (
    AuditLog,
    BankStatus,
    EmbeddingIndex,
    EmbeddingVector,
    FollowUpSuggestion,
    IndexStatus,
    InterviewRound,
    JobPosting,
    QAItem,
    QuestionBankItem,
    RubricExample,
    Score,
)
from interview_assistant.models.base import utcnow
from interview_assistant.providers.base import Embedding
from interview_assistant.providers.fake import FakeEmbedding
from interview_assistant.retrieval.bank import anchors_for, bank_matches
from interview_assistant.retrieval.index import Doc, MemoryIndex
from interview_assistant.retrieval.service import Retrieval

from .api_util import LIVE, P1, sse_events, wait_for

FAB = "공정개발"


def ready(api) -> Retrieval:
    api.portal.call(api.runtime.retrieval.wait)
    return api.runtime.retrieval


def search(api, text: str, *, family: str = FAB, competencies=(), round_position: int | None = 1) -> list[str]:
    retrieval = ready(api)

    async def run() -> list[str]:
        [query] = await retrieval.encode([text])
        with api.runtime.session_factory() as db:
            found = await bank_matches(
                retrieval,
                db,
                query,
                job_family=family,
                competencies=list(competencies),
                round_position=round_position,
            )
            return [m.item.id for m in found]

    return api.portal.call(run)


def embedding(api) -> FakeEmbedding:
    provider = api.runtime.models.active.get("embedding")
    assert isinstance(provider, FakeEmbedding)
    return provider


def llm(api):
    return api.runtime.models.active.get("llm.primary")


def new_question(api, question: str, **extra: Any) -> dict:
    body = {"job_family": FAB, "competency": "공정·장비 이해", "round_position": 1, "question": question}
    created = api.post("/api/question-bank", json={**body, **extra})
    assert created.status_code == 201, created.text
    return created.json()


# --- 질문 은행: 승인된 것만 검색 ---------------------------------------------------------------


def test_seeded_bank_and_index_are_ready(api):
    listed = api.get("/api/question-bank").json()
    assert listed["counts"]["approved"] > 30 and listed["counts"]["draft"] == 2
    assert listed["counts"]["retired"] == 1
    flagged = [i for i in listed["items"] if i["flags"]]
    assert [i["question"] for i in flagged] == ["결혼 계획이 있다면 교대 근무나 해외 출장에 지장은 없을까요?"]
    assert flagged[0]["status"] == "draft" and flagged[0]["flags"][0]["category"] == "marriage"
    families = {f["job_family"]: f["competencies"] for f in listed["families"]}
    assert "공정·장비 이해" in families[FAB] and "시스템 설계" in families["SW개발"]

    retrieval = ready(api)
    status = api.get("/api/admin/embedding-index").json()
    assert status["serving_index_key"] == status["active_index_key"] == "fake-ngram/256"
    approved = [i for i in listed["items"] if i["status"] == "approved"]
    parts = sum(1 + len(i["follow_ups"]) for i in approved)
    assert status["counts"]["question"] == parts
    assert status["counts"]["rubric"] == 15 and status["counts"]["competency_set"] == 3
    assert retrieval.serving is not None
    with api.runtime.session_factory() as db:
        drafts = {i.id for i in db.scalars(select(QuestionBankItem).where(QuestionBankItem.status != BankStatus.approved))}
        indexed = {v.owner_id for v in db.scalars(select(EmbeddingVector).where(EmbeddingVector.owner_type == "question"))}
    assert drafts and not drafts & indexed


def test_only_approved_questions_are_searched(api):
    text = "초전도 큐비트의 결맞음 시간을 늘리려고 어떤 공정 조건을 바꿨나요?"
    draft = new_question(api, text)
    assert draft["status"] == "draft" and draft["flags"] == []
    assert draft["id"] not in search(api, text)

    approved = api.post(f"/api/question-bank/{draft['id']}/approve", json={}).json()
    assert approved["status"] == "approved" and approved["approved_by"]["name"] == "김서연"
    assert search(api, text)[0] == draft["id"]

    # Retired in the database but not yet out of the index: the search checks approval again.
    with api.runtime.session_factory() as db:
        db.get(QuestionBankItem, draft["id"]).status = BankStatus.retired
        db.commit()
    assert draft["id"] not in search(api, text)
    with api.runtime.session_factory() as db:
        db.get(QuestionBankItem, draft["id"]).status = BankStatus.approved
        db.commit()
    assert api.post(f"/api/question-bank/{draft['id']}/retire").json()["status"] == "retired"
    assert draft["id"] not in search(api, text)
    with api.runtime.session_factory() as db:
        vectors = db.scalar(select(func.count()).select_from(EmbeddingVector).where(EmbeddingVector.owner_id == draft["id"]))
    assert vectors == 0

    # Seeded draft and retired questions are never found, even by their own text.
    listed = api.get("/api/question-bank").json()["items"]
    for item in listed:
        if item["status"] != "approved" and item["job_family"] == FAB:
            assert item["id"] not in search(api, item["question"], competencies=(), round_position=item["round_position"] or 1)


def test_editing_an_approved_question_sends_it_back_to_draft(api):
    item = new_question(api, "엣지 링 높이를 바꿀 때 플라즈마 쉬스의 변화를 어떻게 확인했나요?")
    api.post(f"/api/question-bank/{item['id']}/approve", json={})
    edited = api.put(
        f"/api/question-bank/{item['id']}",
        json={"job_family": FAB, "competency": "공정·장비 이해", "round_position": 1,
              "question": "엣지 링 높이와 쉬스 기울기의 관계를 어떻게 확인했나요?", "follow_ups": ["  ", "측정 방법은?"]},
    ).json()
    assert edited["status"] == "draft" and edited["approved_by"] is None
    assert edited["follow_ups"] == ["측정 방법은?"]
    assert item["id"] not in search(api, "엣지 링 높이와 쉬스 기울기의 관계를 어떻게 확인했나요?")


def test_round_and_job_family_filters(api):
    second = new_question(api, "임원 면접에서만 묻는 공정 로드맵 질문입니다 반도체 로드맵", competency="주도성과 책임감", round_position=2)
    api.post(f"/api/question-bank/{second['id']}/approve", json={})
    text = "임원 면접에서만 묻는 공정 로드맵 질문입니다 반도체 로드맵"
    assert second["id"] in search(api, text, round_position=2)
    assert second["id"] not in search(api, text, round_position=1)
    assert second["id"] not in search(api, text, family="SW개발", round_position=2)
    assert second["id"] not in search(api, text, competencies=["공정 문제 해결"], round_position=2)


# --- 금지 질문 ------------------------------------------------------------------------------------


def test_prohibited_question_rules():
    from interview_assistant.ai.question_rules import RULES, check

    for rule in RULES:
        assert [f.category for f in check(rule.example)] == [rule.category], rule.example
    for clean in (
        "가족 같은 팀 분위기를 만들려고 무엇을 했나요?",
        "기억에 남는 장애 하나를 탐지부터 회고까지 순서대로 설명해 주세요.",
        "장비 키 값을 바꾸는 절차를 설명해 주세요.",
        "앞으로 3년 동안 이루고 싶은 성장 목표는 무엇인가요?",
        "보수적으로 일정을 잡은 이유는 무엇인가요?",
        "CVD 증착 균일도에 영향을 준 변수는 무엇이었나요?",
    ):
        assert check(clean) == [], clean
    assert [f.category for f in check("부모님 직업이 무엇인가요?", "형제 관계는요?")] == ["family"]
    assert [f.category for f in check("부모님도 반도체 업계에서 무슨 일을 하시나요?")] == ["family"]
    assert check("가족 같은 팀에서 회사 일을 어떻게 나눴나요?") == []
    assert {f.category for f in check("결혼하셨어요?", "몇 년생이세요?")} == {"marriage", "age"}


def test_prohibited_question_needs_confirmation_to_approve(api):
    checked = api.post("/api/question-bank/check", json={"question": "고향이 어디신가요? 지방 근무가 가능한지 궁금합니다."}).json()
    assert [f["category"] for f in checked["flags"]] == ["origin"]

    item = new_question(api, "고향이 어디신가요? 지방 근무가 가능한지 궁금합니다.", competency="협업과 커뮤니케이션")
    assert [f["category"] for f in item["flags"]] == ["origin"] and item["flags"][0]["source"] == "rule"
    refused = api.post(f"/api/question-bank/{item['id']}/approve", json={})
    assert refused.status_code == 409 and "출신 지역" in refused.json()["detail"]

    ai = api.post(f"/api/question-bank/{item['id']}/ai-check").json()
    assert {f["source"] for f in ai["flags"]} == {"rule", "ai"}
    with api.runtime.session_factory() as db:
        call = db.scalars(select(AuditLog).where(AuditLog.action == "question_bank.ai_checked")).one()
        assert call.prompt_version == "question-check-v0.1" and call.actor_type.value == "ai"

    approved = api.post(f"/api/question-bank/{item['id']}/approve", json={"confirm_warnings": True})
    assert approved.status_code == 200 and approved.json()["status"] == "approved"
    with api.runtime.session_factory() as db:
        row = db.scalars(select(AuditLog).where(AuditLog.action == "question_bank.approved")).one()
        assert row.details == {"flags": ["origin"], "confirmed_warnings": True}


def test_writing_is_open_approving_is_for_admins(api):
    item = new_question(api, "공정 조건을 바꾼 뒤 효과를 어떻게 검증했나요? 새 질문")
    with api.runtime.session_factory() as db:
        from interview_assistant.models import Interviewer

        me = db.scalars(select(Interviewer).where(Interviewer.name == "김서연")).one()
        me.is_admin = False
        db.commit()
    assert api.post(f"/api/question-bank/{item['id']}/approve", json={}).status_code == 403
    assert api.post(f"/api/question-bank/{item['id']}/retire").status_code == 403
    assert api.post("/api/question-bank/import", files={"file": ("a.csv", b"x")}).status_code == 403
    assert new_question(api, "초안은 누구나 쓸 수 있습니다 데이터 질문")["status"] == "draft"


def test_csv_import_makes_drafts_and_reports_rows(api):
    rows = [
        ["직군", "역량", "차수", "질문", "의도", "꼬리질문 예시"],
        [FAB, "데이터 기반 분석", "1차", "FDC 알람이 잦을 때 실제 이상과 오탐을 어떻게 가렸나요?", "알람 품질", "알람 기준은 누가 정했나요? | 오탐을 줄인 뒤 결과는?"],
        [FAB, "데이터 기반 분석", "", "FDC 데이터에서 이상 징후를 찾을 때 어떤 변수부터 보나요?", "", ""],  # already in the bank
        [FAB, "공정 문제 해결", "1", "", "", ""],  # no question
        [FAB, "조직 적합과 성장 의지", "2", "자녀 계획이 있으신가요?", "", ""],  # prohibited
        [FAB, "공정 문제 해결", "9", "차수가 이상한 행", "", ""],
    ]
    buffer = io.StringIO()
    csv.writer(buffer).writerows(rows)
    data = buffer.getvalue().encode("cp949")  # what Excel on Korean Windows writes

    dry = api.post("/api/question-bank/import", files={"file": ("bank.csv", data, "text/csv")}, data={"dry_run": "true"}).json()
    assert dry == {
        "dry_run": True,
        "rows": 5,
        "created": 2,
        "skipped": 1,
        "errors": [{"row": 3, "message": "질문을 입력하세요."}, {"row": 5, "message": "차수는 1~6 또는 비워 둡니다."}],
        "warnings": [{"row": 4, "message": "금지 질문 경고: 임신·출산·육아 계획"}],
    }
    before = api.get("/api/question-bank").json()["counts"]["draft"]
    done = api.post("/api/question-bank/import", files={"file": ("bank.csv", data, "text/csv")}).json()
    assert done["created"] == 2 and not done["dry_run"]
    listed = api.get("/api/question-bank?status=draft").json()
    assert listed["counts"]["draft"] == before + 2
    imported = [i for i in listed["items"] if i["source"] == "csv"]
    assert {i["round_position"] for i in imported} == {1, 2}
    assert imported[0]["follow_ups"] == ["알람 기준은 누가 정했나요?", "오탐을 줄인 뒤 결과는?"]
    again = api.post("/api/question-bank/import", files={"file": ("bank.csv", data, "text/csv")}).json()
    assert again["created"] == 0 and again["skipped"] == 3


def test_csv_import_needs_the_required_columns(api):
    bad = "question,intent\n질문만 있음,\n".encode()
    response = api.post("/api/question-bank/import", files={"file": ("bank.csv", bad, "text/csv")})
    assert response.status_code == 422 and "직군" in response.json()["detail"][0]["msg"]


# --- 꼬리질문: 질문 은행 먼저, 출처, 예시, 중복 거르기 ----------------------------------------------


def _answer_preset(api, preset_id: str) -> dict:
    qa = api.post(
        f"/api/sessions/{LIVE}/qa-items",
        json={"question": next(p["question"] for p in api.get(f"/api/sessions/{LIVE}").json()["preset_questions"] if p["id"] == preset_id),
              "question_source": "preset", "preset_question_id": preset_id},
    ).json()
    wait_for(api, f"/api/sessions/{LIVE}", lambda b: b["qa_items"][-1]["answer_deidentified"])
    return qa


def _preset(api, competency: str) -> str:
    return next(p["id"] for p in api.get(f"/api/sessions/{LIVE}").json()["preset_questions"] if p["competency"] == competency)


def test_bank_suggestions_come_first_then_ai_with_bank_examples_in_the_prompt(api, monkeypatch):
    ready(api)
    prompts: list[str] = []
    model = llm(api)
    original = model.stream

    def recording(system: str, prompt: str, **kwargs: Any) -> AsyncIterator[str]:
        prompts.append(prompt)
        return original(system, prompt, **kwargs)

    monkeypatch.setattr(model, "stream", recording)
    qa = _answer_preset(api, _preset(api, "공정·장비 이해"))
    events = sse_events(api.post(f"/api/sessions/{LIVE}/follow-ups", json={"qa_item_id": qa["id"]}).text)
    names = [e for e, _ in events]
    assert names[0] == "batch.start" and names[-1] == "batch.done"
    starts = [d for e, d in events if e == "suggestion.start"]
    sources = [d["source"] for d in starts]
    assert sources[: sources.count("bank")] == ["bank"] * sources.count("bank")  # bank first
    assert 1 <= sources.count("bank") <= 2 and sources.count("ai") == 3
    bank_done = [d for e, d in events if e == "suggestion.done" and d["source"] == "bank"]
    assert all(d["bank_item_id"] and d["score"] > 0 and d["grounding"] for d in bank_done)
    assert not any(e == "suggestion.delta" and d["suggestion_id"] in {b["suggestion_id"] for b in bank_done} for e, d in events)
    assert events[0][1]["retrieval_model"] == "fake-ngram" and events[0][1]["prompt_version"] == "followup-v0.4"

    [prompt] = prompts
    examples = re.search(r"<example_questions>\n(.*?)\n</example_questions>", prompt, re.S).group(1)
    assert examples.startswith("- [") and "꼬리질문 예시" in examples
    suggested = re.search(r"<already_suggested>\n(.*?)\n</already_suggested>", prompt, re.S).group(1)
    assert all(d["question"] in suggested for d in bank_done)

    with api.runtime.session_factory() as db:
        rows = db.scalars(select(FollowUpSuggestion).where(FollowUpSuggestion.batch_id == events[0][1]["batch_id"])).all()
        by_source = {r.source.value for r in rows}
        assert by_source == {"bank", "ai"}
        assert all(r.latency_ms is not None for r in rows if r.discarded is None)
        bank_rows = [r for r in rows if r.source.value == "bank" and r.discarded is None]
        assert all(r.model == "fake-ngram" and r.prompt_version == "retrieval-v0.1" and r.retrieval_score for r in bank_rows)
        audit = db.scalars(select(AuditLog).where(AuditLog.action == "followup.retrieved")).one()
        assert audit.model == "fake-ngram" and audit.details["shown"] == len(bank_done)
        assert audit.details["index_key"] == "fake-ngram/256"

    # The interviewer uses a bank suggestion: it counts for the bank in the metrics.
    chosen = bank_done[0]
    api.post(
        f"/api/sessions/{LIVE}/qa-items",
        json={"question": chosen["question"], "question_source": "ai_suggested",
              "suggestion": {"batch_id": chosen["batch_id"], "suggestion_id": chosen["suggestion_id"], "edited": False, "original_question": chosen["question"]}},
    )
    metrics = api.get("/api/admin/follow-up-metrics?days=7").json()
    bank = next(s for s in metrics["sources"] if s["source"] == "bank")
    ai = next(s for s in metrics["sources"] if s["source"] == "ai")
    assert bank["shown"] >= 1 and bank["used"] == 1 and bank["adoption_rate"] > 0
    assert bank["first_ms_median"] is not None and ai["first_ms_median"] is not None
    assert metrics["retrieval_model"] == "fake-ngram"


def test_questions_already_asked_are_filtered_by_meaning(api, monkeypatch):
    ready(api)
    qa = _answer_preset(api, _preset(api, "공정·장비 이해"))
    asked = qa["question"]
    with api.runtime.session_factory() as db:
        answer = db.get(QAItem, qa["id"]).answer_deidentified
    # A bank question that asks again what was just asked, worded close to the answer so that it
    # ranks first (the fake embedding knows words, not meaning: the threshold is lowered to match).
    duplicate = new_question(api, f"{asked} {answer.split('.')[0]}")
    api.post(f"/api/question-bank/{duplicate['id']}/approve", json={})
    monkeypatch.setattr(embedding(api), "duplicate_threshold", 0.5)

    # The model, too, proposes the question just asked; its card is taken back when complete.
    model = llm(api)

    async def same_again(system: str, prompt: str, **kwargs: Any) -> AsyncIterator[str]:
        answer = re.search(r"<answer>\n(.*?)\n</answer>", prompt, re.S).group(1)
        quote = answer.split(".")[0]
        for question in (asked, "그 조건을 정한 근거 데이터는 무엇이었나요?"):
            yield (f"<suggestion><competency>공정·장비 이해</competency><question>{question}</question>"
                   f"<rationale>확인</rationale><grounding>{quote}</grounding></suggestion>")

    monkeypatch.setattr(model, "stream", same_again)
    events = sse_events(api.post(f"/api/sessions/{LIVE}/follow-ups", json={"qa_item_id": qa["id"]}).text)
    shown = {d["question"]: d for e, d in events if e == "suggestion.done"}
    # The model's copy is shown, still being checked, then taken back; the bank's never shows.
    assert shown[asked]["source"] == "ai" and shown[asked]["checking"] is True
    [discarded] = [d for e, d in events if e == "suggestion.discarded"]
    assert discarded["suggestion_id"] == shown[asked]["suggestion_id"]
    assert discarded["duplicate_of"] == asked and discarded["similarity"] >= 0.99
    assert [d["suggestion_id"] for e, d in events if e == "suggestion.checked"] == [
        d["suggestion_id"] for q, d in shown.items() if d["source"] == "ai" and q != asked
    ]
    assert events[-1] == ("batch.done", {"batch_id": events[0][1]["batch_id"], "discarded": 1})
    assert duplicate["question"] not in shown

    # The interviewer cannot record the duplicate (it was on screen for a moment).
    count = len(api.get(f"/api/sessions/{LIVE}").json()["qa_items"])
    refused = api.post(
        f"/api/sessions/{LIVE}/qa-items",
        json={"question": asked, "question_source": "ai_suggested",
              "suggestion": {"batch_id": discarded["batch_id"], "suggestion_id": discarded["suggestion_id"],
                             "edited": False, "original_question": asked}},
    )
    assert refused.status_code == 409 and "거둔 제안" in refused.json()["detail"]
    assert len(api.get(f"/api/sessions/{LIVE}").json()["qa_items"]) == count
    with api.runtime.session_factory() as db:
        dropped = db.scalars(select(FollowUpSuggestion).where(FollowUpSuggestion.discarded == "duplicate")).all()
        mine = [r for r in dropped if r.bank_item_id == duplicate["id"]]
        assert [(r.source.value, r.duplicate_of) for r in mine] == [("bank", asked)]
        assert [(r.source.value, r.duplicate_of) for r in dropped if r.source.value == "ai"] == [("ai", asked)]
    metrics = api.get("/api/admin/follow-up-metrics").json()
    assert metrics["duplicates"]["ai"] == 1 and metrics["duplicates"]["bank"] == len(dropped) - 1
    assert metrics["duplicates"]["total"] == len(dropped)

    # The threshold is the embedding role's setting: nothing is the same question above 1.
    monkeypatch.setattr(embedding(api), "duplicate_threshold", 1.01)
    again = sse_events(api.post(f"/api/sessions/{LIVE}/follow-ups", json={"qa_item_id": qa["id"]}).text)
    assert not [e for e, _ in again if e == "suggestion.discarded"]


def test_duplicate_check_runs_after_the_card_is_shown(api, monkeypatch):
    """Embedding a model suggestion for the duplicate check holds up neither its card nor the next
    one. Until the check is done the suggestion is not stored, so it cannot become a question; a
    duplicate is stored as discarded and the API refuses it. The bank examples stay in the prompt."""
    from interview_assistant.ai.followups import follow_up_events
    from interview_assistant.models import InterviewSession

    ready(api)
    qa = _answer_preset(api, _preset(api, "공정·장비 이해"))
    asked = qa["question"]
    written = [asked, "그 조건을 정한 근거 데이터는 무엇이었나요?", "다른 챔버에서도 같은 현상이 있었나요?"]
    retrieval = api.runtime.retrieval
    original = retrieval.encode
    state: dict[str, Any] = {}

    async def gated(texts):
        if len(texts) == 1 and texts[0] in written:  # a model suggestion's check (even if cached)
            await state["gate"].wait()
        return await original(texts)

    prompts: list[str] = []

    async def three(system: str, prompt: str, **kwargs: Any) -> AsyncIterator[str]:
        prompts.append(prompt)
        quote = re.search(r"<answer>\n(.*?)\n</answer>", prompt, re.S).group(1).split(".")[0]
        for question in written:
            yield (f"<suggestion><competency>공정·장비 이해</competency><question>{question}</question>"
                   f"<rationale>확인</rationale><grounding>{quote}</grounding></suggestion>")
        state["gate"].set()  # every card is on screen before any check may finish

    monkeypatch.setattr(retrieval, "encode", gated)
    monkeypatch.setattr(llm(api), "stream", three)
    with api.runtime.session_factory() as db:
        ai = api.runtime.pinned(db.get(InterviewSession, LIVE)).ai

    async def run() -> list[tuple[str, dict]]:
        state["gate"] = asyncio.Event()
        events = []
        async for event in follow_up_events(
            api.runtime.session_factory, ai, api.runtime.deid,
            session_id=LIVE, qa_item_id=qa["id"], retrieval=api.runtime.retrieval,
        ):
            events.append(event)
            name, data = event
            if name == "suggestion.done" and data["source"] == "ai":
                assert data["checking"] is True
                with api.runtime.session_factory() as db:  # not usable yet: the API does not know it
                    assert db.get(FollowUpSuggestion, data["suggestion_id"]) is None
        return events

    events = api.portal.call(run)
    names = [(e, d.get("suggestion_id")) for e, d in events]
    ai_ids = [d["suggestion_id"] for e, d in events if e == "suggestion.start" and d["source"] == "ai"]
    assert len(ai_ids) == 3
    first_result = min(names.index(("suggestion.checked", i)) if ("suggestion.checked", i) in names
                       else names.index(("suggestion.discarded", i)) for i in ai_ids)
    assert names.index(("suggestion.start", ai_ids[2])) < first_result  # shown without waiting
    [discarded] = [d for e, d in events if e == "suggestion.discarded"]
    assert discarded["suggestion_id"] == ai_ids[0] and discarded["duplicate_of"] == asked
    assert [d["suggestion_id"] for e, d in events if e == "suggestion.checked"] == ai_ids[1:]

    # The question-bank examples are still in the prompt.
    [prompt] = prompts
    assert re.search(r"<example_questions>\n- \[", prompt)

    with api.runtime.session_factory() as db:
        rows = {r.id: r for r in db.scalars(select(FollowUpSuggestion).where(FollowUpSuggestion.id.in_(ai_ids)))}
    assert rows[ai_ids[0]].discarded == "duplicate" and rows[ai_ids[0]].duplicate_of == asked
    assert rows[ai_ids[1]].discarded is None and rows[ai_ids[1]].latency_ms is not None

    def use(suggestion_id: str, question: str):
        return api.post(
            f"/api/sessions/{LIVE}/qa-items",
            json={"question": question, "question_source": "ai_suggested",
                  "suggestion": {"batch_id": discarded["batch_id"], "suggestion_id": suggestion_id,
                                 "edited": False, "original_question": question}},
        )

    count = len(api.get(f"/api/sessions/{LIVE}").json()["qa_items"])
    assert use(ai_ids[0], asked).status_code == 409
    assert len(api.get(f"/api/sessions/{LIVE}").json()["qa_items"]) == count
    assert use(ai_ids[1], written[1]).status_code == 201


def test_retrieval_embeds_a_text_once_while_it_is_being_embedded(api):
    """The answer prefetched while the candidate spoke and the follow-up search asking for the same
    text share one embedding instead of queueing a second one behind it."""
    retrieval = ready(api)
    provider = retrieval.serving.provider
    calls: list[list[str]] = []
    original = provider.encode

    async def counted(texts):
        calls.append(list(texts))
        await asyncio.sleep(0.05)
        return await original(texts)

    async def run():
        provider.encode = counted
        try:
            first = asyncio.ensure_future(retrieval.encode(["지금 막 끝난 답변입니다."]))
            await asyncio.sleep(0)
            second = await retrieval.encode(["지금 막 끝난 답변입니다.", "이미 한 질문인가요?"])
            return await first, second
        finally:
            del provider.encode

    first, second = api.portal.call(run)
    assert calls == [["지금 막 끝난 답변입니다."], ["이미 한 질문인가요?"]]
    assert first[0].dense == second[0].dense


def test_earlier_round_questions_count_as_asked(api, monkeypatch):
    from .api_util import LIVE2

    ready(api)
    detail = api.get(f"/api/sessions/{LIVE2}").json()
    answered = next(q for q in reversed(detail["qa_items"]) if q["answer_deidentified"])
    with api.runtime.session_factory() as db:
        from interview_assistant.interviews import earlier_sessions
        from interview_assistant.models import InterviewSession

        earlier = [q.question for s in earlier_sessions(db.get(InterviewSession, LIVE2)) for q in s.qa_items]
    assert earlier
    model = llm(api)

    async def repeat_round_one(system: str, prompt: str, **kwargs: Any) -> AsyncIterator[str]:
        answer = re.search(r"<answer>\n(.*?)\n</answer>", prompt, re.S).group(1)
        yield (f"<suggestion><competency>주도성과 책임감</competency><question>{earlier[0]}</question>"
               f"<rationale>r</rationale><grounding>{answer[:20]}</grounding></suggestion>")

    monkeypatch.setattr(model, "stream", repeat_round_one)
    events = sse_events(api.post(f"/api/sessions/{LIVE2}/follow-ups", json={"qa_item_id": answered["id"]}).text)
    assert [d["duplicate_of"] for e, d in events if e == "suggestion.discarded"] == [earlier[0]]


def test_follow_ups_go_on_without_retrieval(api, monkeypatch):
    ready(api)

    async def broken(texts):
        raise RuntimeError("embedding is down")

    monkeypatch.setattr(embedding(api), "encode", broken)
    api.runtime.retrieval._cache.clear()
    qa = _answer_preset(api, _preset(api, "데이터 기반 분석"))
    events = sse_events(api.post(f"/api/sessions/{LIVE}/follow-ups", json={"qa_item_id": qa["id"]}).text)
    assert [d["source"] for e, d in events if e == "suggestion.done"] == ["ai", "ai", "ai"]


# --- 재색인: 이전 벡터로 계속 ---------------------------------------------------------------------


class _Gate(FakeEmbedding):
    """A model whose embedding waits until the test opens the gate."""

    def __init__(self, gate: asyncio.Event, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.gate = gate

    async def encode(self, texts):
        await self.gate.wait()
        return await super().encode(texts)


class _Models:
    def __init__(self, provider: Any) -> None:
        self.provider = provider
        self.listeners: list[Any] = []
        self.context: dict[str, Any] = {}

    @property
    def active(self):
        models = self

        class _Set:
            specs = {"embedding": None}

            def get(self, role: str) -> Any:
                return models.provider

        return _Set()


async def test_reindexing_keeps_searching_the_old_vectors_until_done(db_factory):
    from interview_assistant.models import Interviewer

    with db_factory() as db:
        person = Interviewer(employee_no="E1", name="검수자")
        db.add(person)
        db.flush()
        for i, text in enumerate(("FDC 알람 기준은 어떻게 정했나요?", "CVD 두께 균일도를 높인 방법은?", "팀 갈등을 어떻게 풀었나요?")):
            db.add(QuestionBankItem(job_family=FAB, competency="역량", question=text, status=BankStatus.approved,
                                    created_by=person.id, approved_by=person.id, approved_at=utcnow(), flags=[], follow_ups=[]))
        db.commit()

    tasks: set[asyncio.Task] = set()

    def spawn(coro):
        task = asyncio.get_running_loop().create_task(coro)
        tasks.add(task)
        return task

    old = FakeEmbedding(dimensions=64)
    models = _Models(old)
    retrieval = Retrieval(db_factory, models, spawn)  # type: ignore[arg-type]
    retrieval.start()
    await retrieval.wait()
    assert retrieval.serving is not None and retrieval.serving.key == "fake-ngram/64"

    gate = asyncio.Event()
    models.provider = _Gate(gate, dimensions=128)
    for listener in models.listeners:
        listener("embedding")
    await asyncio.sleep(0.05)
    states = {s.key: s for s in retrieval.states()}
    assert states["fake-ngram/128"].status == "building" and states["fake-ngram/128"].done == 0
    assert retrieval.serving.key == "fake-ngram/64"  # still the old index
    with db_factory() as db:
        [query] = await old.encode(["FDC 알람 기준"])
        found = await bank_matches(retrieval, db, query, job_family=FAB, competencies=[], round_position=1)
        assert found and found[0].item.question.startswith("FDC")
        assert db.scalar(select(func.count()).select_from(EmbeddingVector).where(EmbeddingVector.index_key == "fake-ngram/64")) == 3

    gate.set()
    await retrieval.wait()
    assert retrieval.serving.key == "fake-ngram/128"
    with db_factory() as db:
        keys = set(db.scalars(select(EmbeddingVector.index_key)))
        assert keys == {"fake-ngram/128"}
        assert db.get(EmbeddingIndex, "fake-ngram/128").status is IndexStatus.ready
        assert db.get(EmbeddingIndex, "fake-ngram/64") is None
    await asyncio.gather(*tasks, return_exceptions=True)


async def test_a_failed_reindex_leaves_the_old_index_serving(db_factory):
    class Broken(FakeEmbedding):
        async def warm_up(self) -> None:
            raise RuntimeError("모델 파일이 없습니다")

    tasks: set[asyncio.Task] = set()
    spawn = lambda coro: tasks.add(t := asyncio.get_running_loop().create_task(coro)) or t  # noqa: E731
    models = _Models(FakeEmbedding(dimensions=32))
    retrieval = Retrieval(db_factory, models, spawn)  # type: ignore[arg-type]
    retrieval.start()
    await retrieval.wait()
    models.provider = Broken(dimensions=16)
    retrieval.changed()
    await retrieval.wait()
    assert retrieval.serving.key == "fake-ngram/32"
    failed = {s.key: s for s in retrieval.states()}["fake-ngram/16"]
    assert failed.status == "failed" and "모델 파일" in failed.error
    await asyncio.gather(*tasks, return_exceptions=True)


def test_switching_the_embedding_model_from_the_admin_screen_reindexes(api):
    ready(api)
    applied = api.post("/api/admin/models/embedding/apply", json={"impl": "fake", "options": {"dimensions": 64}, "reason": "재색인 확인"})
    assert applied.status_code == 200, applied.text
    ready(api)
    status = api.get("/api/admin/embedding-index").json()
    assert status["serving_index_key"] == "fake-ngram/64"
    assert [i["index_key"] for i in status["indexes"]] == ["fake-ngram/64"]
    assert status["indexes"][0]["status"] == "ready" and status["indexes"][0]["done"] == status["indexes"][0]["total"]
    # A threshold change keeps the vectors: no rebuild.
    api.post("/api/admin/models/embedding/apply", json={"impl": "fake", "options": {"dimensions": 64, "duplicate_threshold": 0.95}, "reason": "임계값"})
    ready(api)
    assert api.runtime.retrieval.threshold("duplicate_threshold", 0) == 0.95
    with api.runtime.session_factory() as db:
        built = db.scalars(select(AuditLog).where(AuditLog.action == "embedding.index_built")).all()
    assert [b.target_id for b in built] == ["fake-ngram/256", "fake-ngram/64"]
    assert api.post("/api/admin/embedding-index/rebuild").status_code == 202
    ready(api)


# --- 평점 기준 예시: 유사도로 채점하지 않고, 지난 답변을 쓰지 않는다 ---------------------------------


def test_scoring_shows_anchors_but_never_scores_by_similarity(api, monkeypatch):
    ready(api)
    qa = _answer_preset(api, _preset(api, "공정·장비 이해"))
    with api.runtime.session_factory() as db:
        answer = db.get(QAItem, qa["id"]).answer_deidentified
        mine = set(db.scalars(select(QAItem.answer_deidentified).where(QAItem.session_id == LIVE)))
        # Other applicants' answers (the demo script gives some candidates the same answer: left out).
        others = {a for a in db.scalars(select(QAItem.answer_deidentified).where(QAItem.session_id != LIVE, QAItem.answer_deidentified.is_not(None)))} - mine
        me = db.scalars(select(RubricExample)).first().created_by
        # A 5-point anchor word for word the candidate's answer (only possible straight in the DB).
        db.add(RubricExample(job_family=FAB, competency="공정·장비 이해", score=5, answer=answer, rationale="",
                             status=BankStatus.approved, created_by=me, approved_by=me, approved_at=utcnow()))
        db.commit()

    prompts: list[str] = []
    model = llm(api)

    async def two(system, prompt, *, schema=None, max_tokens=16000):
        from interview_assistant.providers.base import LLMResult

        prompts.append(prompt)
        quote = re.search(r"<answer>\n(.*?)\n</answer>", prompt, re.S).group(1).split(".")[0]
        scores = [{"competency": "공정·장비 이해", "score": 2, "evidence": quote, "confidence": 0.8}]
        structured = {"scores": scores} if schema and schema.get("title") == "AnswerScores" else {"points": []}
        return LLMResult("", structured, "fake-llm", 1, 1)

    async def no_embedding(*args, **kwargs):
        raise AssertionError("scoring must not embed anything")

    monkeypatch.setattr(model, "generate", two)
    monkeypatch.setattr(embedding(api), "encode", no_embedding)
    monkeypatch.setattr(embedding(api), "embed", no_embedding)
    api.post(f"/api/sessions/{LIVE}/end")
    wait_for(api, f"/api/sessions/{LIVE}/evaluation", lambda b: b["ai"]["status"] == "completed")
    with api.runtime.session_factory() as db:
        scores = db.scalars(select(Score).where(Score.qa_item_id == qa["id"])).all()
    assert [s.score for s in scores] == [2]  # the model's reading, not the 5 of the identical anchor
    scoring = [p for p in prompts if "<anchors>" in p and answer in p.split("<answer>")[1]]
    assert scoring and all("5점 예시" in p for p in scoring)
    for prompt in prompts:
        for other in others:
            assert other not in prompt  # no other applicant's answer, as anchor or otherwise


def test_anchor_selection_ignores_the_answer():
    import inspect

    assert list(inspect.signature(anchors_for).parameters) == ["db", "job_family", "competencies"]
    import interview_assistant.ai.scoring as scoring

    source = inspect.getsource(scoring)
    for word in ("Retrieval", ".encode(", ".embed(", "cosine", "similarity(", "bank_matches"):
        assert word not in source, word


def test_rubric_examples_refuse_applicant_answers_and_identifiers(api):
    with api.runtime.session_factory() as db:
        stored = db.scalars(select(QAItem.answer_deidentified).where(QAItem.answer_deidentified.is_not(None))).first()
    body = {"job_family": FAB, "competency": "공정 문제 해결", "score": 3, "answer": stored}
    copied = api.post("/api/rubric-examples", json=body)
    assert copied.status_code == 409 and "지원자의 실제 답변" in copied.json()["detail"]
    phone = api.post("/api/rubric-examples", json={**body, "answer": "연락은 010-1234-5678로 주세요. 가상 답변입니다."})
    assert phone.status_code == 422
    made_up = api.post("/api/rubric-examples", json={**body, "answer": "가스 유량과 압력 두 가지를 의심해 차례로 바꿔 보았고 압력이 원인이었습니다."})
    assert made_up.status_code == 201 and made_up.json()["status"] == "draft"


def test_rubric_overlap_between_score_levels_is_reported(api):
    ready(api)
    listed = api.get("/api/rubric-examples?job_family=공정개발&competency=공정 문제 해결").json()
    three = next(i for i in listed["items"] if i["score"] == 3)
    near = api.post(
        "/api/rubric-examples",
        json={"job_family": FAB, "competency": "공정 문제 해결", "score": 4, "question": three["question"], "answer": three["answer"] + " 끝."},
    ).json()
    assert [o["id"] for o in near["overlaps"]] == [three["id"]] and near["overlaps"][0]["score"] == 3
    approved = api.post(f"/api/rubric-examples/{near['id']}/approve").json()
    assert approved["status"] == "approved" and approved["overlaps"][0]["id"] == three["id"]


def test_the_vector_store_takes_company_text_only(api):
    with api.runtime.session_factory() as db:
        db.add(EmbeddingVector(index_key="x", owner_type="qa_item", owner_id="q", part=0, text_hash="h", dimensions=1, dense=b"\0\0\0\0"))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        kinds = set(db.scalars(select(EmbeddingVector.owner_type).distinct()))
    assert kinds <= {"question", "rubric", "competency_set"}


# --- 역량 사전 초안: 비슷한 공고의 확정 사전 ------------------------------------------------------


def test_competency_draft_gets_similar_approved_dictionaries(api):
    ready(api)
    with api.runtime.session_factory() as db:
        p1 = db.get(JobPosting, P1)
        twin = JobPosting(title="메모리 공정개발 엔지니어 (신입)", job_family=FAB, jd_text=p1.jd_text)
        db.add(twin)
        db.commit()
        round_id = db.scalars(select(InterviewRound.id).where(InterviewRound.posting_id == twin.id)).one()
        p1_sets = {s.id for s in p1.competency_sets if s.approved_at is not None}
    drafted = api.post(f"/api/rounds/{round_id}/competency-sets/generate")
    assert drafted.status_code == 201, drafted.text
    with api.runtime.session_factory() as db:
        call = db.scalars(select(AuditLog).where(AuditLog.action == "competency_set.generated")).all()[-1]
    refs = [r["competency_set_id"] for r in call.details["references"]]
    assert refs and set(refs) <= p1_sets and call.prompt_version == "competency-v0.4"


# --- the in-memory index itself -------------------------------------------------------------------


def test_memory_index_filters_and_hybrid_score():
    index = MemoryIndex()
    a = Doc("question", "a", 0, "FDC", {"job_family": "x", "round_position": None})
    b = Doc("question", "b", 0, "RF", {"job_family": "x", "round_position": 2})
    c = Doc("question", "c", 0, "CVD", {"job_family": "y", "round_position": None})
    index.put([(a, Embedding([1.0, 0.0], {1: 0.5})), (b, Embedding([0.8, 0.6], {2: 0.9})), (c, Embedding([1.0, 0.0]))])
    query = Embedding([1.0, 0.0], {2: 1.0})
    dense_only = index.search(query, owner_type="question", where={"job_family": "x", "round_position": (None, 2)})
    assert [h.doc.owner_id for h in dense_only] == ["a", "b"]
    hybrid = index.search(query, owner_type="question", where={"job_family": "x", "round_position": (None, 2)}, sparse_weight=0.3)
    assert [h.doc.owner_id for h in hybrid] == ["b", "a"]  # the shared term lifts b
    assert index.search(query, owner_type="question", where={"round_position": (None, 1)}, k=5)[0].doc.owner_id in {"a", "c"}
    index.drop([("question", "a", 0)])
    assert index.keys() == {("question", "b", 0), ("question", "c", 0)}
    assert index.vector(("question", "b", 0)).tolist() == pytest.approx([0.8, 0.6])
