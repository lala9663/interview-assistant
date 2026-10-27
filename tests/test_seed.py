"""The demo seed: same shape as the frontend mock, fictional identities sealed, tokens registered."""

from sqlalchemy import func, select

from interview_assistant.deid.service import DeidService
from interview_assistant.demo import mock_data
from interview_assistant.demo.seed import fake_identity
from interview_assistant.models import (
    AiScoringStatus,
    Candidate,
    CheckPoint,
    DeidMapping,
    FollowUpSuggestion,
    Interviewer,
    InterviewRound,
    InterviewSession,
    JobPosting,
    PresetQuestion,
    RoundDecision,
    SessionStatus,
)
from tests.conftest import api_settings, file_session_factory


def test_seed_matches_the_mock_dataset_and_seals_fictional_identities(seeded_db, tmp_path):
    path, key = seeded_db
    factory = file_session_factory(path)
    deid = DeidService.from_settings(api_settings(path, key, tmp_path))
    with factory() as db:
        count = lambda model: db.scalar(select(func.count()).select_from(model))  # noqa: E731
        assert (count(JobPosting), count(Candidate), count(Interviewer)) == (3, 20, 5)
        statuses = db.scalars(select(InterviewSession.status)).all()
        assert statuses.count(SessionStatus.in_progress) == 2
        assert statuses.count(SessionStatus.completed) == 9
        assert statuses.count(SessionStatus.scheduled) == 3
        rounds = {(r.posting.title, r.position): r.name for r in db.scalars(select(InterviewRound))}
        assert sorted(rounds.values()) == ["면접", "임원 면접", "직무 면접", "직무 면접"]
        assert count(PresetQuestion) == 8 + 6 + 6
        assert count(FollowUpSuggestion) == 7 * 3

        sessions = db.scalars(select(InterviewSession)).all()
        scoring = sorted(
            s.ai_scoring_status.value for s in sessions if s.status is SessionStatus.completed
        )
        assert scoring == ["completed"] * 8 + ["running"]
        assert all(s.competency_set is None or s.competency_set.round is s.round for s in sessions)
        decisions = sorted((d.decision.value, d.revision) for d in db.scalars(select(RoundDecision)))
        assert decisions == [("hold", 1), ("hold", 1), ("passed", 1), ("passed", 1), ("passed", 1), ("passed", 1), ("rejected", 2)]
        points = db.scalars(select(CheckPoint)).all()
        assert {p.source.value for p in points} == {"ai", "interviewer"}
        for p in points:
            if p.source.value == "ai":
                assert p.evidence and p.evidence in (p.qa_item.answer_deidentified or "")
        assert all(s.recording_uri for s in sessions if s.status is not SessionStatus.scheduled)
        assert all(
            s.ai_scoring_status is AiScoringStatus.not_started
            for s in sessions
            if s.status is SessionStatus.scheduled
        )

        data = {c["n"]: c for c in mock_data()["candidates"]}
        cand = db.scalars(select(Candidate).where(Candidate.pseudonym == "CAND-0007")).one()
        identity = deid.identity(cand)
        assert identity == fake_identity(7, data[7]["profile"])
        assert identity.phones[0].startswith("010-0000-") and identity.emails[0].endswith(
            "@example.com"
        )
        tokens = set(
            db.scalars(select(DeidMapping.token).where(DeidMapping.candidate_id == cand.id))
        )
        assert {"[지원자]", "[회사-1]", "[회사-2]", "[학교-1]"} <= tokens
        # The same company mentioned later gets the token the profile already uses.
        text = deid.deidentify(db, f"{identity.companies[1]}에서 장비를 맡았습니다", cand)
        assert text == "[회사-2]에서 장비를 맡았습니다"
    factory.kw["bind"].dispose()
