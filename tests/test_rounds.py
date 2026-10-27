"""Interview rounds (전형 차수): round definitions, the order applications move in, decisions and
their history, what a later round sees of earlier ones, and what reaches the model from them."""

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from interview_assistant.demo import mock_data
from interview_assistant.demo.seed import fake_identity
from interview_assistant.models import (
    AuditLog,
    Interviewer,
    InterviewSession,
    QAItem,
    SessionMode,
    SessionStatus,
)
from interview_assistant.providers.fake import FakeLLM
from tests.api_util import (
    COMPLETED,
    EVALUATING,
    LIVE,
    LIVE2,
    P1,
    P3,
    json_keys,
    round_id,
    sse_events,
    wait_for,
)

P2 = "b1d6a0c2-1f3e-4b8a-9c41-5e2f7a9d0002"
CAND9_FIRST_ROUND = "0a1b2c3d-0000-4000-9000-r1n900000000"


def _audits(api, action: str) -> list[AuditLog]:
    with api.runtime.session_factory() as db:
        return list(db.scalars(select(AuditLog).where(AuditLog.action == action)).all())


def _me(api) -> dict:
    return api.get("/api/me").json()


def _submit(api, session_id: str) -> dict:
    ev = api.get(f"/api/sessions/{session_id}/evaluation").json()
    scores = [{"competency": c["name"], "score": 4, "comment": ""} for c in ev["competency_set"]["competencies"]]
    response = api.put(f"/api/sessions/{session_id}/scores/{_me(api)['id']}", json={"scores": scores})
    assert response.status_code == 200, response.text
    return response.json()


def _stage(api, posting_id: str, pseudonym: str) -> tuple:
    row = next(r for r in api.get(f"/api/postings/{posting_id}/applications").json() if r["candidate"]["pseudonym"] == pseudonym)
    stage = row["stage"]
    return stage["kind"], (stage["round"] or {}).get("label"), stage["status"]


def _identity(n: int):
    return fake_identity(n, next(c for c in mock_data()["candidates"] if c["n"] == n)["profile"])


# --- 전형 정의 -----------------------------------------------------------------------------------


def test_rounds_are_ordered_and_rounds_in_use_keep_their_place(api):
    p1 = api.get(f"/api/postings/{P1}/rounds").json()
    assert [(r["label"], r["name"], r["locked"], r["is_last"]) for r in p1] == [
        ("1차", "직무 면접", True, False),
        ("2차", "임원 면접", True, True),
    ]
    assert p1[0]["approved_competency_set"]["version"] == 1 and p1[0]["preset_count"] == 8
    assert p1[1]["default_mode"] == "onsite" and p1[1]["show_previous_scores"] is False

    assert api.post(f"/api/postings/{P2}/rounds", json={"name": "  "}).status_code == 422
    too_many = api.post(f"/api/postings/{P2}/rounds", json={"name": "x", "recommended_interviewers": 11})
    assert too_many.status_code == 422
    second = api.post(f"/api/postings/{P2}/rounds", json={"name": "기술 심층 면접", "default_mode": "onsite"})
    assert second.status_code == 201
    second = second.json()
    assert (second["position"], second["label"], second["is_last"], second["locked"]) == (2, "2차", True, False)
    first = round_id(api, P2)
    assert api.get(f"/api/postings/{P2}/rounds").json()[0]["is_last"] is False
    # CAND-0012 passed P2's only round; with a second round it is no longer final but waits for 2차.
    rows = {r["candidate"]["pseudonym"]: r for r in api.get(f"/api/postings/{P2}/applications").json()}
    assert rows["CAND-0012"]["stage"]["status"] == "waiting" and rows["CAND-0012"]["stage"]["round"]["label"] == "2차"

    updated = api.patch(f"/api/rounds/{second['id']}", json={"name": "기술 리더 면접", "show_previous_scores": True})
    assert updated.json()["name"] == "기술 리더 면접" and updated.json()["show_previous_scores"] is True
    [log] = _audits(api, "round.updated")
    assert log.details["name"] == {"from": "기술 심층 면접", "to": "기술 리더 면접"}

    third = api.post(f"/api/postings/{P2}/rounds", json={"name": "최종 면접"}).json()
    moved = api.put(f"/api/postings/{P2}/rounds/order", json={"round_ids": [second["id"], first, third["id"]]})
    assert moved.status_code == 409 and "1차" in moved.json()["detail"]
    assert api.put(f"/api/postings/{P2}/rounds/order", json={"round_ids": [first, second["id"]]}).status_code == 422
    swapped = api.put(f"/api/postings/{P2}/rounds/order", json={"round_ids": [first, third["id"], second["id"]]}).json()
    assert [r["name"] for r in swapped] == ["직무 면접", "최종 면접", "기술 리더 면접"]
    assert [r["label"] for r in swapped] == ["1차", "2차", "3차"]

    assert api.delete(f"/api/rounds/{first}").status_code == 409  # sessions and decisions
    assert api.delete(f"/api/rounds/{third['id']}").status_code == 204
    assert [r["label"] for r in api.get(f"/api/postings/{P2}/rounds").json()] == ["1차", "2차"]
    assert api.delete(f"/api/rounds/{round_id(api, P3)}").status_code == 409  # the only round
    assert {a.action for a in _audits(api, "round.created") + _audits(api, "round.deleted") + _audits(api, "round.reordered")} == {
        "round.created",
        "round.deleted",
        "round.reordered",
    }


def test_round_presets_drafts_and_ai_questions_do_not_repeat_earlier_rounds(api):
    second = round_id(api, P1, 2)
    drafted = api.post(f"/api/rounds/{second}/competency-sets/generate")
    assert drafted.status_code == 201
    draft = drafted.json()
    assert draft["round_id"] == second and draft["version"] == 2
    names = [c["name"] for c in draft["competencies"]]
    assert "공정 문제 해결" not in names  # round 1's dictionary is not just copied

    first_round_questions = {q["question"] for q in api.get(f"/api/sessions/{LIVE}").json()["preset_questions"]}
    generated = api.post(f"/api/competency-sets/{draft['id']}/preset-questions/generate")
    assert generated.status_code == 200
    questions = generated.json()
    assert questions and {q["competency"] for q in questions} <= set(names)
    assert not {q["question"] for q in questions} & first_round_questions
    again = api.post(f"/api/competency-sets/{draft['id']}/preset-questions/generate").json()
    assert len({q["question"] for q in again}) == len(again)  # nothing added twice
    [log] = _audits(api, "preset_question.generated")[:1]
    assert log.actor_type.value == "ai" and log.prompt_version == "preset-v0.1"

    approved = api.post(f"/api/competency-sets/{draft['id']}/approve")
    assert approved.status_code == 200
    assert api.post(f"/api/competency-sets/{draft['id']}/preset-questions/generate").status_code == 409


# --- 차수 진행과 결정 -----------------------------------------------------------------------------


def test_a_candidate_goes_from_round_one_to_final_candidate(api):
    first, second = round_id(api, P1), round_id(api, P1, 2)
    me = _me(api)
    ev = api.get(f"/api/sessions/{EVALUATING}/evaluation").json()
    assert ev["round"]["label"] == "1차" and ev["decision"]["can_decide"] is False
    assert ev["decision"]["blocked_reason"] == "면접관 점수가 모두 제출된 뒤에 결정할 수 있습니다."
    early = api.post(f"/api/sessions/{EVALUATING}/decision", json={"decision": "passed", "reason": "좋음"})
    assert early.status_code == 409
    application_id = ev["session"]["application_id"]
    body = {"application_id": application_id, "mode": "onsite", "scheduled_at": "2027-01-05T01:00:00Z", "interviewers": [{"interviewer_id": me["id"], "role": "lead"}]}
    not_yet = api.post("/api/sessions", json={**body, "round_id": second})
    assert not_yet.status_code == 409 and not_yet.json()["detail"] == "1차 합격자만 2차 면접을 잡을 수 있습니다."

    ev = _submit(api, EVALUATING)
    assert ev["decision"]["can_decide"] is True and ev["decision"]["next_round"]["label"] == "2차"
    assert api.post(f"/api/sessions/{EVALUATING}/decision", json={"decision": "passed", "reason": " "}).status_code == 422
    held = api.post(f"/api/sessions/{EVALUATING}/decision", json={"decision": "hold", "reason": "다른 지원자 결과를 보고 결정"}).json()
    assert held["decision"]["current"]["decision"] == "hold" and held["decision"]["current"]["revision"] == 1
    assert _stage(api, P1, "CAND-0005") == ("round", "1차", "hold")
    pending = api.get("/api/dashboard").json()["pending_decisions"]
    assert ("CAND-0005", "hold") in {(x["candidate"]["pseudonym"], x["status"]) for x in pending}
    assert application_id not in [a["application_id"] for a in api.get("/api/applications/schedulable?round=2").json()]

    passed = api.post(f"/api/sessions/{EVALUATING}/decision", json={"decision": "passed", "reason": "보류 후 비교 결과 합격"}).json()
    history = passed["decision"]["history"]
    assert [(h["revision"], h["decision"]) for h in history] == [(2, "passed"), (1, "hold")]
    assert history[0]["decided_by_name"] == "김서연"
    [changed] = _audits(api, "round.decision_changed")
    assert changed.details["from"] == "hold" and changed.details["to"] == "passed" and changed.target_id == application_id
    assert _stage(api, P1, "CAND-0005") == ("round", "2차", "waiting")

    waiting = api.get("/api/applications/schedulable?round=2").json()
    [mine] = [a for a in waiting if a["application_id"] == application_id]
    assert mine["round"]["label"] == "2차" and mine["mode"] == "onsite" and mine["recommended_interviewers"] == 2
    assert mine["since"] == history[0]["created_at"]

    created = api.post("/api/sessions", json=body)  # no round_id: the round it waits for
    assert created.status_code == 201
    summary = created.json()
    assert summary["round"]["label"] == "2차" and summary["round_status"] == "scheduled"
    again = api.post("/api/sessions", json={**body, "round_id": second})
    assert again.status_code == 409 and again.json()["detail"] == "이미 예정된 2차 면접이 있습니다."
    redo = api.post("/api/sessions", json={**body, "round_id": first})
    assert redo.status_code == 409 and redo.json()["detail"] == "1차 면접을 이미 마쳤습니다."
    late = api.post(f"/api/sessions/{EVALUATING}/decision", json={"decision": "rejected", "reason": "번복"})
    assert late.status_code == 409 and "2차 면접이 이미 있어" in late.json()["detail"]
    with api.runtime.session_factory() as db:  # the database refuses a second open session too
        db.add(InterviewSession(application_id=application_id, round_id=second, mode=SessionMode.remote, status=SessionStatus.scheduled))
        with pytest.raises(IntegrityError):
            db.commit()

    # 2차: the 1차 summary, carry-over questions, follow-ups that build on 1차.
    new = summary["id"]
    point = api.post(f"/api/sessions/{EVALUATING}/check-points", json={"text": "증착 쪽 깊이를 2차에서 확인", "competency": "공정·장비 이해"})
    assert point.status_code == 201 and point.json()["author_name"] == "김서연"
    api.post(f"/api/sessions/{new}/consent", json={"consent_recording": False})
    detail = api.post(f"/api/sessions/{new}/start").json()
    assert detail["round"]["label"] == "2차" and detail["competency_set"]["round_id"] == second
    [previous] = detail["card"]["previous_rounds"]
    assert previous["round"]["label"] == "1차" and previous["decision"] == "passed"
    assert previous["scores_visible"] is False and previous["scores"] is None and previous["decision_reason"] is None
    points = {p["source"]: p for p in previous["check_points"]}
    assert points["interviewer"]["text"] == "증착 쪽 깊이를 2차에서 확인" and points["interviewer"]["author_name"] == "김서연"
    ai = [p for p in previous["check_points"] if p["source"] == "ai"]  # the seed's, drawn when 1차 was scored
    assert ai and all(p["evidence"] and p["qa_item_id"] for p in ai)

    carried = api.post(f"/api/sessions/{new}/carryover-questions")
    assert carried.status_code == 200
    carryover = carried.json()["carryover_questions"]
    earlier = api.get(f"/api/sessions/{EVALUATING}").json()["qa_items"]
    assert 1 <= len(carryover) <= 3
    for q in carryover:
        assert q["origin"]["round"]["label"] == "1차"
        assert any(q["origin"]["grounding"] in (e["answer_deidentified"] or "") for e in earlier)
        assert q["question"] not in {e["question"] for e in earlier}
    asked = api.post(
        f"/api/sessions/{new}/qa-items",
        json={"question": carryover[0]["question"], "question_source": "preset", "preset_question_id": carryover[0]["id"]},
    )
    assert asked.status_code == 201
    answered = api.patch(f"/api/qa-items/{asked.json()['id']}", json={"answer_text": "제가 먼저 원인을 맡겠다고 했습니다. 결과는 팀과 같이 책임졌습니다."})
    assert answered.status_code == 200
    regenerated = api.post(f"/api/sessions/{new}/carryover-questions").json()["carryover_questions"]
    assert carryover[0]["id"] in [q["id"] for q in regenerated]  # an asked one stays

    events = sse_events(api.post(f"/api/sessions/{new}/follow-ups", json={"qa_item_id": asked.json()["id"]}).text)
    done = [data for name, data in events if name == "suggestion.done"]
    assert done and done[0]["question"].startswith("1차에서는")
    [log] = _audits(api, "followup.generated")[-1:]
    assert log.details["earlier_round_answers"] > 0

    api.post(f"/api/sessions/{new}/end")
    ev = wait_for(api, f"/api/sessions/{new}/evaluation", lambda b: b["ai"]["status"] == "completed")
    ai_points = [p for p in ev["check_points"] if p["source"] == "ai"]
    assert ai_points and all(p["evidence"] in answered.json()["answer_deidentified"] for p in ai_points)
    assert ev["decision"]["is_last_round"] is True
    ev = _submit(api, new)
    final = api.post(f"/api/sessions/{new}/decision", json={"decision": "passed", "reason": "책임감과 영향력 근거가 분명"}).json()
    assert final["decision"]["current"]["decision"] == "passed"
    assert _stage(api, P1, "CAND-0005") == ("final", None, "passed")
    [decided] = [x for x in _audits(api, "round.decided") if x.details.get("session_id") == new]
    assert decided.details["final"] is True
    counts = next(p for p in api.get("/api/postings").json() if p["id"] == P1)["counts"]
    assert counts["final"] == 1 and counts["rounds"][1]["passed"] == 1


def test_rejected_or_held_candidates_do_not_reach_the_next_round(api):
    rows = {r["candidate"]["pseudonym"]: r for r in api.get(f"/api/postings/{P2}/applications").json()}
    assert rows["CAND-0020"]["progress"][1]["status"] == "rejected"
    waiting = {a["candidate"]["pseudonym"] for a in api.get("/api/applications/schedulable").json()}
    assert waiting == {"CAND-0002", "CAND-0017"}  # passed screening, nothing booked yet
    assert api.get("/api/applications/schedulable?round=2").json() == []
    second = api.post(f"/api/postings/{P2}/rounds", json={"name": "기술 심층 면접"}).json()
    waiting = {(a["candidate"]["pseudonym"], a["round"]["label"]) for a in api.get("/api/applications/schedulable").json()}
    assert ("CAND-0012", "2차") in waiting  # passed 1차
    assert not {"CAND-0020", "CAND-0014"} & {p for p, _ in waiting}  # 불합격, 보류
    me = _me(api)
    refused = api.post(
        "/api/sessions",
        json={
            "application_id": rows["CAND-0020"]["application_id"],
            "round_id": second["id"],
            "mode": "remote",
            "scheduled_at": "2027-01-05T01:00:00Z",
            "interviewers": [{"interviewer_id": me["id"], "role": "lead"}],
        },
    )
    assert refused.status_code == 409 and refused.json()["detail"] == "1차 합격자만 2차 면접을 잡을 수 있습니다."
    other = api.post(
        "/api/sessions",
        json={
            "application_id": rows["CAND-0012"]["application_id"],
            "round_id": round_id(api, P1, 2),
            "mode": "remote",
            "scheduled_at": "2027-01-05T01:00:00Z",
            "interviewers": [{"interviewer_id": me["id"], "role": "lead"}],
        },
    )
    assert other.status_code == 422  # another posting's round


def test_decisions_are_for_the_panel_and_reasons_are_de_identified(api):
    name = _identity(14).name
    c3 = "0a1b2c3d-0000-4000-9000-c30000000000"  # CAND-0014, panel 이하은 + 정민재, 보류
    with api.runtime.session_factory() as db:
        me = db.scalars(select(Interviewer).where(Interviewer.employee_no == "E24017")).one()
        me.is_admin = False
        db.commit()
    outsider = api.post(f"/api/sessions/{c3}/decision", json={"decision": "passed", "reason": "좋음"})
    assert outsider.status_code == 403
    with api.runtime.session_factory() as db:
        db.scalars(select(Interviewer).where(Interviewer.employee_no == "E24017")).one().is_admin = True
        db.commit()
    decided = api.post(f"/api/sessions/{c3}/decision", json={"decision": "passed", "reason": f"{name} 지원자 비교 후 합격"}).json()
    assert decided["decision"]["current"]["reason"] == "[지원자] 지원자 비교 후 합격"
    assert decided["decision"]["current"]["revision"] == 2
    detail = api.get(f"/api/applications/{decided['session']['application_id']}/decisions").json()
    assert [d["decision"] for d in detail] == ["passed", "hold"]

    assert api.post(f"/api/sessions/{LIVE}/check-points", json={"text": "x"}).status_code == 409
    assert api.post(f"/api/sessions/{COMPLETED}/check-points", json={"text": " "}).status_code == 422
    assert api.post(f"/api/sessions/{COMPLETED}/check-points", json={"text": "x", "competency": "없음"}).status_code == 422
    point = api.post(f"/api/sessions/{COMPLETED}/check-points", json={"text": f"{_identity(3).name}의 협업 사례 확인"}).json()
    assert point["text"] == "[지원자]의 협업 사례 확인"
    ai_point = next(p for p in api.get(f"/api/sessions/{COMPLETED}/evaluation").json()["check_points"] if p["source"] == "ai")
    assert api.delete(f"/api/check-points/{ai_point['id']}").status_code == 403
    assert api.delete(f"/api/check-points/{point['id']}").status_code == 204


# --- 이전 차수 이어 보기 -----------------------------------------------------------------------


def test_earlier_scores_show_only_when_the_round_allows_it(api):
    [previous] = api.get(f"/api/sessions/{LIVE2}").json()["card"]["previous_rounds"]
    assert previous["round"]["label"] == "1차" and previous["decision"] == "passed"
    assert previous["scores_visible"] is False and previous["scores"] is None
    assert previous["decision_reason"] is None
    sources = {p["source"] for p in previous["check_points"]}
    assert sources == {"interviewer", "ai"}
    assert all(p["evidence"] for p in previous["check_points"] if p["source"] == "ai")
    assert [n["author_name"] for n in previous["notes"]] == ["김서연"]
    assert not json_keys(previous) & {"interviewer_mean", "ai_mean", "score"}

    second = round_id(api, P1, 2)
    api.patch(f"/api/rounds/{second}", json={"show_previous_scores": True})
    [previous] = api.get(f"/api/sessions/{LIVE2}").json()["card"]["previous_rounds"]
    assert previous["scores_visible"] is True and previous["decision_reason"].startswith("데이터로")
    by_name = {s["competency"]: s for s in previous["scores"]}
    assert set(by_name) == {"공정 문제 해결", "데이터 기반 분석", "공정·장비 이해", "협업과 커뮤니케이션"}
    assert all(s["interviewer_mean"] is not None for s in by_name.values())
    assert any(s["ai_mean"] is not None for s in by_name.values())


def test_earlier_rounds_reach_the_model_de_identified_only(api, monkeypatch):
    prompts: list[str] = []
    real_stream, real_generate = FakeLLM.stream, FakeLLM.generate

    def stream(self, system, prompt, **kwargs):
        prompts.append(prompt)
        return real_stream(self, system, prompt, **kwargs)

    async def generate(self, system, prompt, **kwargs):
        prompts.append(prompt)
        return await real_generate(self, system, prompt, **kwargs)

    monkeypatch.setattr(FakeLLM, "stream", stream)
    monkeypatch.setattr(FakeLLM, "generate", generate)
    identity = _identity(9)
    raw = [identity.name, *identity.phones, *identity.emails, *identity.companies, *identity.schools]

    detail = api.get(f"/api/sessions/{LIVE2}").json()
    answered = next(q for q in reversed(detail["qa_items"]) if q["answer_deidentified"])
    events = sse_events(api.post(f"/api/sessions/{LIVE2}/follow-ups", json={"qa_item_id": answered["id"]}).text)
    assert events[-1][0] == "batch.done"
    assert api.post(f"/api/sessions/{LIVE2}/carryover-questions").status_code == 200
    with api.runtime.session_factory() as db:
        earlier = [q.answer_deidentified for q in db.get(InterviewSession, CAND9_FIRST_ROUND).qa_items]
    first_sentence = earlier[0].split(". ")[0]
    followup = next(x for x in prompts if "<follow_up_request>" in x)
    carryover = next(x for x in prompts if '<qa ref="' in x)
    assert "<earlier_rounds>" in followup and first_sentence in followup
    assert '<qa ref="1차-Q1" round="1차">' in carryover and first_sentence in carryover
    assert "증착 공정 경험은 서류 대비 설명이 얕음" in carryover  # 1차 points to check
    for prompt in prompts:
        for value in raw:
            assert value not in prompt, value

    # An identifier left in an earlier round's answer stops the call before it leaves.
    with api.runtime.session_factory() as db:
        qa = db.scalars(select(QAItem).where(QAItem.session_id == CAND9_FIRST_ROUND).order_by(QAItem.seq)).first()
        qa.answer_deidentified = f"{identity.name}입니다. {identity.phones[0]}로 연락 주세요."
        db.commit()
    ours = lambda: [x for x in prompts if "<follow_up_request>" in x or '<qa ref="' in x]  # noqa: E731
    sent = len(ours())
    events = sse_events(api.post(f"/api/sessions/{LIVE2}/follow-ups", json={"qa_item_id": answered["id"]}).text)
    assert events == [("error", {"message": "답변에 식별 정보가 남아 있어 AI에 보내지 않았습니다."})]
    assert api.post(f"/api/sessions/{LIVE2}/carryover-questions").status_code == 502
    assert len(ours()) == sent  # nothing reached the model
    refused = [a for a in _audits(api, "followup.generated") + _audits(api, "carryover.generated") if (a.details or {}).get("refused")]
    assert len(refused) == 2
