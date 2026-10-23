"""Seed the database with the demo dataset, laid out relative to now like the frontend mock:
3 postings (competency sets, preset questions), 20 candidates with screenings, 5 interviewers,
one interview in progress, three scheduled, four completed (three AI-scored, one still being
scored), two weeks of availability and an activity history.

Everything is fictional. Candidates get made-up identities (names, 010-0000-xxxx numbers,
example.com addresses, invented schools and companies) sealed with IA_ENCRYPTION_KEY, and the
tokens their profiles use ([회사-1], [학교-1] ...) are registered through the real
de-identification path, so later answers mentioning the same values get the same tokens.
Seeded AI outputs (screenings, scores, follow-ups) are scripted, not model output; they carry the
fake providers' model names.

    uv run python scripts/seed_demo.py --reset
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete
from sqlalchemy.orm import Session

from interview_assistant.ai.prompts import (
    FOLLOWUP_PROMPT,
    SCORING_PROMPT,
    SCREENING_PROMPT,
)
from interview_assistant.config import Settings
from interview_assistant.deid.service import DeidService
from interview_assistant.deid.types import KnownIdentity
from interview_assistant.demo import mock_data
from interview_assistant.demo.script import split_sentences
from interview_assistant.models import (
    ActorType,
    AiScoringStatus,
    Application,
    AuditLog,
    Availability,
    Base,
    Candidate,
    CandidateNote,
    CompetencySet,
    EvaluatorType,
    FollowUpSuggestion,
    Interviewer,
    InterviewerRole,
    InterviewSession,
    JobPosting,
    PostingStatus,
    PresetQuestion,
    QAItem,
    QuestionSource,
    Score,
    Screening,
    ScreeningStatus,
    SessionInterviewer,
    SessionMode,
    SessionStatus,
    Speaker,
    TranscriptSegment,
)
from interview_assistant.models.base import iso_z, new_id

KST = timezone(timedelta(hours=9))
AI_MODEL = "fake-llm"
SCREENING_MODEL = "fake-llm-screening"

_SURNAMES = "강 윤 한 서 임 오 송 전 문 류".split()
_GIVEN = "도윤 서진 하람 지안 예린 시우 유나 태오 민서 건우".split()
_COMPANIES = (
    "한빛반도체 새솔전자 누리테크 가온시스템 다온소프트 미르데이터 라온클라우드 해솔정밀".split()
)
_SCHOOLS = "한울대학교 가람대학교 솔뫼대학교 늘봄대학교 마루대학교".split()


def candidate_id(n: int) -> str:
    return f"c0a1b2c3-0000-4000-9000-{n:012d}"


def application_id(n: int) -> str:
    return f"d1e2f3a4-0000-4000-9000-{n:012d}"


def screening_id(n: int) -> str:
    return f"f7a8b9c0-0000-4000-9000-{n:012d}"


def session_id(key: str) -> str:
    return f"0a1b2c3d-0000-4000-9000-{key.ljust(12, '0')}"


def fake_identity(n: int, profile: dict[str, Any]) -> KnownIdentity:
    """A made-up person: never a real name, number or address."""
    companies = sorted({e["company"] for e in profile["experience"]})
    schools = sorted({e["school"] for e in profile["education"]})
    return KnownIdentity(
        name=_SURNAMES[n % len(_SURNAMES)] + _GIVEN[(n * 3) % len(_GIVEN)],
        phones=(f"010-0000-{n:04d}",),
        emails=(f"cand{n:04d}@example.com",),
        companies=tuple(_COMPANIES[(n + i) % len(_COMPANIES)] for i in range(len(companies))),
        schools=tuple(_SCHOOLS[(n + i) % len(_SCHOOLS)] for i in range(len(schools))),
    )


def _hash01(text: str) -> float:
    """Deterministic 0..1 from a string (FNV-1a), for stable scripted scores."""
    h = 2166136261
    for ch in text:
        h ^= ord(ch)
        h = (h * 16777619) & 0xFFFFFFFF
    return (h % 10000) / 10000


def clear(db: Session) -> None:
    """Delete every row, children first."""
    for table in reversed(Base.metadata.sorted_tables):
        db.execute(delete(table))
    db.commit()


class _Seeder:
    def __init__(self, db: Session, deid: DeidService, settings: Settings, now: datetime) -> None:
        self.db = db
        self.deid = deid
        self.settings = settings
        self.now = now
        self.data = mock_data()
        self.interviewers: dict[str, Interviewer] = {}
        self.postings: dict[str, JobPosting] = {}
        self.posting_keys: dict[str, str] = {}  # posting id -> P1/P2/P3
        self.presets: dict[str, PresetQuestion] = {}  # dataset preset id (p1-q1) -> row
        self.applications: dict[int, Application] = {}

    # --- time -------------------------------------------------------------------------------

    def days_ago(self, days: int, hour: int = 10, minute: int = 0) -> datetime:
        day = (self.now - timedelta(days=days)).astimezone(KST).date()
        return datetime(day.year, day.month, day.day, hour, minute, tzinfo=KST).astimezone(
            timezone.utc
        )

    def minutes(self, delta: float) -> datetime:
        return self.now + timedelta(minutes=delta)

    # --- people, postings, candidates -------------------------------------------------------

    def interviewers_(self) -> None:
        base = self.days_ago(120)
        for i, row in enumerate(self.data["interviewers"]):
            person = Interviewer(
                id=row["id"],
                employee_no=row["employee_no"],
                name=row["name"],
                job_family=row["job_family"],
                department=row["department"],
                # The signed-in interviewer of the mock comes first (fallback "me").
                created_at=base + timedelta(minutes=0 if row["key"] == self.data["me"] else i + 1),
            )
            self.db.add(person)
            self.interviewers[row["key"]] = person

    def postings_(self) -> None:
        for p in self.data["postings"]:
            posting = JobPosting(
                id=p["id"],
                title=p["title"],
                job_family=p["job_family"],
                jd_text=p["jd_text"],
                status=PostingStatus(p["status"]),
                created_at=self.days_ago(p["createdDaysAgo"], 9),
            )
            self.db.add(posting)
            self.postings[p["key"]] = posting
            self.posting_keys[p["id"]] = p["key"]
            approved: CompetencySet | None = None
            for v in p["sets"]:
                created = self.days_ago(v["daysAgo"], 11)
                cs = CompetencySet(
                    id=f"e5f6a7b8-0000-4000-9000-{p['id'][-4:]}0000000{v['version']}",
                    posting=posting,
                    version=v["version"],
                    competencies=v["competencies"],
                    approved_by=self.interviewers[v["approvedBy"]].id if v["approvedBy"] else None,
                    approved_at=created + timedelta(minutes=180) if v["approvedBy"] else None,
                    created_at=created,
                )
                self.db.add(cs)
                if v["approvedBy"]:
                    approved = cs
            if approved is not None:
                for position, q in enumerate(p["presets"], start=1):
                    preset = PresetQuestion(
                        competency_set=approved,
                        position=position,
                        competency=q["competency"],
                        question=q["question"],
                        intent=q["intent"],
                        created_at=approved.approved_at,
                    )
                    self.db.add(preset)
                    self.presets[q["id"]] = preset

    def candidates_(self) -> None:
        for c in self.data["candidates"]:
            n = c["n"]
            posting = self.postings[c["posting"]]
            applied = self.days_ago(c["appliedDaysAgo"], 9 + n % 8, (n * 7) % 60)
            identity = fake_identity(n, c["profile"])
            candidate = Candidate(
                id=candidate_id(n),
                pseudonym=f"CAND-{n:04d}",
                encrypted_identity=self.deid.seal(identity),
                consent_recording=False,
                created_at=applied,
            )
            self.db.add(candidate)
            self.db.flush()
            # Register the profile's tokens in order: [지원자], [회사-1], [회사-2], [학교-1] ...
            self.deid.deidentifier(self.db).deidentify(
                " / ".join([identity.name or "", *identity.companies, *identity.schools]),
                candidate_id=candidate.id,
                known=identity,
            )
            application = Application(
                id=application_id(n),
                candidate=candidate,
                posting=posting,
                profile=c["profile"],
                created_at=applied,
            )
            rationale = "\n".join(
                [
                    c["summaryLine"],
                    *(f"+ {x}" for x in c["strengths"]),
                    *(f"- {x}" for x in c["concerns"]),
                ]
            )
            application.screening = Screening(
                id=screening_id(n),
                fit_score=c["fit"],
                rationale=rationale,
                status=ScreeningStatus(c["status"]),
                model=SCREENING_MODEL,
                prompt_version=SCREENING_PROMPT,
                created_at=applied + timedelta(minutes=90),
            )
            self.db.add(application)
            self.applications[n] = application

    # --- sessions ---------------------------------------------------------------------------

    def session(
        self,
        key: str,
        n: int,
        mode: str,
        status: SessionStatus,
        scheduled: datetime,
        panel: list[tuple[str, InterviewerRole]],
        started: datetime | None = None,
        ended: datetime | None = None,
    ) -> InterviewSession:
        application = self.applications[n]
        ran = status in (SessionStatus.in_progress, SessionStatus.completed)
        approved = [cs for cs in application.posting.competency_sets if cs.approved_at]
        sid = session_id(key)
        session = InterviewSession(
            id=sid,
            application=application,
            mode=SessionMode(mode),
            status=status,
            scheduled_at=scheduled,
            started_at=started,
            ended_at=ended,
            recording_uri=(self.settings.recordings_dir / f"{sid}.webm").resolve().as_uri()
            if ran
            else None,
            competency_set=approved[-1] if ran and approved else None,
            created_at=scheduled - timedelta(days=4),
        )
        for k, role in panel:
            session.interviewers.append(
                SessionInterviewer(interviewer=self.interviewers[k], role=role)
            )
        if ran:
            application.candidate.consent_recording = True
            application.candidate.consent_at = (started or scheduled) - timedelta(minutes=1)
        self.db.add(session)
        return session

    def ask_preset(
        self, session: InterviewSession, preset_key: str, at: datetime, answered: bool
    ) -> QAItem:
        preset = self.presets[preset_key]
        answer = self.data["answer_bank"][preset_key]["answer"]
        qa = QAItem(
            seq=len(session.qa_items) + 1,
            question=preset.question,
            question_source=QuestionSource.preset,
            preset_question=preset,
            target_competency=preset.competency,
            answer_text=answer if answered else None,
            answer_deidentified=answer if answered else None,
            asked_at=at,
            answered_at=at + timedelta(minutes=2) if answered else None,
            created_at=at,
        )
        session.qa_items.append(qa)
        return qa

    def ask_suggestion(
        self, session: InterviewSession, after: QAItem, preset_key: str, index: int, at: datetime
    ) -> QAItem:
        """The dataset's follow-ups for a preset answer, stored as one batch; one was used."""
        batch_id = new_id()
        rows = []
        for i, seed in enumerate(self.data["answer_bank"][preset_key]["suggestions"]):
            rows.append(
                FollowUpSuggestion(
                    batch_id=batch_id,
                    qa_item=after,
                    position=i,
                    competency=seed["competency"],
                    question=seed["question"],
                    rationale=seed["rationale"],
                    grounding=seed["grounding"],
                    model=AI_MODEL,
                    prompt_version=FOLLOWUP_PROMPT,
                    created_at=after.answered_at,
                )
            )
        self.db.add_all(rows)
        chosen = self.data["answer_bank"][preset_key]["suggestions"][index]
        qa = QAItem(
            seq=len(session.qa_items) + 1,
            question=chosen["question"],
            question_source=QuestionSource.ai_suggested,
            target_competency=chosen["competency"],
            answer_text=chosen["answer"],
            answer_deidentified=chosen["answer"],
            asked_at=at,
            answered_at=at + timedelta(minutes=2),
            created_at=at,
        )
        session.qa_items.append(qa)
        self.db.flush()
        rows[index].used_qa_item_id = qa.id
        rows[index].used_at = at
        return qa

    def ai_scores(self, session: InterviewSession) -> None:
        """Scripted AI scores: one per answered question, evidence quoted from the answer."""
        fit = session.application.screening.fit_score
        for qa in session.qa_items:
            if not qa.answer_deidentified or not qa.target_competency:
                continue
            h = _hash01(f"{qa.seq}:{session.id}:{qa.target_competency}")
            sentences = split_sentences(qa.answer_deidentified)
            pool = [x for x in sentences if re.search(r"\d", x)] or sentences
            session.scores.append(
                Score(
                    qa_item=qa,
                    competency=qa.target_competency,
                    score=max(1, min(5, round(fit / 20 - 1.3 + h * 2.4))),
                    evidence=pool[math.floor(_hash01(qa.question) * len(pool))],
                    confidence=round(0.52 + _hash01(f"{qa.seq}:conf") * 0.42, 2),
                    evaluator_type=EvaluatorType.ai,
                    model=AI_MODEL,
                    prompt_version=SCORING_PROMPT,
                    created_at=session.ended_at,
                )
            )
        session.ai_scoring_status = AiScoringStatus.completed
        session.ai_scoring_started_at = session.ended_at
        session.ai_scoring_finished_at = session.ended_at + timedelta(minutes=3)

    def interviewer_scores(
        self, session: InterviewSession, key: str, at: datetime, rows: list[tuple[str, int, str]]
    ) -> None:
        person = self.interviewers[key]
        for competency, score, comment in rows:
            session.scores.append(
                Score(
                    competency=competency,
                    score=score,
                    evidence=comment,
                    evaluator_type=EvaluatorType.interviewer,
                    evaluator_id=person.id,
                    created_at=at,
                )
            )
        link = next(x for x in session.interviewers if x.interviewer is person)
        link.submitted_at = at

    def sessions_(self) -> None:
        lead, panel = InterviewerRole.lead, InterviewerRole.panel
        today = self.now.astimezone(KST).date()
        today16 = datetime(today.year, today.month, today.day, 16, tzinfo=KST).astimezone(
            timezone.utc
        )
        half_hour = 30 * 60
        soon_ts = math.ceil(self.minutes(60).timestamp() / half_hour) * half_hour
        soon = datetime.fromtimestamp(soon_ts, tz=timezone.utc)
        s1_at = today16 if today16 > soon else soon
        tomorrow = today + timedelta(days=1)
        tomorrow10 = datetime(
            tomorrow.year, tomorrow.month, tomorrow.day, 10, tzinfo=KST
        ).astimezone(timezone.utc)

        live = self.session(
            "live",
            7,
            "remote",
            SessionStatus.in_progress,
            self.minutes(-15),
            [("kim", lead), ("park", panel)],
            started=self.minutes(-13),
        )
        self.session(
            "s1", 11, "remote", SessionStatus.scheduled, s1_at, [("kim", lead), ("park", panel)]
        )
        self.session(
            "s2",
            18,
            "onsite",
            SessionStatus.scheduled,
            s1_at + timedelta(minutes=90),
            [("lee", lead), ("jung", panel)],
        )
        self.session(
            "s3", 9, "remote", SessionStatus.scheduled, tomorrow10, [("park", lead), ("kim", panel)]
        )
        c1 = self.session(
            "c1",
            3,
            "remote",
            SessionStatus.completed,
            self.days_ago(1, 14),
            [("kim", lead), ("park", panel)],
            started=self.days_ago(1, 14, 2),
            ended=self.days_ago(1, 14, 48),
        )
        c2 = self.session(
            "c2",
            5,
            "onsite",
            SessionStatus.completed,
            self.days_ago(2, 10),
            [("park", lead), ("kim", panel)],
            started=self.days_ago(2, 10, 1),
            ended=self.days_ago(2, 10, 52),
        )
        c3 = self.session(
            "c3",
            14,
            "remote",
            SessionStatus.completed,
            self.days_ago(1, 15, 30),
            [("lee", lead), ("jung", panel)],
            started=self.days_ago(1, 15, 31),
            ended=self.days_ago(1, 16, 20),
        )
        c4 = self.session(
            "c4",
            16,
            "remote",
            SessionStatus.completed,
            self.minutes(-125),
            [("jung", lead), ("lee", panel)],
            started=self.minutes(-124),
            ended=self.minutes(-75),
        )

        # Live: Q1 answered, its follow-up answered, Q3 asked a moment ago (answered on connect).
        l1 = self.ask_preset(live, "p1-q1", self.minutes(-12), True)
        l2 = self.ask_suggestion(live, l1, "p1-q1", 0, self.minutes(-8))
        l3 = self.ask_preset(live, "p1-q3", self.minutes(-1), False)
        self.transcript(live, [l1, l2], l3)
        self.db.add(
            CandidateNote(
                session=live,
                author=self.interviewers["kim"],
                content="엣지 링 사례 설명이 구체적. 비용 판단 근거까지 스스로 설명함.",
                created_at=self.minutes(-6),
            )
        )

        self.ask_preset(c1, "p1-q2", self.days_ago(1, 14, 4), True)
        q5 = self.ask_preset(c1, "p1-q5", self.days_ago(1, 14, 12), True)
        self.ask_suggestion(c1, q5, "p1-q5", 0, self.days_ago(1, 14, 18))
        self.ask_preset(c1, "p1-q7", self.days_ago(1, 14, 25), True)
        self.ask_preset(c1, "p1-q4", self.days_ago(1, 14, 34), True)

        self.ask_preset(c2, "p1-q1", self.days_ago(2, 10, 3), True)
        q3 = self.ask_preset(c2, "p1-q3", self.days_ago(2, 10, 14), True)
        self.ask_suggestion(c2, q3, "p1-q3", 1, self.days_ago(2, 10, 22))
        self.ask_preset(c2, "p1-q8", self.days_ago(2, 10, 30), True)
        self.ask_preset(c2, "p1-q6", self.days_ago(2, 10, 40), True)

        incident = self.ask_preset(c3, "p2-q3", self.days_ago(1, 15, 33), True)
        self.ask_suggestion(c3, incident, "p2-q3", 0, self.days_ago(1, 15, 41))
        self.ask_preset(c3, "p2-q4", self.days_ago(1, 15, 48), True)
        self.ask_preset(c3, "p2-q6", self.days_ago(1, 15, 58), True)
        self.ask_preset(c3, "p2-q1", self.days_ago(1, 16, 8), True)

        self.ask_preset(c4, "p2-q1", self.minutes(-120), True)
        self.ask_preset(c4, "p2-q2", self.minutes(-108), True)
        self.ask_preset(c4, "p2-q5", self.minutes(-95), True)

        self.db.flush()
        for done in (c1, c2, c3):
            self.ai_scores(done)
        # c4 ended 75 minutes ago and is still being scored: the server picks it up at startup and
        # scores it with the configured LLM provider.
        c4.ai_scoring_status = AiScoringStatus.running
        c4.ai_scoring_started_at = c4.ended_at

        self.interviewer_scores(
            c1,
            "kim",
            self.days_ago(1, 15, 10),
            [
                ("공정 문제 해결", 4, "실패 원인을 스스로 찾아 검증 절차 개선까지 연결함."),
                ("데이터 기반 분석", 3, "분석 근거는 있으나 표본 크기에 대한 설명이 부족."),
                ("공정·장비 이해", 4, "온도와 폴리머 증착의 관계를 정확히 설명."),
                ("협업과 커뮤니케이션", 4, "생산팀과 합의 후 재조정까지 이어간 과정이 구체적."),
            ],
        )
        self.interviewer_scores(
            c1,
            "park",
            self.days_ago(1, 15, 40),
            [
                ("공정 문제 해결", 4, "재발 방지 조치까지 확인함."),
                ("데이터 기반 분석", 4, "이벤트 겹쳐 보기로 원인을 찾은 접근이 좋음."),
                ("공정·장비 이해", 3, "식각 메커니즘 설명은 좋으나 증착 쪽 깊이는 보통."),
                ("협업과 커뮤니케이션", 5, "데이터로 이견을 조율하고 결과를 수용하는 태도."),
            ],
        )
        self.interviewer_scores(
            c2,
            "park",
            self.days_ago(2, 11, 30),
            [
                ("공정 문제 해결", 4, "가설 설정과 DOE 검증이 체계적."),
                ("데이터 기반 분석", 4, "다변량 분석 이후 판단 기준이 명확."),
                ("공정·장비 이해", 3, "전후 공정 영향은 설명했으나 근거가 다소 약함."),
                ("협업과 커뮤니케이션", 3, "장비사 협업 양식 개선은 좋으나 내부 협업 사례 부족."),
            ],
        )

    def transcript(
        self, session: InterviewSession, answered: list[QAItem], pending: QAItem
    ) -> None:
        t = 60_000

        def push(qa: QAItem, speaker: Speaker, text: str) -> None:
            nonlocal t
            duration = max(1500, len(text) * 110)
            self.db.add(
                TranscriptSegment(
                    session=session,
                    qa_item_id=qa.id,
                    speaker=speaker,
                    text_deidentified=text,
                    start_ms=t,
                    end_ms=t + duration,
                )
            )
            t += duration + 600

        self.db.flush()
        for qa in answered:
            push(qa, Speaker.interviewer, qa.question)
            for sentence in split_sentences(qa.answer_deidentified or ""):
                push(qa, Speaker.candidate, sentence)
        t = 12 * 60_000
        push(pending, Speaker.interviewer, pending.question)

    # --- availability, activity -------------------------------------------------------------

    _TEMPLATES: dict[str, list[list[tuple[float, float]]]] = {
        "kim": [[(10, 12), (14, 17)], [(9, 11.5)], [(13, 18)], [(10, 12), (15, 17)], [(9, 12)]],
        "park": [
            [(9, 11), (15, 18)],
            [(10, 12), (14, 16)],
            [(14, 17)],
            [(9, 11.5), (15.5, 18)],
            [(10, 11)],
        ],
        "lee": [[(13, 16)], [(9, 12)], [(10, 12), (14, 15)], [(13, 18)], [(9, 11)]],
        "jung": [[(10, 12), (13.5, 15)], [(9.5, 11)], [(15, 18)], [(10, 12), (14, 16)], [(13, 17)]],
        "choi": [[(9, 12)], [(13, 17)], [(9, 10.5)], [(9, 11)], [(14, 18)]],
    }

    def availability_(self) -> None:
        today = self.now.astimezone(KST).date()
        monday = today - timedelta(days=today.weekday())
        created = datetime(monday.year, monday.month, monday.day, tzinfo=KST) - timedelta(days=3)
        for key, days in self._TEMPLATES.items():
            for week in range(2):
                for d in range(5):
                    day = monday + timedelta(days=week * 7 + d)
                    start_of_day = datetime(day.year, day.month, day.day, tzinfo=KST)
                    # Next week rotates the template by a day so the weeks differ.
                    for start, end in days[(d + week) % 5]:
                        self.db.add(
                            Availability(
                                interviewer=self.interviewers[key],
                                start_at=(start_of_day + timedelta(hours=start)).astimezone(
                                    timezone.utc
                                ),
                                end_at=(start_of_day + timedelta(hours=end)).astimezone(
                                    timezone.utc
                                ),
                                created_at=created.astimezone(timezone.utc),
                            )
                        )

    def activity_(self) -> None:
        def log(
            at: datetime,
            actor: ActorType,
            action: str,
            target_type: str,
            target_id: str,
            who: str | None = None,
            model: str | None = None,
            **details: Any,
        ) -> None:
            self.db.add(
                AuditLog(
                    occurred_at=at,
                    actor_type=actor,
                    actor_id=self.interviewers[who].id if who else None,
                    action=action,
                    target_type=target_type,
                    target_id=target_id,
                    model=model,
                    details=details or None,
                )
            )

        p1v2 = next(cs for cs in self.postings["P1"].competency_sets if cs.version == 2)
        p2v1 = next(cs for cs in self.postings["P2"].competency_sets if cs.version == 1)
        ai, user = ActorType.ai, ActorType.user
        sess = "interview_session"
        log(
            self.now - timedelta(days=3),
            ai,
            "screening.batch_completed",
            "job_posting",
            self.postings["P2"].id,
            model=SCREENING_MODEL,
            count=9,
        )
        log(
            self.now - timedelta(days=2),
            ai,
            "competency_set.generated",
            "competency_set",
            p1v2.id,
            model=AI_MODEL,
        )
        log(
            self.now - timedelta(days=2, minutes=-50),
            user,
            "score.interviewer_submitted",
            sess,
            session_id("c2"),
            who="park",
        )
        log(
            self.now - timedelta(days=1),
            user,
            "competency_set.approved",
            "competency_set",
            p2v1.id,
            who="lee",
        )
        log(
            self.now - timedelta(days=1, minutes=-30),
            ai,
            "score.ai_completed",
            sess,
            session_id("c1"),
            model=AI_MODEL,
        )
        log(
            self.now - timedelta(days=1, minutes=-70),
            user,
            "score.interviewer_submitted",
            sess,
            session_id("c1"),
            who="kim",
        )
        log(
            self.now - timedelta(days=1, minutes=-95),
            ai,
            "score.ai_completed",
            sess,
            session_id("c3"),
            model=AI_MODEL,
        )
        log(
            self.minutes(-180),
            user,
            "screening.status_changed",
            "screening",
            screening_id(13),
            who="park",
            **{"from": "rejected", "to": "hold"},
        )
        log(self.minutes(-75), user, "session.completed", sess, session_id("c4"), who="jung")
        log(self.minutes(-75), ai, "score.ai_started", sess, session_id("c4"), model=AI_MODEL)
        log(
            self.minutes(-14),
            user,
            "consent.recorded",
            sess,
            session_id("live"),
            who="kim",
            consent_recording=True,
        )
        log(
            self.minutes(-13),
            user,
            "session.started",
            sess,
            session_id("live"),
            who="kim",
            recording=True,
        )
        log(
            self.minutes(-8),
            user,
            "qa.created",
            sess,
            session_id("live"),
            who="kim",
            question_source="ai_suggested",
        )
        log(
            self.minutes(-1),
            user,
            "qa.created",
            sess,
            session_id("live"),
            who="kim",
            question_source="preset",
        )


def seed(
    db: Session, deid: DeidService, settings: Settings, now: datetime | None = None
) -> dict[str, object]:
    """Insert the demo dataset; the database must be empty. Returns row counts."""
    now = now or datetime.now(timezone.utc)
    seeder = _Seeder(db, deid, settings, now)
    seeder.interviewers_()
    seeder.postings_()
    db.flush()
    seeder.candidates_()
    db.flush()
    seeder.sessions_()
    seeder.availability_()
    seeder.activity_()
    db.commit()
    return {
        "postings": len(seeder.postings),
        "candidates": len(seeder.applications),
        "interviewers": len(seeder.interviewers),
        "seeded_at": iso_z(now),
    }
