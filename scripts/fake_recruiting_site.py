"""가짜 채용 사이트: sends signed application events the way the real recruiting site would.

    uv run python scripts/fake_recruiting_site.py --url http://127.0.0.1:8000 --count 500
    uv run python scripts/fake_recruiting_site.py --url http://127.0.0.1:8000 --count 500   # again: all duplicates

The key comes from --secret or IA_SITE_SECRET (.env), the same value the server checks. Everything
is fictional: names from a pool, 010-0xxx-xxxx / 010-1xxx-xxxx numbers, example.com/org/net
mail, invented schools and companies. Attachments are drawn for each applicant with the builders
of scripts/make_resume_fixtures.py (Korean font from the system, as there).

The scenario (same --seed on the same day, the same events byte for byte; a second run resends everything):

- submissions over the postings (--postings), some applicants applying to two or three of them
- updates before the deadline (revision 2: an edited essay, one more skill), withdrawals
- out of order: some updates are sent before their submission (the update applies, the late
  submission is skipped as stale)
- resends: some events go out twice unchanged (one application, `duplicate: true`)
- deliberate errors: an unknown posting number, HWP, spreadsheet and scanned attachments, items the spec
  refuses (photo, 주민등록번호, family, an attachment of kind photo), a missing required field
- before that, three forged requests (bad signature, stale timestamp replay, tampered body)

Then it polls the status of every accepted event (signed GET) until none is queued or being
applied, and prints what came back: HTTP codes, final statuses, failure codes, timings.
"""

from __future__ import annotations

import argparse
import base64
import importlib.util
import io
import json
import os
import random
import sys
import time
import uuid
import zipfile
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from interview_assistant.intake.signature import signed_headers

EVENTS_PATH = "/api/intake/site/events"
DEFAULT_POSTINGS = "DS-2026-0101,DS-2026-0102,DS-2026-0103"
UNKNOWN_POSTING = "DS-2026-9999"

# --- fictional people -----------------------------------------------------------------------

SURNAMES = [
    ("김", "Kim"), ("이", "Lee"), ("박", "Park"), ("최", "Choi"), ("정", "Jung"), ("강", "Kang"),
    ("조", "Cho"), ("윤", "Yoon"), ("장", "Jang"), ("임", "Lim"), ("한", "Han"), ("오", "Oh"),
    ("서", "Seo"), ("신", "Shin"), ("권", "Kwon"), ("황", "Hwang"), ("안", "Ahn"), ("송", "Song"),
    ("류", "Ryu"), ("홍", "Hong"), ("전", "Jeon"), ("고", "Ko"), ("문", "Moon"), ("양", "Yang"),
]  # fmt: skip
GIVEN = [
    ("도윤", "Doyun"), ("서진", "Seojin"), ("하람", "Haram"), ("지안", "Jian"), ("예린", "Yerin"),
    ("시우", "Siwoo"), ("유나", "Yuna"), ("태오", "Taeo"), ("민서", "Minseo"), ("건우", "Gunwoo"),
    ("서아", "Seoa"), ("은우", "Eunwoo"), ("지호", "Jiho"), ("하린", "Harin"), ("수아", "Sua"),
    ("윤호", "Yunho"), ("다인", "Dain"), ("세린", "Serin"), ("주원", "Juwon"), ("채원", "Chaewon"),
    ("현우", "Hyunwoo"), ("가은", "Gaeun"), ("준서", "Junseo"), ("소율", "Soyul"), ("이안", "Ian"),
    ("로하", "Roha"), ("연우", "Yeonwoo"), ("나은", "Naeun"), ("시온", "Sion"), ("태린", "Taerin"),
]  # fmt: skip
SCHOOLS = [("한빛대학교", "한빛대"), ("가람대학교", "가람대"), ("솔뫼대학교", "솔뫼대"), ("늘봄대학교", "늘봄대"),
           ("마루대학교", "마루대"), ("새별대학교", "새별대"), ("온누리과학기술원", "온누리과기원")]  # fmt: skip
COMPANIES = ["한빛반도체", "새솔전자", "누리테크", "가온시스템", "다온소프트", "미르데이터", "라온클라우드",
             "해솔정밀", "별무리소프트", "이음랩스"]  # fmt: skip
REGIONS = ["서울특별시 마포구", "서울특별시 송파구", "경기도 수원시 영통구", "경기도 성남시 분당구", "대전광역시 유성구",
           "부산광역시 해운대구", "경기도 용인시 수지구", "인천광역시 연수구"]  # fmt: skip
ROADS = ["솔바람길", "별빛누리길", "은하수로", "물빛로", "들꽃길", "노을빛길", "바람결길", "햇살마루길"]
REFS = [("오태호", "팀장"), ("문정훈", "파트장"), ("김태현", "책임"), ("정민지", "박사"), ("이서준", "선배")]

FAMILIES = [
    {
        "titles": ["공정개발 엔지니어", "공정 엔지니어", "수율 분석 엔지니어", "설비 엔지니어"],
        "skills": ["SPC", "DOE", "FDC", "Python", "JMP", "Spotfire", "CVD", "ALD", "식각", "증착", "수율", "통계", "MES", "Excel"],
        "majors": ["재료공학", "화학공학", "전자공학", "물리학", "신소재공학"],
        "work": ["식각 공정 조건 최적화와 산포 관리", "증착 두께 균일도 개선 과제", "SPC 관리도로 이상 징후를 조기에 찾는 체계 운영", "수율 저하 원인을 DOE로 분리"],
        "project": ("수율 개선 TF", "관리도와 DOE로 불량 원인을 찾아 수율을 개선"),
    },
    {
        "titles": ["백엔드 개발자", "플랫폼 엔지니어", "SRE", "데이터 엔지니어"],
        "skills": ["Python", "Go", "Kubernetes", "Kafka", "Redis", "PostgreSQL", "gRPC", "vLLM", "Triton", "Docker", "Prometheus", "Grafana", "Terraform", "FastAPI"],
        "majors": ["컴퓨터공학", "소프트웨어학", "전산학", "정보통신공학"],
        "work": ["추론 API 게이트웨이 설계와 운영", "메시지 큐 기반 비동기 처리 파이프라인 구축", "SLO 정의와 장애 대응 절차 개선", "PostgreSQL 쿼리 튜닝으로 응답 시간 단축"],
        "project": ("LLM 서빙 플랫폼", "GPU 추론 서버 앞단의 큐와 캐시를 설계해 처리량을 높임"),
    },
    {
        "titles": ["UX 디자이너", "프로덕트 디자이너", "UI 디자이너"],
        "skills": ["Figma", "프로토타이핑", "사용성 테스트", "디자인 시스템", "데이터 분석"],
        "majors": ["산업디자인학", "시각디자인학", "HCI", "심리학"],
        "work": ["모바일 앱 결제 흐름 재설계", "디자인 시스템 컴포넌트 정의", "사용성 테스트 설계와 개선안 도출", "접근성 기준 점검"],
        "project": ("모바일 결제 개선", "사용성 테스트로 이탈 지점을 찾아 결제 완료율을 높임"),
    },
]  # fmt: skip

ESSAY_QUESTIONS = ["지원 동기와 입사 후 포부를 적어 주세요.", "가장 어려웠던 문제를 해결한 경험을 적어 주세요.", "협업 과정에서 갈등을 조정한 경험을 적어 주세요."]
ESSAY_TEMPLATES = [
    "저는 {name}입니다. {school_short}에서 {major}을 전공했고, {company}에서 {work} 업무를 맡았습니다. 이 경험을 바탕으로 {title} 직무에서 성과를 내고 싶습니다.",
    "{company}에서 {work}를 하며 데이터로 원인을 확인하는 습관을 들였습니다. 당시 {ref} {ref_title}님과 기준을 먼저 합의한 뒤 개선안을 검증했습니다.",
    "팀 간 우선순위가 달라 일정이 밀렸을 때, 측정 가능한 목표로 다시 정리해 합의를 이끌었습니다. 궁금하신 점은 {email}로 연락 주세요.",
    "{work} 과제에서 실패한 시도도 기록해 두고 다음 결정의 근거로 썼습니다. 결과를 숫자로 설명하는 것이 제 강점입니다.",
]  # fmt: skip


@dataclass
class Applicant:
    n: int
    applicant_no: str
    name: str
    english: str
    phone: str
    email: str
    birthdate: str
    address: str
    school: tuple[str, str]
    major: str
    company: str
    family: int
    title: str
    start_year: int
    skills: list[str]
    ref: tuple[str, str]


def make_applicant(rng: random.Random, n: int, family: int) -> Applicant:
    surname, sur_en = rng.choice(SURNAMES)
    given, given_en = rng.choice(GIVEN)
    fam = FAMILIES[family]
    domain = rng.choice(["example.com", "example.org", "example.net"])
    return Applicant(
        n=n,
        applicant_no=f"U{100000 + n}",
        name=surname + given,
        english=f"{given_en} {sur_en}",
        phone=f"010-{rng.choice('01')}{rng.randint(0, 999):03d}-{rng.randint(0, 9999):04d}",
        email=f"{given_en.lower()}.{sur_en.lower()}{n}@{domain}",
        birthdate=f"{rng.randint(1988, 2001)}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}",
        address=f"{rng.choice(REGIONS)} {rng.choice(ROADS)} {rng.randint(1, 120)}",
        school=rng.choice(SCHOOLS),
        major=rng.choice(fam["majors"]),
        company=rng.choice(COMPANIES),
        family=family,
        title=rng.choice(fam["titles"]),
        start_year=rng.randint(2014, 2023),
        skills=rng.sample(fam["skills"], k=min(len(fam["skills"]), rng.randint(3, 6))),
        ref=rng.choice(REFS),
    )


# --- events ---------------------------------------------------------------------------------


@dataclass
class Planned:
    label: str  # what this send exercises (submit, update, withdraw, resend, error:...)
    event: dict[str, Any]
    files: dict[str, tuple[str, bytes]] = field(default_factory=dict)  # part -> (filename, data)
    expect_http: int = 202


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def essays(a: Applicant, rng: random.Random, edited: bool = False) -> list[dict[str, str]]:
    fam = FAMILIES[a.family]
    values = {
        "name": a.name, "school_short": a.school[1], "major": a.major, "company": a.company,
        "work": rng.choice(fam["work"]), "title": a.title, "ref": a.ref[0], "ref_title": a.ref[1], "email": a.email,
    }  # fmt: skip
    picks = rng.sample(range(len(ESSAY_TEMPLATES)), k=2)
    out = [{"question": ESSAY_QUESTIONS[i], "answer": ESSAY_TEMPLATES[t].format(**values)} for i, t in enumerate(picks)]
    if edited:
        out[0]["answer"] += " 마감 전에 최근 과제의 결과를 더해 고쳐 씁니다."
    return out


def form(a: Applicant, rng: random.Random, edited: bool = False) -> dict[str, Any]:
    fam = FAMILIES[a.family]
    end = None if rng.random() < 0.6 else f"{min(2026, a.start_year + rng.randint(2, 6))}-{rng.randint(1, 12):02d}"
    skills = list(a.skills) + ([rng.choice([s for s in fam["skills"] if s not in a.skills] or ["Excel"])] if edited else [])
    return {
        "education": [{"school": a.school[0], "degree": rng.choice(["bachelor", "bachelor", "master"]), "major": a.major,
                       "start": f"{a.start_year - 4}-03", "end": f"{a.start_year}-02", "status": "graduated"}],
        "career": [{"company": a.company, "department": "개발팀" if a.family == 1 else "기술팀", "title": a.title,
                    "start": f"{a.start_year}-0{rng.randint(1, 9)}", "end": end,
                    "description": f"{rng.choice(fam['work'])}. {rng.choice(fam['work'])}."}],
        "certifications": [{"name": rng.choice(["정보처리기사", "TOEIC", "OPIc", "품질경영기사"]), "score": rng.choice(["", "900", "IH"]),
                            "acquired": f"{a.start_year - 1}-{rng.randint(1, 12):02d}"}],
        "skills": skills,
        "projects": [{"name": fam["project"][0], "role": "담당", "description": fam["project"][1], "tech": a.skills[:2]}],
        "essays": essays(a, rng, edited),
    }  # fmt: skip


def applicant_block(a: Applicant) -> dict[str, Any]:
    return {
        "applicant_no": a.applicant_no,
        "name": a.name,
        "other_names": [a.english],
        "phones": [a.phone],
        "emails": [a.email],
        "birthdate": a.birthdate,
        "address": a.address,
    }


def event(
    kind: str, event_no: int, application_no: str, posting_no: str, revision: int, at: datetime, **body: Any
) -> dict[str, Any]:
    return {
        "event_id": f"EVT-{event_no:06d}",
        "event_type": f"application.{kind}",
        "occurred_at": _iso(at),
        "revision": revision,
        "posting_no": posting_no,
        "application_no": application_no,
        **body,
    }


# --- attachments (resume fixture builders) --------------------------------------------------


class Attachments:
    """Draws a resume for a fictional applicant with scripts/make_resume_fixtures.py."""

    BUILDERS = {"pdf": "pdf_r05", "docx": "docx_r07", "pptx": "pptx_r11", "html": "html_r16", "scan": "scan_r18"}

    def __init__(self, font: str | None) -> None:
        path = ROOT / "scripts" / "make_resume_fixtures.py"
        spec = importlib.util.spec_from_file_location("make_resume_fixtures", path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        self.m = module
        try:
            self.font = module.find_font(font)
            module.register_font(self.font)
        except SystemExit:
            self.font = None  # no Korean font: DOCX, PPTX and HTML only

    def available(self, form: str) -> bool:
        return self.font is not None or form not in ("pdf", "scan")

    def resume(self, a: Applicant, form: str) -> tuple[str, bytes]:
        m = self.m
        ext = {"scan": "pdf"}.get(form, form)
        person = m.Person(
            id=f"S{a.n}", form=form, file=f"이력서_{a.name}.{ext}", name=a.name, english=a.english,
            phone=a.phone, email=a.email, birth=a.birthdate, region=a.address.rsplit(" ", 2)[0],
            road=" ".join(a.address.rsplit(" ", 2)[1:]), unit="", school=a.school[0], school_short=a.school[1],
            major=a.major, company=a.company, company_short=a.company, role=a.title, job=a.title,
            period=f"{a.start_year}.03 ~ 2025.12", ref=a.ref[0], ref_title=a.ref[1], template=a.n % 4,
        )  # fmt: skip
        data, _ = getattr(m, self.BUILDERS[form])(person, m.Truth(), self.font)
        return person.file, data


HWP_BYTES = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 504  # an HWP header, nothing readable after it


def xlsx_bytes() -> bytes:
    """A spreadsheet: not a format the spec takes for a resume."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, text in (("[Content_Types].xml", "<Types/>"), ("xl/workbook.xml", "<workbook/>")):
            # A fixed entry time: the same bytes every run, or a resend would not be the same event.
            zf.writestr(zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0)), text)
    return buf.getvalue()


def scenario(
    postings: list[str],
    count: int = 500,
    seed: int = 7,
    *,
    files: Attachments | None = None,
    attachment_share: float = 0.3,
    now: datetime | None = None,
) -> list[Planned]:
    """The sends, in order. Roughly: 82% submissions, 7% updates, 3.5% withdrawals, 3.5% resends,
    4% deliberate errors; about one in five applicants applies to more than one posting."""
    rng = random.Random(seed)
    # Times start at midnight UTC of the day (or `now`), so the same seed on the same day builds
    # byte-identical events: a second run is a resend of every event.
    clock = (now or datetime.now(UTC)).replace(hour=0, minute=0, second=0, microsecond=0)
    n_errors = max(5, round(count * 0.04))
    n_updates = max(2, round(count * 0.07))
    n_withdraw = max(1, round(count * 0.035))
    n_resend = max(1, round(count * 0.035))
    n_submit = count - n_errors - n_updates - n_withdraw - n_resend

    weights = [0.45, 0.35, 0.2][: len(postings)]
    submissions: list[tuple[Applicant, str]] = []
    applicants: list[Applicant] = []
    while len(submissions) < n_submit:
        family = rng.choices(range(len(postings)), weights=weights)[0]
        a = make_applicant(rng, len(applicants) + 1, family % len(FAMILIES))
        applicants.append(a)
        targets = [family]
        if rng.random() < 0.2:  # the same person applies to another posting (or two)
            others = [i for i in range(len(postings)) if i != family]
            targets += rng.sample(others, k=min(len(others), 1 if rng.random() < 0.8 else 2))
        for t in targets[: n_submit - len(submissions)]:
            submissions.append((a, postings[t]))

    seq = 0
    plans: list[Planned] = []
    applied: list[tuple[Applicant, str, str, Planned]] = []  # applicant, posting, application_no, submit plan

    def next_event() -> int:
        nonlocal seq
        seq += 1
        return seq

    def tick() -> datetime:
        nonlocal clock
        clock += timedelta(seconds=rng.randint(5, 40))
        return clock

    attached: dict[int, tuple[str, bytes]] = {}
    for i, (a, posting_no) in enumerate(submissions):
        application_no = f"A{200000 + i}"
        body: dict[str, Any] = {
            "applicant": applicant_block(a),
            "consent": {"terms_version": "2026-10-v1", "agreed_at": _iso(tick())},
            "form": form(a, rng),
        }
        parts: dict[str, tuple[str, bytes]] = {}
        if files is not None and rng.random() < attachment_share:
            kind = rng.choice([k for k in ("pdf", "docx", "pptx", "html") if files.available(k)])
            if a.n not in attached:
                attached[a.n] = files.resume(a, kind)
            name, data = attached[a.n]
            parts["resume"] = (name, data)
            body["attachments"] = [{"part": "resume", "kind": "resume", "filename": name}]
        plan = Planned("submit", event("submitted", next_event(), application_no, posting_no, 1, tick(), **body), parts)
        plans.append(plan)
        applied.append((a, posting_no, application_no, plan))

    # Updates before the deadline (revision 2). A third of them go out before their submission.
    updated = rng.sample(applied, k=min(n_updates, len(applied)))
    for k, (a, posting_no, application_no, submit) in enumerate(updated):
        body = {
            "applicant": applicant_block(a),
            "consent": submit.event["consent"],
            "form": form(a, rng, edited=True),
        }
        if "attachments" in submit.event:
            body["attachments"] = submit.event["attachments"]
        plan = Planned("update", event("updated", next_event(), application_no, posting_no, 2, tick(), **body), submit.files)
        if k < max(1, n_updates // 3):
            plan.label = "update-before-submit"
            plans.insert(plans.index(submit), plan)
        else:
            plans.append(plan)

    # Withdrawals (a revision above anything sent for that application).
    for a, posting_no, application_no, submit in rng.sample(applied, k=min(n_withdraw, len(applied))):
        revision = 3 if any(p.event["application_no"] == application_no and p.event["revision"] == 2 for p in plans) else 2
        plans.append(Planned("withdraw", event("withdrawn", next_event(), application_no, posting_no, revision, tick())))

    # Deliberate errors.
    errors: list[Planned] = []
    for k in range(n_errors):
        a = make_applicant(rng, len(applicants) + 1, k % len(FAMILIES))
        applicants.append(a)
        application_no = f"A{900000 + k}"
        body = {
            "applicant": applicant_block(a),
            "consent": {"terms_version": "2026-10-v1", "agreed_at": _iso(tick())},
            "form": form(a, rng),
        }
        posting_no = postings[k % len(postings)]
        parts = {}
        case = k % 10
        if case in (0, 1):
            label, posting_no = "error:unknown_posting", UNKNOWN_POSTING
        elif case == 2:
            label = "error:hwp"
            parts = {"resume": (f"이력서_{a.name}.hwp", HWP_BYTES)}
            body["attachments"] = [{"part": "resume", "kind": "resume", "filename": parts["resume"][0]}]
        elif case == 3 and files is not None and files.available("scan"):
            label = "error:scan"
            parts = {"resume": files.resume(a, "scan")}
            body["attachments"] = [{"part": "resume", "kind": "resume", "filename": parts["resume"][0]}]
        elif case == 4:
            label = "error:forbidden_photo"
            body["applicant"]["photo"] = base64.b64encode(b"\x89PNG fictional").decode()
        elif case == 5:
            label = "error:forbidden_rrn"
            body["applicant"]["resident_registration_number"] = f"{a.birthdate[2:4]}0101-1000000"
        elif case == 6:
            label = "error:forbidden_family"
            body["applicant"]["family"] = [{"relation": "부", "occupation": "회사원"}]
        elif case == 7:
            label = "error:missing_name"
            del body["applicant"]["name"]
        elif case == 8:
            label = "error:spreadsheet"
            parts = {"resume": (f"경력_{a.n}.xlsx", xlsx_bytes())}
            body["attachments"] = [{"part": "resume", "kind": "resume", "filename": parts["resume"][0]}]
        else:
            label = "error:forbidden_photo_attachment"
            parts = {"photo": ("photo.jpg", b"\xff\xd8\xff fictional")}
            body["attachments"] = [{"part": "photo", "kind": "photo", "filename": "photo.jpg"}]
        expect = 422 if label.startswith(("error:forbidden", "error:missing")) else 202
        errors.append(Planned(label, event("submitted", next_event(), application_no, posting_no, 1, tick(), **body), parts, expect))
    for plan in errors:
        plans.insert(rng.randrange(len(plans) + 1), plan)

    # Resends: the same event again, unchanged, a little later.
    for original in rng.sample([p for p in plans if p.label in ("submit", "update", "withdraw")], k=n_resend):
        copy = Planned("resend", original.event, original.files, 202)
        plans.insert(min(len(plans), plans.index(original) + rng.randint(1, 40)), copy)
    return plans


# --- transport ------------------------------------------------------------------------------


class Transport(Protocol):
    def __call__(self, method: str, path: str, headers: dict[str, str], body: bytes) -> tuple[int, dict[str, Any]]: ...


def http_transport(base_url: str, timeout: float = 30) -> Transport:
    def send(method: str, path: str, headers: dict[str, str], body: bytes) -> tuple[int, dict[str, Any]]:
        request = Request(base_url.rstrip("/") + path, data=body if method != "GET" else None, method=method, headers=headers)
        try:
            with urlopen(request, timeout=timeout) as response:
                return response.status, json.loads(response.read() or b"{}")
        except HTTPError as exc:
            try:
                return exc.code, json.loads(exc.read() or b"{}")
            except ValueError:
                return exc.code, {}

    return send


def encode(plan: Planned) -> tuple[bytes, str]:
    """multipart/form-data: the event JSON, then one part per attachment. Part file names are
    neutral; the real file name travels in the event (attachments[].filename)."""
    if not plan.files:
        return json.dumps(plan.event, ensure_ascii=False).encode(), "application/json"
    boundary = f"fake-site-{uuid.uuid4().hex}"
    chunks = [
        f'--{boundary}\r\nContent-Disposition: form-data; name="event"; filename="event.json"\r\n'
        "Content-Type: application/json; charset=utf-8\r\n\r\n".encode(),
        json.dumps(plan.event, ensure_ascii=False).encode(),
        b"\r\n",
    ]
    for part, (_, data) in plan.files.items():
        chunks += [
            f'--{boundary}\r\nContent-Disposition: form-data; name="{part}"; filename="{part}.bin"\r\n'
            "Content-Type: application/octet-stream\r\n\r\n".encode(),
            data,
            b"\r\n",
        ]
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def post(transport: Transport, secret: str, plan: Planned) -> tuple[int, dict[str, Any]]:
    body, content_type = encode(plan)
    headers = {"Content-Type": content_type, **signed_headers(secret, "POST", EVENTS_PATH, body)}
    return transport("POST", EVENTS_PATH, headers, body)


def status(transport: Transport, secret: str, event_id: str) -> tuple[int, dict[str, Any]]:
    path = f"{EVENTS_PATH}/{event_id}"
    return transport("GET", path, signed_headers(secret, "GET", path, b""), b"")


def probe_security(transport: Transport, secret: str, postings: list[str]) -> dict[str, int]:
    """Three requests that must be refused (401) and leave nothing behind."""
    rng = random.Random(1)
    a = make_applicant(rng, 0, 0)
    probe = Planned(
        "probe",
        event("submitted", 999_999, "A999999", postings[0], 1, datetime.now(UTC),
              applicant=applicant_block(a), consent={"terms_version": "2026-10-v1", "agreed_at": _iso(datetime.now(UTC))},
              form=form(a, rng)),
    )  # fmt: skip
    body, content_type = encode(probe)
    out = {}
    forged = {"Content-Type": content_type, **signed_headers("not-the-key", "POST", EVENTS_PATH, body)}
    out["forged_signature"] = transport("POST", EVENTS_PATH, forged, body)[0]
    old = {"Content-Type": content_type, **signed_headers(secret, "POST", EVENTS_PATH, body, now=time.time() - 3600)}
    out["replayed_after_an_hour"] = transport("POST", EVENTS_PATH, old, body)[0]
    good = {"Content-Type": content_type, **signed_headers(secret, "POST", EVENTS_PATH, body)}
    out["tampered_body"] = transport("POST", EVENTS_PATH, good, body.replace(b"A999999", b"A999998"))[0]
    return out


@dataclass
class Report:
    sent: int = 0
    http: Counter[int] = field(default_factory=Counter)
    labels: Counter[str] = field(default_factory=Counter)
    unexpected: list[str] = field(default_factory=list)
    duplicates: int = 0
    refused_codes: Counter[str] = field(default_factory=Counter)
    send_seconds: float = 0.0
    final: Counter[str] = field(default_factory=Counter)
    failures: Counter[str] = field(default_factory=Counter)
    processing_seconds: float | None = None
    per_event_ms: list[int] = field(default_factory=list)
    security: dict[str, int] = field(default_factory=dict)
    pending_ids: list[str] = field(default_factory=list)

    def lines(self) -> list[str]:
        ms = sorted(self.per_event_ms)

        def pct(p: float) -> str:
            return f"{ms[min(len(ms) - 1, max(0, round(p * len(ms)) - 1))] / 1000:.2f}s" if ms else "-"

        out = [
            f"security probes: {self.security}" if self.security else "",
            f"sent {self.sent} requests in {self.send_seconds:.1f}s: "
            + ", ".join(f"HTTP {k} x {v}" for k, v in sorted(self.http.items())),
            f"  scenario: {dict(sorted(self.labels.items()))}",
            f"  duplicates acknowledged: {self.duplicates}, refused at the door: {dict(self.refused_codes)}",
            f"final statuses: {dict(self.final)}",
            f"  failed by code: {dict(self.failures)}",
        ]
        if self.processing_seconds is not None:
            out.append(
                f"all applied {self.processing_seconds:.1f}s after the first send; per event received->finished "
                f"avg {sum(ms) / len(ms) / 1000:.2f}s, p50 {pct(0.5)}, p95 {pct(0.95)}, max {pct(1.0)}"
                if ms
                else f"processing window {self.processing_seconds:.1f}s"
            )
        if self.pending_ids:
            out.append(f"still pending after the wait: {len(self.pending_ids)}")
        if self.unexpected:
            out.append("unexpected answers: " + "; ".join(self.unexpected[:10]))
        return [line for line in out if line]


def run(
    transport: Transport,
    secret: str,
    plans: list[Planned],
    *,
    wait: float = 900,
    poll: float = 1.0,
    on_progress: Callable[[str], None] | None = None,
) -> Report:
    report = Report()
    started = time.monotonic()
    accepted: dict[str, None] = {}
    for i, plan in enumerate(plans, 1):
        code, body = post(transport, secret, plan)
        report.sent += 1
        report.http[code] += 1
        report.labels[plan.label] += 1
        if body.get("duplicate"):
            report.duplicates += 1
        if code != plan.expect_http and not (plan.label == "resend" and code == 202):
            report.unexpected.append(f"{plan.label} {plan.event['event_id']}: HTTP {code} {body.get('code')}")
        if code == 422:
            report.refused_codes[str(body.get("code"))] += 1
        if code == 202:
            accepted[plan.event["event_id"]] = None
        if on_progress and i % 100 == 0:
            on_progress(f"  sent {i}/{len(plans)}")
    report.send_seconds = time.monotonic() - started

    pending = list(accepted)
    finished: dict[str, dict[str, Any]] = {}
    deadline = time.monotonic() + wait
    while pending and time.monotonic() < deadline:
        still = []
        for event_id in pending:
            code, body = status(transport, secret, event_id)
            if code == 200 and body.get("status") not in ("queued", "processing"):
                finished[event_id] = body
            else:
                still.append(event_id)
        pending = still
        if pending:
            if on_progress:
                on_progress(f"  waiting: {len(pending)} queued or being applied")
            time.sleep(poll)
    report.pending_ids = pending
    for body in finished.values():
        report.final[body["status"]] += 1
        if body["status"] == "failed":
            report.failures[str(body.get("code"))] += 1
        if body.get("finished_at"):
            t0 = datetime.fromisoformat(body["received_at"].replace("Z", "+00:00"))
            t1 = datetime.fromisoformat(body["finished_at"].replace("Z", "+00:00"))
            report.per_event_ms.append(round((t1 - t0).total_seconds() * 1000))
    if finished:
        report.processing_seconds = time.monotonic() - started
    return report


def _secret(arg: str | None) -> str | None:
    if arg:
        return arg
    if os.environ.get("IA_SITE_SECRET"):
        return os.environ["IA_SITE_SECRET"]
    env = ROOT / ".env"
    if env.is_file():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("IA_SITE_SECRET="):
                return line.split("=", 1)[1].strip() or None
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0], formatter_class=argparse.RawTextHelpFormatter)
    # 127.0.0.1, not localhost: on Windows "localhost" tries IPv6 first and every request waits ~2 s.
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--secret", help="shared key (default: IA_SITE_SECRET from the environment or .env)")
    parser.add_argument("--postings", default=DEFAULT_POSTINGS, help="site posting numbers, comma separated")
    parser.add_argument("--count", type=int, default=500)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--attachments", type=float, default=0.3, help="share of submissions with a resume file")
    parser.add_argument("--font", help="Korean TrueType font for PDF attachments")
    parser.add_argument("--wait", type=float, default=900, help="seconds to wait for processing")
    parser.add_argument("--json", type=Path, help="write the report (statuses and codes only) here")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    secret = _secret(args.secret)
    if not secret:
        print("IA_SITE_SECRET is not set (--secret, environment or .env).", file=sys.stderr)
        return 2
    postings = [p.strip() for p in args.postings.split(",") if p.strip()]
    print(f"building {args.count} events for {postings} (seed {args.seed}) ...")
    t0 = time.monotonic()
    files = Attachments(args.font) if args.attachments > 0 else None
    plans = scenario(postings, args.count, args.seed, files=files, attachment_share=args.attachments)
    print(f"built in {time.monotonic() - t0:.1f}s; sending to {args.url}")
    transport = http_transport(args.url)
    try:
        security = probe_security(transport, secret, postings)
    except URLError as exc:
        print(f"cannot reach {args.url}: {exc}", file=sys.stderr)
        return 2
    report = run(transport, secret, plans, wait=args.wait, on_progress=print)
    report.security = security
    for line in report.lines():
        print(line)
    if args.json:
        args.json.write_text(
            json.dumps(
                {
                    "security": security, "sent": report.sent, "http": report.http, "labels": report.labels,
                    "duplicates": report.duplicates, "refused": report.refused_codes, "send_seconds": report.send_seconds,
                    "final": report.final, "failures": report.failures, "processing_seconds": report.processing_seconds,
                    "per_event_ms": report.per_event_ms, "unexpected": report.unexpected,
                },
                indent=1,
            ),
            encoding="utf-8",
        )
    ok = not report.unexpected and not report.pending_ids and all(v == 401 for v in security.values())
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
