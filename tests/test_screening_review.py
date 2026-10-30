"""서류 선별 and 평가 for real use: a structured screening rationale in plain Korean, a reason for
탈락, and AI scores kept from an interviewer until they have scored themselves."""

import json
import random

from sqlalchemy import select

from interview_assistant.ai.prompts import SCREENING_SCHEMA, profile_text, screening_prompt, years_text
from interview_assistant.ai.screening import Assessment, humanize
from interview_assistant.demo import mock_data
from interview_assistant.models import AuditLog, SessionInterviewer
from interview_assistant.providers.fake_tasks import assess_screening, jd_requirements
from tests.api_util import EVALUATING, P1
from tests.test_api_flows import upload

PROFILE = {
    "summary": "백엔드 7년. 추론 게이트웨이 구축.",
    "years_experience": 7.2,
    "skills": ["Python", "Kubernetes", "vLLM"],
    "experience": [
        {"company": "[회사-1]", "role": "백엔드 엔지니어", "period": "2019.03 – 현재", "highlights": ["게이트웨이 p95 40% 감소"]}
    ],
    "education": [{"school": "[학교-1]", "degree": "학사", "major": "컴퓨터공학"}],
    "projects": [{"name": "추론 게이트웨이", "description": "동적 배치", "tech": ["Go", "vLLM"]}],
    "certifications": [],
}
FIELD_NAMES = ("years_experience", "skills", "experience", "education", "projects", "certifications", "highlights")


def _posting(key: str) -> dict:
    return next(p for p in mock_data()["postings"] if p["key"] == key)


def _audits(api, action: str) -> list[AuditLog]:
    with api.runtime.session_factory() as db:
        return list(db.scalars(select(AuditLog).where(AuditLog.action == action)).all())


# --- structured rationale -------------------------------------------------------------------


def test_the_screening_prompt_shows_the_profile_without_json_keys():
    """With the profile as JSON, models wrote its keys into the rationale ('years_experience 7.2')."""
    prompt = screening_prompt(
        title="T", jd_text="필수 요건\n- 경력 4년 이상", competencies=[], profile=PROFILE, document_text="문서"
    )
    for name in FIELD_NAMES:
        assert name not in prompt
    assert "총 경력: 7년 2개월" in prompt and "기술: Python, Kubernetes, vLLM" in prompt
    assert "- [회사-1] · 백엔드 엔지니어 · 2019.03 – 현재" in profile_text(PROFILE)
    assert [years_text(y) for y in (7.2, 7, 0.5, None)] == ["7년 2개월", "7년", "6개월", "알 수 없음"]
    # The output schema asks per requirement, with the recommendation in its own field.
    item = SCREENING_SCHEMA["properties"]["requirements"]["items"]["properties"]
    assert set(item) == {"kind", "requirement", "verdict", "evidence", "source"}
    assert {"recommendation", "interview_checks"} <= set(SCREENING_SCHEMA["required"])


def test_field_names_that_slip_into_model_text_come_back_in_korean():
    assessment = Assessment.model_validate(
        {
            "fit_score": 70,
            "summary": "years_experience 7.2년으로 competencies의 협업 근거가 있고 skills에 Python이 있습니다.",
            "requirements": [
                {"kind": "required", "requirement": "경력 4년", "verdict": "met", "evidence": "fit_score 높음", "source": "experience의 [회사-1]"},
                {"kind": "preferred", "requirement": "  ", "verdict": "unclear", "evidence": "", "source": ""},
            ],
            "recommendation": "hold",
            "interview_checks": ["soft skills 확인", " "],
        }
    )
    assert assessment.summary == "경력 연수 7.2년으로 역량의 협업 근거가 있고 기술에 Python이 있습니다."
    assert assessment.requirements[0].evidence == "적합도 높음"
    assert assessment.requirements[0].source == "경력의 [회사-1]"
    assert len(assessment.requirements) == 1  # an empty requirement is dropped
    assert assessment.interview_checks == ["soft skills 확인"]  # English words in a sentence stay


def test_the_fake_model_judges_each_jd_requirement_in_order():
    posting = _posting("P2")
    candidate = next(c for c in mock_data()["candidates"] if c["n"] == 12)
    prompt = screening_prompt(
        title=posting["title"], jd_text=posting["jd_text"], competencies=[], profile=candidate["profile"], document_text="문서"
    )
    assessment = Assessment.model_validate(assess_screening(prompt, random.Random(0)))
    expected = jd_requirements(posting["jd_text"])
    assert [(r.kind, r.requirement) for r in assessment.requirements] == expected
    assert [k for k, _ in expected] == ["required"] * 3 + ["preferred"] * 3
    years = assessment.requirements[0]
    assert years.verdict == "met" and "7년" in years.evidence and years.source == "경력"
    assert assessment.requirements[3].source == "경력 · [회사-1]"  # vLLM: in the experience entry
    rationale = assessment.rationale()
    assert "AI 권고" not in rationale and rationale.splitlines()[0] == assessment.summary
    assert "+ 필수 충족 · 백엔드 개발 경력 4년 이상: 서류상 총 경력이 7년입니다." in rationale
    for name in FIELD_NAMES:
        assert name not in json.dumps(assessment.details(), ensure_ascii=False)


def test_an_upload_is_screened_per_requirement_with_a_separate_recommendation(api):
    response = upload(api, "이력서_문태오.docx")
    assert response.status_code == 201, response.text
    screening = response.json()["screening"]
    assert screening["prompt_version"] == "screening-v0.5"
    assert screening["status"] == "hold" and screening["reject_reason"] is None
    assert screening["recommendation"] in {"passed", "hold", "rejected"}
    assessment = screening["assessment"]
    assert assessment["requirements"] and assessment["interview_checks"]
    assert {r["kind"] for r in assessment["requirements"]} == {"required", "preferred"}
    assert all(r["verdict"] in {"met", "unmet", "unclear"} for r in assessment["requirements"])
    assert screening["rationale"].splitlines()[0] == assessment["summary"]
    assert "AI 권고" not in screening["rationale"]
    detail = api.get(f"/api/applications/{response.json()['application_id']}").json()
    assert detail["screening"]["assessment"] == assessment


def test_rows_screened_before_v0_5_keep_their_free_text(api):
    rows = {r["candidate"]["pseudonym"]: r["screening"] for r in api.get(f"/api/postings/{P1}/applications").json()}
    old = rows["CAND-0003"]
    assert old["assessment"] is None and old["recommendation"] is None
    assert old["prompt_version"] == "screening-v0.4"
    assert any(line.startswith("+ ") for line in old["rationale"].splitlines())
    new = rows["CAND-0001"]
    assert new["prompt_version"] == "screening-v0.5" and new["recommendation"] == "passed"
    assert new["assessment"]["requirements"][0]["kind"] == "required"


# --- 탈락 사유 -------------------------------------------------------------------------------


def _screening_of(api, pseudonym: str) -> dict:
    rows = api.get(f"/api/postings/{P1}/applications").json()
    return next(r["screening"] for r in rows if r["candidate"]["pseudonym"] == pseudonym)


def test_rejecting_needs_a_reason_that_is_kept_deidentified_and_audited(api):
    screening = _screening_of(api, "CAND-0006")
    url = f"/api/screenings/{screening['id']}"
    for body in ({"status": "rejected"}, {"status": "rejected", "reason": "   "}, {"status": "rejected", "reason": "가" * 501}):
        refused = api.patch(url, json=body)
        assert refused.status_code == 422, body
        assert refused.json()["detail"][0]["loc"][-1] == "reason"
    assert _screening_of(api, "CAND-0006")["status"] == "hold"

    reason = "최근 경력이 장비 유지보수 중심입니다. 문의는 010-2468-1357로 받았습니다."
    rejected = api.patch(url, json={"status": "rejected", "reason": reason}).json()
    assert rejected["status"] == "rejected"
    assert rejected["reject_reason"].startswith("최근 경력이 장비 유지보수 중심입니다.")
    assert "010-2468-1357" not in rejected["reject_reason"]  # free text is de-identified like any other
    (entry,) = _audits(api, "screening.status_changed")[-1:]
    assert entry.details == {"from": "hold", "to": "rejected", "reason": rejected["reject_reason"]}

    edited = api.patch(url, json={"status": "rejected", "reason": "공정 개발 근거가 부족합니다."}).json()
    assert edited["reject_reason"] == "공정 개발 근거가 부족합니다."
    assert _audits(api, "screening.reason_changed")[-1].details["reason"] == "공정 개발 근거가 부족합니다."

    back = api.patch(url, json={"status": "hold", "reason": "무시됨"}).json()
    assert back["status"] == "hold" and back["reject_reason"] is None
    assert _audits(api, "screening.status_changed")[-1].details == {"from": "rejected", "to": "hold"}


def test_seeded_rejections_carry_their_reason(api):
    assert _screening_of(api, "CAND-0004")["reject_reason"].startswith("반도체 단위공정 경력이 없고")


# --- AI scores after one's own -------------------------------------------------------------


def test_ai_scores_stay_hidden_from_an_interviewer_until_they_submit(api):
    ev = api.get(f"/api/sessions/{EVALUATING}/evaluation").json()
    assert ev["ai"]["status"] == "completed"
    assert ev["ai"]["hidden"] is True and ev["ai"]["scores"] == [] and ev["ai"]["summary"] == []
    mine = next(i for i in ev["interviewers"] if i["interviewer"]["name"] == "김서연")
    assert mine["submitted_at"] is None

    competencies = [c["name"] for c in ev["competency_set"]["competencies"]]
    body = {"scores": [{"competency": c, "score": 3, "comment": ""} for c in competencies]}
    after = api.put(f"/api/sessions/{EVALUATING}/scores/{mine['interviewer']['id']}", json=body).json()
    assert after["ai"]["hidden"] is False and after["ai"]["scores"] and after["ai"]["summary"]
    assert not _audits(api, "evaluation.ai_revealed")


def test_seeing_ai_scores_before_submitting_is_a_recorded_choice(api):
    revealed = api.post(f"/api/sessions/{EVALUATING}/ai-scores/reveal").json()
    assert revealed["ai"]["hidden"] is False and revealed["ai"]["scores"]
    (entry,) = _audits(api, "evaluation.ai_revealed")
    assert entry.target_id == EVALUATING and entry.details == {"before_submitting": True}
    # It sticks, and asking again records nothing more.
    assert api.get(f"/api/sessions/{EVALUATING}/evaluation").json()["ai"]["hidden"] is False
    api.post(f"/api/sessions/{EVALUATING}/ai-scores/reveal")
    assert len(_audits(api, "evaluation.ai_revealed")) == 1
    with api.runtime.session_factory() as db:
        assert db.scalar(
            select(SessionInterviewer.ai_revealed_at).where(
                SessionInterviewer.session_id == EVALUATING,
                SessionInterviewer.ai_revealed_at.is_not(None),
            )
        )


def test_whoever_is_not_on_the_panel_sees_ai_scores(api):
    """김서연 is an admin but not on CAND-0012's 1차 panel: nothing of hers to anchor, and she may
    decide the round."""
    other = "0a1b2c3d-0000-4000-9000-r1n120000000"
    ev = api.get(f"/api/sessions/{other}/evaluation").json()
    assert all(i["interviewer"]["name"] != "김서연" for i in ev["interviewers"])
    assert ev["ai"]["hidden"] is False and ev["ai"]["scores"]


def test_ai_scores_cannot_be_revealed_before_scoring_finished(api):
    from tests.api_util import SCHEDULED

    assert api.post(f"/api/sessions/{SCHEDULED}/ai-scores/reveal").status_code == 409
