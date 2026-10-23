"""AI layer: the pre-call guard, audit rows, scoring aggregation, fake model output shapes."""

import random

import pytest
from pydantic import TypeAdapter
from sqlalchemy import select

from interview_assistant.ai.gateway import AiCall, AiGateway
from interview_assistant.ai.guard import IdentifierInPrompt, check_prompt
from interview_assistant.ai.prompts import (
    COMPETENCY_SCHEMA,
    PROFILE_SCHEMA,
    SCORING_SCHEMA,
    SCREENING_SCHEMA,
    competency_prompt,
    profile_prompt,
    scoring_prompt,
    screening_prompt,
)
from interview_assistant.ai.scoring import _Sample, aggregate, valid_samples
from interview_assistant.ai.screening import Assessment
from interview_assistant.deid.types import KnownIdentity
from interview_assistant.domain import CandidateProfile, Competency
from interview_assistant.models import AuditLog
from interview_assistant.providers import fake_tasks
from interview_assistant.providers.fake import FakeLLM

KNOWN = KnownIdentity(
    name="강도윤",
    phones=("010-0000-0007",),
    emails=("cand0007@example.com",),
    companies=("누리테크",),
)


def test_guard_refuses_identifiers_and_contact_shapes():
    check_prompt(
        "<answer>[지원자]입니다. [회사-1]에서 일했습니다.</answer>", ["[지원자]입니다."], KNOWN
    )
    with pytest.raises(IdentifierInPrompt) as exc:
        check_prompt("p", ["저는 강도윤입니다."], KNOWN)
    assert exc.value.kinds == ("candidate",)
    with pytest.raises(IdentifierInPrompt):
        check_prompt("p", ["연락은 010 9999 1234로"], None)  # not this candidate's, still a phone
    with pytest.raises(IdentifierInPrompt):
        check_prompt("JD ... 강도윤 ...", [], KNOWN)  # undeclared candidate text in the prompt
    # A company named in the posting itself is not candidate text.
    check_prompt("<jd>누리테크 협력사 대상</jd>", ["[회사-1]"], KNOWN)


async def test_refused_calls_never_reach_the_provider_and_are_audited(db_factory):
    class Recording(FakeLLM):
        calls = 0

        async def generate(self, *args, **kwargs):
            Recording.calls += 1
            return await super().generate(*args, **kwargs)

    gateway = AiGateway({"primary": Recording(model="m")})
    call = AiCall(
        action="screening.assessed",
        prompt_version="v",
        system="s",
        prompt="저는 강도윤입니다.",
        candidate_texts=["저는 강도윤입니다."],
        known=KNOWN,
        target_type="application",
        target_id="a1",
    )
    with db_factory() as db:
        with pytest.raises(IdentifierInPrompt):
            await gateway.generate(db, call)
        [log] = db.scalars(select(AuditLog)).all()
    assert Recording.calls == 0
    assert log.action == "screening.assessed" and log.model == "m"
    assert log.details == {"refused": ["candidate"]}


async def test_successful_calls_record_model_version_and_tokens(db_factory):
    gateway = AiGateway({"primary": FakeLLM(model="m1"), "screening": FakeLLM(model="m2")})
    prompt = profile_prompt(
        document_text="[회사-1] 백엔드 엔지니어 2019.01 – 2024.12, Python, Kafka"
    )
    with db_factory() as db:
        result = await gateway.generate(
            db,
            AiCall(
                action="profile.extracted",
                prompt_version="profile-v0.1",
                system="s",
                prompt=prompt,
                role="screening",
                schema=PROFILE_SCHEMA,
                candidate_texts=[prompt],
                known=KNOWN,
            ),
        )
        [log] = db.scalars(select(AuditLog)).all()
    assert result.model == "m2" and log.model == "m2"
    assert log.actor_type.value == "ai" and log.prompt_version == "profile-v0.1"
    assert log.input_tokens > 0 and log.output_tokens > 0


def test_scoring_keeps_only_samples_with_verbatim_evidence():
    answer = "원인을 찾으려고 3주치 데이터를 비교했습니다. 결국 히터 보정으로 해결했습니다."
    raw = {
        "scores": [
            {
                "competency": "문제 해결",
                "score": 4,
                "evidence": "3주치 데이터를 비교했습니다",
                "confidence": 0.8,
            },
            {
                "competency": "문제 해결",
                "score": 5,
                "evidence": "답변에 없는 문장",
                "confidence": 0.9,
            },
            {
                "competency": "없는 역량",
                "score": 3,
                "evidence": "히터 보정으로 해결했습니다",
                "confidence": 0.7,
            },
            {
                "competency": "문제 해결",
                "score": 9,
                "evidence": "히터 보정으로 해결했습니다",
                "confidence": 0.7,
            },
        ]
    }
    kept = valid_samples(raw, answer, {"문제 해결"})
    assert [s.score for s in kept] == [4]
    assert valid_samples({"scores": "nope"}, answer, {"문제 해결"}) == []


def test_aggregate_takes_the_median_and_discounts_spread_and_rejections():
    def sample(score, confidence):
        return _Sample(competency="c", score=score, evidence=f"근거 {score}", confidence=confidence)

    assert aggregate([sample(4, 0.9), sample(4, 0.9), sample(4, 0.9)], 3) == (4, 0.9, "근거 4")
    score, confidence, evidence = aggregate([sample(3, 0.8), sample(5, 0.8), sample(4, 0.8)], 3)
    assert (score, evidence) == (4, "근거 4") and confidence == pytest.approx(0.8 * 0.5)
    assert aggregate([sample(2, 0.6)], 3)[1] == pytest.approx(0.2)


JD = "[AI센터] 백엔드\n필수 요건\n- 백엔드 개발 경력 4년 이상\n- Kubernetes, Kafka 운영\n우대: SLO, 장애 회고"
DOC = (
    "[표 3]\n기간 | 회사 | 직무\n2018.03 ~ 2025.03 | [회사-1] | 백엔드 엔지니어\n"
    "[본문]\nPython과 Kafka로 이벤트 파이프라인을 운영했습니다. 장애 회고를 도입했습니다.\n"
    "[표 2]\n2013.03 ~ 2017.02 | [학교-1] | 컴퓨터공학 | 학사"
)


@pytest.mark.parametrize("seed", range(5))
def test_fake_model_answers_every_task_in_the_schema_the_app_validates(seed):
    rng = random.Random(seed)
    draft = fake_tasks.respond(
        "CompetencyDraft",
        competency_prompt(title="t", job_family="SW", jd_text=JD, current=[]),
        rng,
    )
    assert COMPETENCY_SCHEMA["title"] == "CompetencyDraft"
    competencies = TypeAdapter(list[Competency]).validate_python(draft["competencies"])
    assert 3 <= len(competencies) <= 8 and competencies[-1].name == "협업과 커뮤니케이션"

    profile = CandidateProfile.model_validate(
        fake_tasks.respond(PROFILE_SCHEMA["title"], profile_prompt(document_text=DOC), rng)
    )
    assert profile.years_experience == 7 and {"Python", "Kafka"} <= set(profile.skills)
    assert profile.experience[0].company == "[회사-1]" and profile.education[0].school == "[학교-1]"

    assessed = fake_tasks.respond(
        SCREENING_SCHEMA["title"],
        screening_prompt(
            title="t",
            jd_text=JD,
            competencies=[c.model_dump() for c in competencies],
            profile=profile.model_dump(),
            document_text=DOC,
        ),
        rng,
    )
    assessment = Assessment.model_validate(assessed)
    assert assessment.rationale().splitlines()[1].startswith("+ ")

    answer = "원인을 찾으려고 3주치 데이터를 비교했습니다. 결국 히터 보정으로 해결했습니다."
    scored = fake_tasks.respond(
        SCORING_SCHEMA["title"],
        scoring_prompt(
            competencies=[c.model_dump() for c in competencies],
            target_competency=competencies[0].name,
            question="q",
            answer=answer,
        ),
        rng,
    )
    assert valid_samples(scored, answer, {c.name for c in competencies})
