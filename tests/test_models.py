from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool

from interview_assistant.db import make_engine, make_session_factory
from interview_assistant.models import (
    ActorType,
    Application,
    AuditLog,
    Availability,
    Base,
    Candidate,
    CandidateNote,
    CompetencySet,
    EvaluatorType,
    Interviewer,
    InterviewerRole,
    InterviewSession,
    JobPosting,
    QAItem,
    QuestionSource,
    Score,
    Screening,
    ScreeningStatus,
    SessionInterviewer,
    SessionMode,
)

NOW = datetime(2026, 10, 21, 9, 0, tzinfo=timezone.utc)


@pytest.fixture
def session_factory():
    engine = make_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield make_session_factory(engine)
    engine.dispose()


def _posting() -> JobPosting:
    return JobPosting(title="Backend Engineer", job_family="SW", jd_text="Build services.")


def _candidate(pseudonym: str = "CAND-0001") -> Candidate:
    return Candidate(pseudonym=pseudonym, consent_recording=True, consent_at=NOW)


def test_full_graph_roundtrip(session_factory):
    with session_factory() as db:
        posting = _posting()
        posting.competency_sets.append(
            CompetencySet(
                version=1,
                competencies=[{"name": "문제 해결", "bars": {"1": "...", "5": "..."}}],
            )
        )
        candidate = _candidate()
        application = Application(candidate=candidate, posting=posting, profile={"years": 5})
        application.screening = Screening(
            fit_score=82.5, rationale="JD 요건 충족", status=ScreeningStatus.passed, model="fake"
        )
        interviewer = Interviewer(employee_no="E-100", name="면접관 A", job_family="SW")
        session = InterviewSession(application=application, mode=SessionMode.remote)
        session.interviewers.append(
            SessionInterviewer(interviewer=interviewer, role=InterviewerRole.lead)
        )
        qa = QAItem(seq=1, question="최근 프로젝트는?", question_source=QuestionSource.preset)
        qa.scores.append(
            Score(
                competency="문제 해결",
                score=4,
                evidence="\"…장애를 30분 만에 복구했습니다\"",
                confidence=0.8,
                evaluator_type=EvaluatorType.ai,
                model="fake",
            )
        )
        qa.scores.append(
            Score(
                competency="문제 해결",
                score=3,
                evaluator_type=EvaluatorType.interviewer,
                evaluator_id=interviewer.id,
            )
        )
        session.qa_items.append(qa)
        session.notes.append(CandidateNote(author=interviewer, content="설명이 구체적임"))
        interviewer.availabilities.append(
            Availability(start_at=NOW, end_at=NOW + timedelta(hours=2))
        )
        db.add_all([posting, interviewer])
        db.add(AuditLog(actor_type=ActorType.ai, action="screening.run", target_type="application"))
        db.commit()

    with session_factory() as db:
        loaded = db.scalars(select(Application)).one()
        assert loaded.candidate.pseudonym == "CAND-0001"
        assert loaded.posting.competency_sets[0].version == 1
        assert loaded.screening.status is ScreeningStatus.passed
        [sess] = loaded.sessions
        assert sess.mode is SessionMode.remote
        assert sess.interviewers[0].role is InterviewerRole.lead
        assert sess.interviewers[0].interviewer.employee_no == "E-100"
        [qa_loaded] = sess.qa_items
        assert {s.evaluator_type for s in qa_loaded.scores} == {
            EvaluatorType.ai,
            EvaluatorType.interviewer,
        }
        assert sess.notes[0].author.name == "면접관 A"
        assert db.scalars(select(AuditLog)).one().action == "screening.run"


def test_pseudonym_must_be_unique(session_factory):
    with session_factory() as db:
        db.add_all([_candidate("DUP"), _candidate("DUP")])
        with pytest.raises(IntegrityError):
            db.commit()


def test_competency_set_version_unique_per_posting(session_factory):
    with session_factory() as db:
        posting = _posting()
        posting.competency_sets.extend(
            [CompetencySet(version=1, competencies=[]), CompetencySet(version=1, competencies=[])]
        )
        db.add(posting)
        with pytest.raises(IntegrityError):
            db.commit()


def _session_with_qa(db) -> QAItem:
    posting = _posting()
    application = Application(candidate=_candidate(), posting=posting)
    session = InterviewSession(application=application, mode=SessionMode.onsite)
    qa = QAItem(seq=1, question="Q", question_source=QuestionSource.interviewer)
    session.qa_items.append(qa)
    db.add(posting)
    db.flush()
    return qa


def test_score_must_be_between_1_and_5(session_factory):
    with session_factory() as db:
        qa = _session_with_qa(db)
        qa.scores.append(
            Score(competency="x", score=6, evidence="e", evaluator_type=EvaluatorType.ai)
        )
        with pytest.raises(IntegrityError):
            db.commit()


def test_ai_score_requires_evidence(session_factory):
    with session_factory() as db:
        qa = _session_with_qa(db)
        qa.scores.append(Score(competency="x", score=3, evaluator_type=EvaluatorType.ai))
        with pytest.raises(IntegrityError):
            db.commit()


def test_interviewer_score_may_omit_evidence(session_factory):
    with session_factory() as db:
        qa = _session_with_qa(db)
        qa.scores.append(Score(competency="x", score=3, evaluator_type=EvaluatorType.interviewer))
        db.commit()
        assert db.scalars(select(Score)).one().evidence is None


def test_availability_end_must_be_after_start(session_factory):
    with session_factory() as db:
        interviewer = Interviewer(employee_no="E-1", name="A")
        interviewer.availabilities.append(Availability(start_at=NOW, end_at=NOW))
        db.add(interviewer)
        with pytest.raises(IntegrityError):
            db.commit()


def test_deleting_candidate_cascades_to_sessions_and_scores(session_factory):
    with session_factory() as db:
        qa = _session_with_qa(db)
        qa.scores.append(Score(competency="x", score=2, evaluator_type=EvaluatorType.interviewer))
        db.commit()
        assert db.scalars(select(Score)).one()

        candidate = db.scalars(select(Candidate)).one()
        db.delete(candidate)
        db.commit()

        assert db.scalars(select(Application)).all() == []
        assert db.scalars(select(InterviewSession)).all() == []
        assert db.scalars(select(QAItem)).all() == []
        assert db.scalars(select(Score)).all() == []
        assert db.scalars(select(JobPosting)).one()  # postings are never cascaded


def test_invalid_enum_value_is_rejected_by_the_database(session_factory):
    with session_factory() as db:
        db.add(_posting())
        db.commit()
        with pytest.raises(IntegrityError):
            db.execute(text("UPDATE job_postings SET status = 'bogus'"))
            db.commit()


def test_candidate_retention_fields(session_factory):
    with session_factory() as db:
        candidate = _candidate()
        candidate.deleted_at = NOW + timedelta(days=180)
        db.add(candidate)
        db.commit()
        assert db.scalars(select(Candidate)).one().deleted_at is not None
