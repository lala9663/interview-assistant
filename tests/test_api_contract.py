"""The API serves exactly what docs/api-contract.md and frontend/src/api/types.ts promise."""

import re
from pathlib import Path

import pytest

from interview_assistant.models import (
    ActorType,
    AvailabilitySource,
    EvaluatorType,
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
    assert len(documented) == 35
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

    sessions = api.get("/api/sessions").json()
    statuses = [x["status"] for x in sessions]
    assert statuses.count("in_progress") == 1
    assert statuses.count("completed") == 4
    assert statuses.count("scheduled") == 3

    me = api.get("/api/me").json()
    assert me["name"] == "김서연"
    dashboard = api.get("/api/dashboard").json()
    assert {row["posting"]["status"] for row in dashboard["pipeline"]} <= {"draft", "open"}
    assert dashboard["hold_count"] == 4
    assert all(
        me["id"] in [i["interviewer_id"] for i in x["interviewers"]]
        for x in dashboard["pending_my_scores"]
    )


def test_application_rows_and_stage(api):
    rows = api.get(f"/api/postings/{P1}/applications").json()
    by_pseudonym = {r["candidate"]["pseudonym"]: r for r in rows}
    assert by_pseudonym["CAND-0007"]["stage"] == "interviewing"
    assert by_pseudonym["CAND-0011"]["stage"] == "interview_scheduled"
    assert by_pseudonym["CAND-0001"]["stage"] == "screening"
    assert (
        by_pseudonym["CAND-0003"]["stage"] == "evaluated"
    )  # AI done, both panel members submitted
    assert by_pseudonym["CAND-0005"]["stage"] == "interviewed"  # kim has not submitted
    assert by_pseudonym["CAND-0007"]["top_skills"] == ["건식 식각", "FDC", "SPC"]
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
