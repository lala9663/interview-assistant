"""Write flows through the API on the seeded demo database, fake providers without latency."""

from pathlib import Path

import yaml
from sqlalchemy import select

from interview_assistant.models import (
    AuditLog,
    FollowUpSuggestion,
    InterviewSession,
    QAItem,
)
from tests.api_util import LIVE, P1, P3, SCHEDULED, round_id, sse_events, wait_for

ROOT = Path(__file__).resolve().parents[1]
RESUMES = ROOT / "tests" / "fixtures" / "resumes"
P2 = "b1d6a0c2-1f3e-4b8a-9c41-5e2f7a9d0002"


def _competency(name: str) -> dict:
    return {
        "name": name,
        "description": f"{name} 설명",
        "bars": {k: f"{name} {k}점" for k in "12345"},
    }


def _audits(api, action: str) -> list[AuditLog]:
    with api.runtime.session_factory() as db:
        return list(db.scalars(select(AuditLog).where(AuditLog.action == action)).all())


# --- 역량 사전 --------------------------------------------------------------------------------


def test_competency_versions_edit_approve_and_carry_presets(api):
    first = round_id(api, P1)
    created = api.post(
        f"/api/rounds/{first}/competency-sets",
        json={"competencies": [_competency("공정 문제 해결")]},
    )
    assert created.status_code == 201
    v3 = created.json()
    assert v3["version"] == 3 and v3["approved_at"] is None and v3["round_id"] == first
    # The draft starts with the approved version's questions for the competencies it keeps.
    copied = api.get(f"/api/competency-sets/{v3['id']}/preset-questions").json()
    assert [q["competency"] for q in copied] == ["공정 문제 해결", "공정 문제 해결"]

    edited = api.put(
        f"/api/competency-sets/{v3['id']}",
        json={"competencies": [_competency("공정 문제 해결"), _competency("데이터 기반 분석")]},
    )
    assert [c["name"] for c in edited.json()["competencies"]] == [
        "공정 문제 해결",
        "데이터 기반 분석",
    ]

    bad = api.put(
        f"/api/competency-sets/{v3['id']}",
        json={"competencies": [{"name": "x", "description": "", "bars": {"1": "a"}}]},
    )
    assert bad.status_code == 422
    assert bad.json()["detail"][0]["msg"] == "역량마다 1~5점 기준이 모두 필요합니다."

    question = {"competency": "데이터 기반 분석", "question": "데이터로 판단을 바꾼 사례는?", "intent": "근거"}
    added = api.post(f"/api/competency-sets/{v3['id']}/preset-questions", json=question)
    assert added.status_code == 201 and added.json()["origin"] is None
    stranger = api.post(
        f"/api/competency-sets/{v3['id']}/preset-questions", json={**question, "competency": "없는 역량"}
    )
    assert stranger.status_code == 422
    renamed = api.put(f"/api/preset-questions/{copied[1]['id']}", json={**copied[1], "question": "실패 대응 사례는?"})
    assert renamed.json()["question"] == "실패 대응 사례는?"

    approved = api.post(f"/api/competency-sets/{v3['id']}/approve").json()
    me = api.get("/api/me").json()
    assert approved["approved_by"] == me["id"] and approved["approved_at"]
    assert api.post(f"/api/competency-sets/{v3['id']}/approve").status_code == 409
    assert api.put(f"/api/competency-sets/{v3['id']}", json={"competencies": []}).status_code == 409
    # An approved version's questions are read-only too.
    assert api.post(f"/api/competency-sets/{v3['id']}/preset-questions", json=question).status_code == 409
    assert api.delete(f"/api/preset-questions/{copied[0]['id']}").status_code == 409

    posting = next(p for p in api.get("/api/postings").json() if p["id"] == P1)
    assert posting["approved_competency_set"]["version"] == 3
    # The live session stays pinned to the version approved when it started.
    assert api.get(f"/api/sessions/{LIVE}").json()["competency_set"]["version"] == 1
    # A session not started yet uses the newest approved version and its carried-over presets.
    upcoming = api.get(f"/api/sessions/{SCHEDULED}").json()
    assert upcoming["competency_set"]["version"] == 3
    assert [q["question"] for q in upcoming["preset_questions"]] == [
        copied[0]["question"],
        "실패 대응 사례는?",
        "데이터로 판단을 바꾼 사례는?",
    ]


def test_ai_draft_goes_through_the_provider_and_is_audited(api):
    drafted = api.post(f"/api/rounds/{round_id(api, P3)}/competency-sets/generate")
    assert drafted.status_code == 201
    body = drafted.json()
    assert body["version"] == 2 and body["approved_at"] is None
    names = [c["name"] for c in body["competencies"]]
    assert names[:3] == ["사용자 리서치", "인터랙션 설계", "협업과 커뮤니케이션"]  # v1 kept
    assert len(names) == 4 and all(len(c["bars"]) == 5 for c in body["competencies"])
    [log] = _audits(api, "competency_set.generated")[-1:]
    assert log.actor_type.value == "ai" and log.model == "fake-llm"
    assert log.prompt_version == "competency-v0.4" and log.target_id == body["id"]
    assert log.input_tokens and log.output_tokens


# --- 서류 선별 ------------------------------------------------------------------------------


def test_screening_status_change_is_audited_and_counted(api):
    rows = api.get(f"/api/postings/{P1}/applications").json()
    row = next(r for r in rows if r["candidate"]["pseudonym"] == "CAND-0006")
    assert row["screening"]["status"] == "hold"
    changed = api.patch(f"/api/screenings/{row['screening']['id']}", json={"status": "passed"})
    assert changed.json()["status"] == "passed"
    assert api.get("/api/dashboard").json()["hold_count"] == 1
    item = api.get("/api/activity?limit=1").json()[0]
    assert item["action"] == "screening.status_changed"
    assert item["details"] == {"from": "hold", "to": "passed"}
    assert item["target_label"] == "CAND-0006" and item["actor_label"] == "김서연"
    assert row["application_id"] in [
        a["application_id"] for a in api.get("/api/applications/schedulable").json()
    ]
    assert (
        api.patch(f"/api/screenings/{row['screening']['id']}", json={"status": "maybe"}).status_code
        == 422
    )


def _manifest_identity(file: str) -> dict:
    manifest = yaml.safe_load((RESUMES / "manifest.yaml").read_text(encoding="utf-8"))
    return next(s for s in manifest["samples"] if s["file"] == file)["identity"]


def upload(api, file: str, posting: str = P2, **fields):
    identity = _manifest_identity(file)
    form = {
        "name": identity["name"],
        "phone": "\n".join(identity.get("phones", [])),
        "email": "\n".join(identity.get("emails", [])),
        "birthdate": identity.get("birthdate", ""),
        "aliases": "\n".join(identity.get("aliases", [])),
        "addresses": "\n".join(identity.get("addresses", [])),
        "schools": "\n".join(identity.get("schools", [])),
        "companies": "\n".join(identity.get("companies", [])),
        **fields,
    }
    data = (RESUMES / file).read_bytes()
    return api.post(
        f"/api/postings/{posting}/applications", data=form, files={"file": (file, data)}
    )


def test_upload_extracts_deidentifies_screens_and_keeps_the_file(api, tmp_path):
    response = upload(api, "이력서_문태오.docx")
    assert response.status_code == 201, response.text
    result = response.json()
    assert result["candidate"]["pseudonym"] == "CAND-0021"
    assert result["screening"]["status"] == "hold"  # people decide
    assert result["screening"]["recommendation"] in {"passed", "hold", "rejected"}
    assert result["screening"]["assessment"]["requirements"]
    assert result["screening"]["model"] == "fake-llm-screening"
    assert result["document"]["format"] == "docx" and result["document"]["replacements"] > 0

    detail = api.get(f"/api/applications/{result['application_id']}").json()
    profile = detail["application"]["profile"]
    assert profile["years_experience"] > 0 and profile["skills"]
    assert any(e["company"].startswith("[회사-") for e in profile["experience"])
    assert detail["document"] == result["document"]

    stored = list((tmp_path / "uploads").rglob("*.docx"))
    assert (
        len(stored) == 1 and stored[0].read_bytes() == (RESUMES / "이력서_문태오.docx").read_bytes()
    )
    assert "문태오" not in stored[0].name

    rows = api.get(f"/api/postings/{P2}/applications").json()
    assert result["application_id"] in [r["application_id"] for r in rows]
    feed = api.get("/api/activity?limit=1").json()[0]
    assert feed["action"] == "screening.batch_completed" and feed["details"] == {"count": 1}
    actions = {
        a.action for a in _audits(api, "profile.extracted") + _audits(api, "screening.assessed")
    }
    assert actions == {"profile.extracted", "screening.assessed"}


def test_upload_reads_a_scan_with_the_ocr_engine_in_force(api):
    """The fake OCR reads nothing but stands in for the engine: a scan goes through, and the
    application records how it was read (settings revision, mode, tools, pages read by OCR)."""
    scan = upload(api, "봉채원_scan.pdf")
    assert scan.status_code == 201, scan.text
    reading = scan.json()["document"]["reading"]
    assert reading["mode"] == "auto" and reading["revision"] >= 1
    assert "fake OCR" in reading["tools"] and any(t.startswith("pdfplumber") for t in reading["tools"])
    assert reading["files"] == [
        {
            "format": "pdf", "converted_from": None, "pages": 2, "ocr_pages": [1, 2], "ocr_confidence": 0.5,
            "pictures_read": 0, "photos_dropped": 0, "garbled_pages": [],
        }
    ]  # fmt: skip


def test_upload_refuses_scans_unsupported_files_and_closed_inputs(api):
    text_only = {"impl": "standard", "options": {"mode": "text_only"}, "reason": "OCR 끄기"}
    assert api.post("/api/admin/models/document.reading/apply", json=text_only).status_code == 200
    scan = upload(api, "봉채원_scan.pdf")
    assert scan.status_code == 422
    assert "OCR" in scan.json()["detail"][0]["msg"]

    # HWP is read now; a broken one (an OLE header and nothing else) is refused as unreadable.
    hwp = api.post(
        f"/api/postings/{P2}/applications",
        data={"name": "가나다"},
        files={"file": ("x.hwp", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 64)},
    )
    assert hwp.status_code == 422 and "읽을 수 없습니다" in hwp.json()["detail"][0]["msg"]

    nameless = upload(api, "이력서_문태오.docx", name="  ")
    assert nameless.status_code == 422
    assert (
        api.get(f"/api/postings/{P2}/applications").json()[-1]["candidate"]["pseudonym"]
        != "CAND-0021"
    )


# --- 면접 -----------------------------------------------------------------------------------


def test_schedule_a_session_validates_the_panel(api):
    app_id = next(a["application_id"] for a in api.get("/api/applications/schedulable").json())
    people = [i["id"] for i in api.get("/api/interviewers").json()]
    body = {"application_id": app_id, "mode": "remote", "scheduled_at": "2026-12-01T01:00:00Z"}
    two_leads = api.post(
        "/api/sessions",
        json={**body, "interviewers": [{"interviewer_id": p, "role": "lead"} for p in people[:2]]},
    )
    assert two_leads.status_code == 422
    assert two_leads.json()["detail"][0]["msg"] == "주관 면접관은 한 명이어야 합니다."
    naive = api.post(
        "/api/sessions",
        json={
            **body,
            "scheduled_at": "2026-12-01T10:00:00",
            "interviewers": [{"interviewer_id": people[0], "role": "lead"}],
        },
    )
    assert naive.status_code == 422

    panel = [
        {"interviewer_id": people[0], "role": "lead"},
        {"interviewer_id": people[1], "role": "panel"},
    ]
    created = api.post("/api/sessions", json={**body, "interviewers": panel})
    assert created.status_code == 201
    summary = created.json()
    assert summary["status"] == "scheduled" and summary["ai_scoring"] == "not_started"
    assert summary["scheduled_at"] == "2026-12-01T01:00:00.000Z"
    assert summary["interviewers"][0]["role"] == "lead"
    assert api.post("/api/sessions", json={**body, "interviewers": panel}).status_code == 409
    assert app_id not in [
        a["application_id"] for a in api.get("/api/applications/schedulable").json()
    ]


def test_manual_mode_interview_from_consent_to_scores(api):
    """No recording consent: no transcript, answers typed by the interviewer."""
    assert (
        api.post(
            f"/api/sessions/{SCHEDULED}/consent", json={"consent_recording": False}
        ).status_code
        == 200
    )
    started = api.post(f"/api/sessions/{SCHEDULED}/start").json()
    assert (
        started["session"]["status"] == "in_progress"
        and started["session"]["has_recording"] is False
    )
    assert (
        api.post(f"/api/sessions/{SCHEDULED}/consent", json={"consent_recording": True}).status_code
        == 409
    )

    preset = started["preset_questions"][0]
    qa = api.post(
        f"/api/sessions/{SCHEDULED}/qa-items",
        json={
            "question": preset["question"],
            "question_source": "preset",
            "preset_question_id": preset["id"],
        },
    ).json()
    assert qa["seq"] == 1 and qa["answer_deidentified"] is None
    answered = api.patch(
        f"/api/qa-items/{qa['id']}",
        json={"answer_text": "챔버별로 나눠 보고 DOE로 3번 검증했습니다. 수율이 2%p 올랐습니다."},
    ).json()
    assert answered["answer_deidentified"].startswith("챔버별로") and answered["answered_at"]
    assert "answer_text" not in answered

    with api.runtime.session_factory() as db:
        stored = db.get(QAItem, qa["id"])
        assert (
            stored.preset_question_id == preset["id"]
            and stored.target_competency == preset["competency"]
        )

    other = api.post(
        f"/api/sessions/{SCHEDULED}/qa-items",
        json={"question": "다른 질문", "question_source": "preset", "preset_question_id": "nope"},
    )
    assert other.status_code == 422

    ended = api.post(f"/api/sessions/{SCHEDULED}/end").json()
    assert ended["session"]["status"] == "completed" and ended["session"]["ended_at"]
    ev = wait_for(
        api, f"/api/sessions/{SCHEDULED}/evaluation", lambda b: b["ai"]["status"] == "completed"
    )
    assert ev["ai"]["model"] == "fake-llm" and ev["ai"]["prompt_version"] == "score-v0.4"
    # 김서연 is on the panel and has not scored yet: AI scores stay hidden until she chooses to see them.
    assert ev["ai"]["hidden"] and ev["ai"]["scores"] == []
    ev = api.post(f"/api/sessions/{SCHEDULED}/ai-scores/reveal").json()
    [score] = ev["ai"]["scores"]
    assert score["qa_item_id"] == qa["id"] and score["competency"] == preset["competency"]
    assert score["evidence"] in answered["answer_deidentified"]

    names = [c["name"] for c in ev["competency_set"]["competencies"]]
    me = api.get("/api/me").json()
    missing = api.put(
        f"/api/sessions/{SCHEDULED}/scores/{me['id']}",
        json={"scores": [{"competency": names[0], "score": 3, "comment": ""}]},
    )
    assert missing.status_code == 422 and names[1] in missing.json()["detail"][0]["msg"]
    out_of_range = api.put(
        f"/api/sessions/{SCHEDULED}/scores/{me['id']}",
        json={"scores": [{"competency": n, "score": 6, "comment": ""} for n in names]},
    )
    assert out_of_range.status_code == 422
    outsider = next(i["id"] for i in api.get("/api/interviewers").json() if i["name"] == "최유진")
    assert (
        api.put(f"/api/sessions/{SCHEDULED}/scores/{outsider}", json={"scores": []}).status_code
        == 409
    )

    first = api.put(
        f"/api/sessions/{SCHEDULED}/scores/{me['id']}",
        json={"scores": [{"competency": n, "score": 3, "comment": "보통"} for n in names]},
    )
    again = api.put(
        f"/api/sessions/{SCHEDULED}/scores/{me['id']}",
        json={"scores": [{"competency": n, "score": 4, "comment": ""} for n in names]},
    ).json()
    assert first.status_code == 200
    mine = next(i for i in again["interviewers"] if i["interviewer"]["id"] == me["id"])
    assert [x["score"] for x in mine["scores"]] == [4] * len(names)  # replaced, not appended
    assert mine["submitted_at"] and all(x["evidence"] is None for x in mine["scores"])
    summary = next(x for x in api.get("/api/sessions").json() if x["id"] == SCHEDULED)
    assert me["id"] in summary["submitted_interviewer_ids"]


def test_live_interview_transcript_follow_ups_and_scoring(api):
    detail = api.get(f"/api/sessions/{LIVE}").json()
    preset = next(q for q in detail["preset_questions"] if q["competency"] == "공정·장비 이해")
    qa = api.post(
        f"/api/sessions/{LIVE}/qa-items",
        json={
            "question": preset["question"],
            "question_source": "preset",
            "preset_question_id": preset["id"],
        },
    ).json()
    assert qa["seq"] == 4

    # The simulated candidate answers through the fake STT; the answer closes by itself.
    detail = wait_for(
        api, f"/api/sessions/{LIVE}", lambda b: b["qa_items"][-1]["answer_deidentified"]
    )
    answer = detail["qa_items"][-1]["answer_deidentified"]
    assert answer.startswith("식각 공정에서는 하부 전극 온도 분포가 가장 컸습니다.")
    segments = api.get(f"/api/sessions/{LIVE}/transcript").json()["segments"]
    mine = [s for s in segments if s["qa_item_id"] == qa["id"]]
    assert mine[0]["speaker"] == "interviewer" and mine[0]["text"] == preset["question"]
    assert [s["speaker"] for s in mine[1:]] == ["candidate"] * 4
    assert " ".join(s["text"] for s in mine[1:]) == answer
    assert all(s["is_final"] and s["end_ms"] >= s["start_ms"] for s in mine)

    stream = api.post(f"/api/sessions/{LIVE}/follow-ups", json={"qa_item_id": qa["id"]})
    events = sse_events(stream.text)
    names = [e for e, _ in events]
    assert names[0] == "batch.start" and names[-1] == "batch.done"
    assert names.count("suggestion.start") == names.count("suggestion.done")
    batch = events[0][1]
    assert batch["model"] == "fake-llm" and batch["prompt_version"] == "followup-v0.4"
    # Question-bank suggestions come first, finished at once; then the model's three, streamed.
    sources = [d["source"] for e, d in events if e == "suggestion.done"]
    assert sources == ["bank"] * (len(sources) - 3) + ["ai"] * 3
    done = [d for e, d in events if e == "suggestion.done" and d["source"] == "ai"]
    for d in done:
        streamed = "".join(
            x["text"]
            for e, x in events
            if e == "suggestion.delta" and x["suggestion_id"] == d["suggestion_id"]
        )
        assert streamed == d["question"]
        assert d["grounding"] and d["grounding"] in answer
        assert d["rationale"]
    assert done[0]["competency"] == "공정·장비 이해"  # the question's own competency first
    with api.runtime.session_factory() as db:
        stored = db.scalars(
            select(FollowUpSuggestion).where(FollowUpSuggestion.batch_id == batch["batch_id"])
        ).all()
        assert sorted(x.position for x in stored) == list(range(len(sources)))

    chosen = done[1]
    used = api.post(
        f"/api/sessions/{LIVE}/qa-items",
        json={
            "question": chosen["question"] + " 구체적으로요.",
            "question_source": "ai_suggested",
            "suggestion": {
                "batch_id": batch["batch_id"],
                "suggestion_id": chosen["suggestion_id"],
                "edited": True,
                "original_question": chosen["question"],
            },
        },
    )
    assert used.status_code == 201
    with api.runtime.session_factory() as db:
        row = db.get(FollowUpSuggestion, chosen["suggestion_id"])
        assert (
            row.used_qa_item_id == used.json()["id"]
            and row.edited
            and row.question == chosen["question"]
        )
        assert db.get(QAItem, used.json()["id"]).target_competency == chosen["competency"]
    again = api.post(
        f"/api/sessions/{LIVE}/qa-items",
        json={
            "question": "x",
            "question_source": "ai_suggested",
            "suggestion": {
                "batch_id": batch["batch_id"],
                "suggestion_id": chosen["suggestion_id"],
                "edited": False,
                "original_question": "x",
            },
        },
    )
    assert again.status_code == 409
    unknown = api.post(
        f"/api/sessions/{LIVE}/qa-items",
        json={
            "question": "x",
            "question_source": "ai_suggested",
            "suggestion": {
                "batch_id": "b",
                "suggestion_id": "s",
                "edited": False,
                "original_question": "x",
            },
        },
    )
    assert (
        unknown.status_code == 422
        and unknown.json()["detail"][0]["msg"] == "알 수 없는 제안입니다."
    )

    note = api.post(f"/api/sessions/{LIVE}/notes", json={"content": "설명이 구체적임"})
    assert note.status_code == 201 and note.json()["author_id"] == api.get("/api/me").json()["id"]

    ended = api.post(f"/api/sessions/{LIVE}/end")
    assert ended.status_code == 200
    with api.runtime.session_factory() as db:
        last = db.scalars(
            select(QAItem).where(QAItem.session_id == LIVE).order_by(QAItem.seq.desc())
        ).first()
        assert last.answer_deidentified  # the answer in progress was closed with what was heard
    ev = wait_for(
        api, f"/api/sessions/{LIVE}/evaluation", lambda b: b["ai"]["status"] == "completed"
    )
    answered = {q["id"]: q["answer_deidentified"] for q in ev["qa_items"]}
    assert ev["ai"]["hidden"]  # 김서연 has not scored this session yet
    ev = api.post(f"/api/sessions/{LIVE}/ai-scores/reveal").json()
    assert ev["ai"]["scores"]
    for score in ev["ai"]["scores"]:
        assert score["evidence"] in answered[score["qa_item_id"]]
        assert 0 <= score["confidence"] <= 1
    assert len(_audits(api, "score.ai_sample")) >= 3 * len(ev["ai"]["scores"]) // 2
    assert (
        api.post(
            f"/api/sessions/{LIVE}/qa-items",
            json={"question": "q", "question_source": "interviewer"},
        ).status_code
        == 409
    )


def test_follow_ups_for_an_unanswered_question_is_an_error_event(api):
    detail = api.get(f"/api/sessions/{LIVE}").json()
    pending = detail["qa_items"][-1]
    assert pending["answer_deidentified"] is None
    events = sse_events(
        api.post(f"/api/sessions/{LIVE}/follow-ups", json={"qa_item_id": pending["id"]}).text
    )
    assert events == [("error", {"message": "답변이 아직 없어 꼬리질문을 만들 수 없습니다."})]


def test_server_restart_resumes_running_ai_scoring(api):
    c4 = "0a1b2c3d-0000-4000-9000-c40000000000"
    ev = wait_for(api, f"/api/sessions/{c4}/evaluation", lambda b: b["ai"]["status"] == "completed")
    assert len(ev["ai"]["scores"]) == 3
    with api.runtime.session_factory() as db:
        assert db.get(InterviewSession, c4).ai_scoring_finished_at is not None


# --- 스케줄 ---------------------------------------------------------------------------------


def test_availability_crud_and_suggestions_skip_booked_interviews(api):
    people = {i["name"]: i["id"] for i in api.get("/api/interviewers").json()}
    choi, kim = people["최유진"], people["김서연"]
    window = {"start_at": "2027-03-02T00:00:00Z", "end_at": "2027-03-02T04:00:00Z"}  # 09-13 KST
    assert (
        api.post(
            "/api/availabilities",
            json={
                "interviewer_id": choi,
                "start_at": window["end_at"],
                "end_at": window["start_at"],
            },
        ).status_code
        == 422
    )
    a = api.post("/api/availabilities", json={"interviewer_id": choi, **window}).json()
    b = api.post("/api/availabilities", json={"interviewer_id": kim, **window}).json()
    assert a["source"] == "manual"
    listed = api.get("/api/availabilities?from=2027-03-02T00:00:00Z&to=2027-03-03T00:00:00Z").json()
    assert {x["id"] for x in listed} == {a["id"], b["id"]}

    ask = {
        "interviewer_ids": [choi, kim],
        "from": "2027-03-01T00:00:00Z",
        "to": "2027-03-03T00:00:00Z",
        "duration_minutes": 60,
    }
    before = [x["start_at"] for x in api.post("/api/schedule/suggestions", json=ask).json()]
    assert before == [
        "2027-03-02T00:00:00.000Z",
        "2027-03-02T01:00:00.000Z",
        "2027-03-02T02:00:00.000Z",
        "2027-03-02T03:00:00.000Z",
    ]

    app_id = next(x["application_id"] for x in api.get("/api/applications/schedulable").json())
    api.post(
        "/api/sessions",
        json={
            "application_id": app_id,
            "mode": "onsite",
            "scheduled_at": "2027-03-02T01:00:00Z",
            "interviewers": [{"interviewer_id": kim, "role": "lead"}],
        },
    )
    after = [x["start_at"] for x in api.post("/api/schedule/suggestions", json=ask).json()]
    assert "2027-03-02T01:00:00.000Z" not in after and len(after) == 3

    assert api.delete(f"/api/availabilities/{a['id']}").status_code == 204
    assert api.delete(f"/api/availabilities/{a['id']}").status_code == 404
    assert (
        api.post("/api/schedule/suggestions", json={**ask, "interviewer_ids": []}).status_code
        == 422
    )


def _at(hm: str) -> str:
    """2027-03-02 at hh:mm UTC, as the API writes it."""
    return f"2027-03-02T{hm}:00.000Z"


def _mine(api, interviewer_id: str) -> list[tuple[str, str]]:
    listed = api.get(f"/api/availabilities?from={_at('00:00')}&to=2027-03-03T00:00:00Z").json()
    return [(x["start_at"], x["end_at"]) for x in listed if x["interviewer_id"] == interviewer_id]


def _details(api, action: str, key: str) -> list[dict]:
    return [x.details for x in _audits(api, action) if key in (x.details or {})]


def test_an_interviewers_blocks_merge_when_they_touch_and_never_overlap(api):
    people = {i["name"]: i["id"] for i in api.get("/api/interviewers").json()}
    choi, kim = people["최유진"], people["김서연"]

    def add(who: str, start: str, end: str) -> dict:
        body = {"interviewer_id": who, "start_at": _at(start), "end_at": _at(end)}
        response = api.post("/api/availabilities", json=body)
        assert response.status_code == 201
        return response.json()

    # One hour per click, as the grid did: 10:00, 10:30 (overlaps), 11:30 (touches) KST.
    first = add(choi, "01:00", "02:00")
    second = add(choi, "01:30", "02:30")
    third = add(choi, "02:30", "03:30")
    assert (third["start_at"], third["end_at"]) == (_at("01:00"), _at("03:30"))
    assert _mine(api, choi) == [(_at("01:00"), _at("03:30"))]
    # Another interviewer's block at the same time stays theirs.
    add(kim, "01:00", "02:00")
    assert _mine(api, kim) == [(_at("01:00"), _at("02:00"))]
    created = [x.details for x in _audits(api, "availability.created") if x.target_id == choi]
    assert created[-3:] == [
        {"availability_id": first["id"]},
        {"availability_id": second["id"], "merged": [first["id"]]},
        {"availability_id": third["id"], "merged": [second["id"]]},
    ]

    # A block apart, then the first one grown down to it: one block again, the id kept.
    apart = add(choi, "05:00", "06:00")
    grown = api.patch(f"/api/availabilities/{third['id']}", json={"end_at": _at("05:00")})
    assert grown.status_code == 200 and grown.json()["id"] == third["id"]
    assert _mine(api, choi) == [(_at("01:00"), _at("06:00"))]
    [log] = [x for x in _audits(api, "availability.updated") if x.target_id == choi]
    assert log.target_type == "interviewer" and log.actor_id is not None
    assert log.details == {
        "availability_id": third["id"],
        "from": [_at("01:00"), _at("03:30")],
        "to": [_at("01:00"), _at("06:00")],
        "merged": [apart["id"]],
    }

    # Moved (both ends), a no-op (no audit row), backwards, unknown.
    moved = {"start_at": _at("02:00"), "end_at": _at("04:00")}
    shrunk = api.patch(f"/api/availabilities/{third['id']}", json=moved).json()
    assert (shrunk["start_at"], shrunk["end_at"]) == (_at("02:00"), _at("04:00"))
    count = len(_audits(api, "availability.updated"))
    assert api.patch(f"/api/availabilities/{third['id']}", json={}).status_code == 200
    assert len(_audits(api, "availability.updated")) == count
    backwards = api.patch(f"/api/availabilities/{third['id']}", json={"end_at": _at("02:00")})
    assert backwards.status_code == 422
    assert api.patch("/api/availabilities/nope", json={}).status_code == 404


def test_clearing_part_of_a_block_shortens_splits_or_deletes_it(api):
    choi = next(i["id"] for i in api.get("/api/interviewers").json() if i["name"] == "최유진")
    body = {"interviewer_id": choi, "start_at": _at("00:00"), "end_at": _at("04:00")}
    block = api.post("/api/availabilities", json=body).json()

    def clear(start: str, end: str, id_: str = block["id"]):
        cut = {"start_at": _at(start), "end_at": _at(end)}
        return api.post(f"/api/availabilities/{id_}/clear", json=cut)

    # The middle hour: two blocks, the first keeps the id.
    left, right = clear("01:00", "02:00").json()
    assert left["id"] == block["id"] and right["id"] != block["id"]
    assert _mine(api, choi) == [(_at("00:00"), _at("01:00")), (_at("02:00"), _at("04:00"))]
    assert _details(api, "availability.created", "split_from") == [
        {"availability_id": right["id"], "split_from": block["id"]}
    ]
    [updated] = _details(api, "availability.updated", "cleared")
    assert updated["to"] == [_at("00:00"), _at("01:00")]

    # Outside the block: nothing changes. The rest of it: the block goes.
    assert [x["id"] for x in clear("05:00", "06:00").json()] == [block["id"]]
    assert clear("00:00", "01:30").json() == []
    assert _mine(api, choi) == [(_at("02:00"), _at("04:00"))]
    assert _details(api, "availability.deleted", "cleared") == [
        {"availability_id": block["id"], "cleared": [_at("00:00"), _at("01:30")]}
    ]
    assert clear("00:00", "01:00").status_code == 404
    assert clear("03:00", "02:00", right["id"]).status_code == 422
