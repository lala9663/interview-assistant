"""The API serves exactly what docs/api-contract.md and frontend/src/api/types.ts promise."""

import re
from pathlib import Path

import pytest

from interview_assistant.models import (
    ActorType,
    ApplicationChannel,
    AvailabilitySource,
    CheckPointSource,
    DecisionStatus,
    EvaluatorType,
    IntakeEventType,
    IntakeStatus,
    InterviewerRole,
    PostingStatus,
    QuestionSource,
    ScreeningStatus,
    SessionMode,
    SessionStatus,
)
from tests.api_util import (
    COMPLETED,
    LIVE,
    P1,
    P3,
    SCHEDULED,
    get_paths,
    json_keys,
    sse_events,
    walk_json,
)

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = (ROOT / "docs" / "api-contract.md").read_text(encoding="utf-8")
TYPES = (ROOT / "frontend" / "src" / "api" / "types.ts").read_text(encoding="utf-8")


def _shape(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "{}", path.split("?")[0])


def test_every_contract_endpoint_is_served(api):
    documented = {
        (method, _shape(path))
        for method, path in re.findall(
            r"^\| (GET|POST|PUT|PATCH|DELETE) \| `([^`]+)`", CONTRACT, re.M
        )
    }
    served = {
        (method.upper(), _shape(path))
        for path, ops in api.app.openapi()["paths"].items()
        if path.startswith("/api")
        for method in ops
    }
    assert len(documented) == 87
    assert documented == served


@pytest.mark.parametrize(
    ("ts_name", "enum"),
    [
        ("POSTING_STATUSES", PostingStatus),
        ("SCREENING_STATUSES", ScreeningStatus),
        ("SESSION_MODES", SessionMode),
        ("SESSION_STATUSES", SessionStatus),
        ("INTERVIEWER_ROLES", InterviewerRole),
        ("QUESTION_SOURCES", QuestionSource),
        ("EVALUATOR_TYPES", EvaluatorType),
        ("AVAILABILITY_SOURCES", AvailabilitySource),
        ("ACTOR_TYPES", ActorType),
        ("APPLICATION_CHANNELS", ApplicationChannel),
        ("INTAKE_EVENT_TYPES", IntakeEventType),
        ("INTAKE_STATUSES", IntakeStatus),
        ("DECISION_STATUSES", DecisionStatus),
        ("CHECK_POINT_SOURCES", CheckPointSource),
    ],
)
def test_enum_values_match_the_frontend(ts_name, enum):
    m = re.search(rf"export const {ts_name} = \[([^\]]*)\] as const", TYPES)
    assert m, ts_name
    assert re.findall(r"'([^']+)'", m.group(1)) == [e.value for e in enum]


def test_every_get_answers_and_datetimes_are_utc_milliseconds(api):
    iso = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$")
    for path in get_paths(api):
        response = api.get(path)
        assert response.status_code == 200, (path, response.text)
        if path.endswith("/stream"):
            continue
        for key, value in walk_json(response.json()):
            if key.endswith(("_at", ".occurred_at")) and isinstance(value, str):
                assert iso.match(value), (path, key, value)


def test_seeded_dashboard_matches_the_mock_dataset(api):
    postings = {p["title"]: p for p in api.get("/api/postings").json()}
    assert len(postings) == 3
    p1 = postings["메모리 공정개발 엔지니어 (경력)"]
    assert p1["counts"]["applications"] == 11
    assert p1["approved_competency_set"]["version"] == 1
    assert p1["latest_competency_set"]["version"] == 2
    assert "jd_text" not in p1

    assert [r["label"] for r in p1["rounds"]] == ["1차", "2차"]
    assert [r["name"] for r in p1["rounds"]] == ["직무 면접", "임원 면접"]
    assert [r["label"] for r in postings["AI 플랫폼 백엔드 엔지니어"]["rounds"]] == ["1차"]

    sessions = api.get("/api/sessions").json()
    statuses = [x["status"] for x in sessions]
    assert statuses.count("in_progress") == 2
    assert statuses.count("completed") == 9
    assert statuses.count("scheduled") == 3
    by_round = {(x["round"]["label"], x["status"]) for x in sessions if x["posting"]["id"] == P1}
    assert {("2차", "scheduled"), ("2차", "in_progress"), ("2차", "completed")} <= by_round

    me = api.get("/api/me").json()
    assert me["name"] == "김서연"
    dashboard = api.get("/api/dashboard").json()
    assert {row["posting"]["status"] for row in dashboard["pipeline"]} <= {"draft", "open"}
    assert dashboard["hold_count"] == 2
    pending = {(x["candidate"]["pseudonym"], x["round"]["label"], x["status"]) for x in dashboard["pending_decisions"]}
    assert pending == {("CAND-0001", "2차", "deciding"), ("CAND-0014", "1차", "hold")}
    pipeline = {row["posting"]["title"]: row["counts"] for row in dashboard["pipeline"]}
    p1_rounds = pipeline["메모리 공정개발 엔지니어 (경력)"]["rounds"]
    assert [(r["round"]["label"], r["reached"], r["passed"]) for r in p1_rounds] == [("1차", 7, 3), ("2차", 3, 0)]
    assert pipeline["AI 플랫폼 백엔드 엔지니어"]["final"] == 1
    assert all(
        me["id"] in [i["interviewer_id"] for i in x["interviewers"]]
        for x in dashboard["pending_my_scores"]
    )


def test_application_rows_and_stage(api):
    rows = api.get(f"/api/postings/{P1}/applications").json()
    by_pseudonym = {r["candidate"]["pseudonym"]: r for r in rows}

    def now(pseudonym):
        stage = by_pseudonym[pseudonym]["stage"]
        return stage["kind"], (stage["round"] or {}).get("label"), stage["status"]

    def trail(pseudonym):
        return [s["status"] for s in by_pseudonym[pseudonym]["progress"]]

    assert now("CAND-0007") == ("round", "1차", "in_progress")
    assert now("CAND-0011") == ("round", "1차", "scheduled")
    assert now("CAND-0002") == ("round", "1차", "waiting")  # passed screening, nothing booked
    assert now("CAND-0005") == ("round", "1차", "evaluating")  # kim has not submitted
    assert now("CAND-0003") == ("round", "2차", "scheduled")  # passed 1차, 2차 tomorrow
    assert now("CAND-0009") == ("round", "2차", "in_progress")
    assert now("CAND-0001") == ("round", "2차", "deciding")  # both submitted, no decision yet
    assert now("CAND-0004") == ("screening", None, "rejected")
    assert trail("CAND-0001") == ["passed", "passed", "deciding", None]
    assert trail("CAND-0004") == ["rejected", None, None, None]
    assert [s["kind"] for s in by_pseudonym["CAND-0001"]["progress"]] == ["screening", "round", "round", "final"]
    assert by_pseudonym["CAND-0007"]["top_skills"] == ["건식 식각", "FDC", "SPC"]
    p2 = {r["candidate"]["pseudonym"]: r for r in api.get("/api/postings/b1d6a0c2-1f3e-4b8a-9c41-5e2f7a9d0002/applications").json()}
    assert p2["CAND-0012"]["stage"]["kind"] == "final"  # passed the only round
    assert p2["CAND-0020"]["stage"]["status"] == "rejected" and p2["CAND-0014"]["stage"]["status"] == "hold"
    assert api.get(f"/api/postings/{P3}/applications").json() == []


def test_session_detail_has_card_presets_and_pinned_set(api):
    detail = api.get(f"/api/sessions/{LIVE}").json()
    assert detail["session"]["has_recording"] is True
    assert detail["card"]["candidate"]["pseudonym"] == "CAND-0007"
    assert detail["card"]["candidate"]["consent_recording"] is True
    assert detail["card"]["screening"]["fit_score"] == 89
    assert detail["competency_set"]["version"] == 1
    assert len(detail["preset_questions"]) == 8
    assert [q["seq"] for q in detail["qa_items"]] == [1, 2, 3]
    assert detail["interviewers"][0]["role"] == "lead"
    assert detail["notes"][0]["content"].startswith("엣지 링")
    assert detail["round"] == {
        "id": detail["session"]["round_id"],
        "position": 1,
        "label": "1차",
        "name": "직무 면접",
        "is_last": False,
        "rounds": 2,
        "show_previous_scores": False,
    }
    assert detail["card"]["previous_rounds"] == [] and detail["carryover_questions"] == []


def test_evaluation_keeps_ai_and_interviewer_scores_apart(api):
    ev = api.get(f"/api/sessions/{COMPLETED}/evaluation").json()
    assert ev["ai"]["status"] == "completed"
    assert ev["ai"]["samples"] == 3
    assert all(
        x["evaluator_type"] == "ai" and x["qa_item_id"] and x["evidence"]
        for x in ev["ai"]["scores"]
    )
    assert all(x["confidence"] is not None for x in ev["ai"]["scores"])
    for person in ev["interviewers"]:
        assert all(
            x["evaluator_type"] == "interviewer" and x["qa_item_id"] is None
            for x in person["scores"]
        )
    summary = {s["competency"]: s for s in ev["ai"]["summary"]}
    for name, row in summary.items():
        items = [x["score"] for x in ev["ai"]["scores"] if x["competency"] == name]
        assert row["item_count"] == len(items)
        assert row["score"] == round(sum(items) / len(items) + 1e-9, 1)
    # Nothing anywhere combines the two.
    assert not json_keys(ev) & {"total", "overall", "combined", "average", "weighted"}


def test_activity_has_labels_and_only_feed_actions(api):
    feed = api.get("/api/activity?limit=50").json()
    assert feed and all(item["actor_label"] for item in feed)
    assert {item["action"] for item in feed} <= {
        "screening.batch_completed",
        "screening.status_changed",
        "competency_set.generated",
        "competency_set.created",
        "competency_set.updated",
        "competency_set.approved",
        "consent.recorded",
        "session.scheduled",
        "session.started",
        "session.completed",
        "qa.created",
        "score.ai_started",
        "score.ai_completed",
        "score.interviewer_submitted",
        "round.decided",
        "round.decision_changed",
    }
    labels = {item["target_label"] for item in feed}
    assert "CAND-0007" in labels
    assert any(label and label.endswith(" v2") for label in labels)


def test_errors_use_the_fastapi_shape_in_korean(api):
    missing = api.get("/api/postings/nope")
    assert missing.status_code == 404
    assert missing.json() == {"detail": "공고를 찾을 수 없습니다."}
    assert api.get("/api/sessions/nope").json()["detail"] == "면접을 찾을 수 없습니다."

    started = api.post(f"/api/sessions/{LIVE}/start")
    assert started.status_code == 409
    assert started.json()["detail"] == "예정된 면접만 시작할 수 있습니다."

    bad = api.post(
        f"/api/sessions/{LIVE}/qa-items", json={"question": "  ", "question_source": "interviewer"}
    )
    assert bad.status_code == 422
    assert bad.json()["detail"] == [
        {"loc": ["body", "question"], "msg": "질문을 입력하세요.", "type": "value_error"}
    ]

    wrong = api.post(f"/api/sessions/{SCHEDULED}/consent", json={})
    assert wrong.status_code == 422
    [error] = wrong.json()["detail"]
    assert error["loc"] == ["body", "consent_recording"] and error["msg"] == "필수 항목입니다."

    enum = api.get("/api/sessions?status=bogus")
    assert enum.status_code == 422
    assert enum.json()["detail"][0]["msg"].startswith("허용되지 않는 값입니다.")


def test_transcript_stream_of_a_finished_session_sends_status_and_ends(api):
    response = api.get(f"/api/sessions/{COMPLETED}/transcript/stream")
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"
    assert sse_events(response.text) == [
        ("status", {"recording": "stopped", "stt": "off", "latency_ms": None})
    ]


def test_step_statuses_match_the_frontend():
    from interview_assistant.interviews import STEP_STATUSES

    m = re.search(r"export const STEP_STATUSES = \[([^\]]*)\] as const", TYPES)
    assert m and re.findall(r"'([^']+)'", m.group(1)) == list(STEP_STATUSES)
