"""Applications from the recruiting site (docs/site-intake-spec.md), sent the way the fake site
(scripts/fake_recruiting_site.py) sends them, through the real signed endpoint and the background
queue. Fake providers without latency, no external network."""

from __future__ import annotations

import copy
import importlib.util
import json
import shutil
import sys
import time
from contextlib import contextmanager
from datetime import UTC
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from interview_assistant.intake.forms import CareerField, FormFields, build_profile, career_months
from interview_assistant.main import create_app
from interview_assistant.models import (
    Application,
    AuditLog,
    Candidate,
    IntakeEvent,
    InterviewSession,
    JobPosting,
    PostingStatus,
)
from interview_assistant.providers.fake import FakeLLM
from tests.api_util import P1, P3, get_paths, json_keys, walk_json
from tests.conftest import ROOT, api_settings, file_session_factory, instant_providers
from tests.test_api_flows import P2

SECRET = "test-site-secret-0123456789"
P1_NO, P2_NO = "DS-2026-0101", "DS-2026-0102"  # seeded links; P3 is not linked
RESUMES = ROOT / "tests" / "fixtures" / "resumes"


def _load_fake_site():
    path = ROOT / "scripts" / "fake_recruiting_site.py"
    spec = importlib.util.spec_from_file_location("fake_recruiting_site", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


site_mod = _load_fake_site()


def transport(client: TestClient):
    def send(method: str, path: str, headers: dict[str, str], body: bytes):
        response = client.request(method, path, headers=headers, content=body if method != "GET" else None)
        try:
            return response.status_code, response.json()
        except ValueError:
            return response.status_code, {}

    return send


@contextmanager
def app_client(seeded_db, db_path: Path, tmp_path: Path, *, providers=None, **overrides):
    template, key = seeded_db
    if not db_path.exists():
        shutil.copyfile(template, db_path)
    factory = file_session_factory(db_path)
    settings = dict(site_secret=SECRET, intake_workers=2)
    settings.update(overrides)
    app = create_app(
        api_settings(db_path, key, tmp_path, **settings),
        providers=providers or instant_providers(),
        session_factory=factory,
    )
    with TestClient(app) as client:
        client.runtime = app.state.runtime
        yield client
    factory.kw["bind"].dispose()


@pytest.fixture
def site(seeded_db, tmp_path, no_external_network):
    with app_client(seeded_db, tmp_path / "site.db", tmp_path) as client:
        yield client


# --- helpers --------------------------------------------------------------------------------

_counter = iter(range(1, 1_000_000))


class Person:
    """A fictional applicant from the fake site's pools."""

    def __init__(self, n: int, family: int = 0) -> None:
        import random

        rng = random.Random(n)
        self.a = site_mod.make_applicant(rng, n, family)
        self.form = site_mod.form(self.a, rng)

    def event(self, kind: str, application_no: str, posting_no: str, revision: int = 1, **extra: Any) -> dict:
        body: dict[str, Any] = {}
        if kind != "withdrawn":
            body = {
                "applicant": site_mod.applicant_block(self.a),
                "consent": {"terms_version": "2026-10-v1", "agreed_at": "2026-10-26T00:00:00.000Z"},
                "form": copy.deepcopy(self.form),
            }
        body.update(extra)
        from datetime import datetime

        return site_mod.event(kind, 700_000 + next(_counter), application_no, posting_no, revision, datetime.now(UTC), **body)


def send(client, event: dict, files: dict[str, tuple[str, bytes]] | None = None, *, secret: str = SECRET):
    return site_mod.post(transport(client), secret, site_mod.Planned("test", event, files or {}))


def finish(client, event_id: str, timeout: float = 20) -> dict:
    deadline = time.monotonic() + timeout
    while True:
        code, body = site_mod.status(transport(client), SECRET, event_id)
        assert code == 200, body
        if body["status"] not in ("queued", "processing"):
            return body
        if time.monotonic() > deadline:
            raise AssertionError(f"event {event_id} still {body['status']}")
        time.sleep(0.02)


def submit(client, person: Person, application_no: str, posting_no: str = P1_NO, **extra) -> dict:
    event = person.event("submitted", application_no, posting_no, **extra)
    code, body = send(client, event)
    assert code == 202, body
    return finish(client, event["event_id"])


def rows(client, posting_id: str) -> list[dict]:
    return client.get(f"/api/postings/{posting_id}/applications").json()


def row_of(client, application_no: str) -> Application | None:
    with client.runtime.session_factory() as db:
        return db.scalar(select(Application).where(Application.site_application_no == application_no))


def audits(client, action: str) -> list[AuditLog]:
    with client.runtime.session_factory() as db:
        return list(db.scalars(select(AuditLog).where(AuditLog.action == action)).all())


# --- the door: signatures -------------------------------------------------------------------


def test_forged_replayed_and_tampered_requests_are_refused_and_leave_nothing(site):
    probes = site_mod.probe_security(transport(site), SECRET, [P1_NO])
    assert probes == {"forged_signature": 401, "replayed_after_an_hour": 401, "tampered_body": 401}
    event = Person(1).event("submitted", "A-SIG", P1_NO)
    body, content_type = site_mod.encode(site_mod.Planned("x", event))
    missing = site.post("/api/intake/site/events", content=body, headers={"Content-Type": content_type})
    assert missing.status_code == 401 and missing.json()["code"] == "missing_signature"
    # Signed for another path: not valid here.
    from interview_assistant.intake.signature import signed_headers

    wrong_path = signed_headers(SECRET, "POST", "/api/other", body)
    elsewhere = site.post("/api/intake/site/events", content=body, headers={"Content-Type": content_type, **wrong_path})
    assert elsewhere.status_code == 401 and elsewhere.json()["code"] == "invalid_signature"
    with site.runtime.session_factory() as db:
        assert db.scalars(select(IntakeEvent)).all() == []
    codes = sorted(a.details["code"] for a in audits(site, "intake.signature_rejected"))
    assert codes == ["invalid_signature", "invalid_signature", "invalid_signature", "missing_signature", "stale_timestamp"]
    lookup = site.get(f"/api/intake/site/events/{event['event_id']}")
    assert lookup.status_code == 401


def test_the_previous_key_still_works_while_rotating_and_no_key_means_closed(seeded_db, tmp_path, no_external_network):
    with app_client(seeded_db, tmp_path / "rot.db", tmp_path, site_secret="new-key", site_secret_previous=SECRET) as client:
        code, _ = send(client, Person(2).event("submitted", "A-ROT", P1_NO))
        assert code == 202
        code, body = send(client, Person(3).event("submitted", "A-ROT2", P1_NO), secret="new-key")
        assert code == 202, body
    with app_client(seeded_db, tmp_path / "off.db", tmp_path, site_secret=None) as client:
        code, body = send(client, Person(4).event("submitted", "A-OFF", P1_NO))
        assert code == 503 and body["code"] == "not_configured"


# --- applying -------------------------------------------------------------------------------


def test_a_submission_is_applied_in_the_background_and_the_form_is_the_profile(site):
    person = Person(10, family=0)
    event = person.event("submitted", "A-0001", P1_NO)
    code, body = send(site, event)
    assert code == 202 and body["status"] in ("queued", "processing") and body["duplicate"] is False
    assert body["status_url"] == f"/api/intake/site/events/{event['event_id']}"
    done = finish(site, event["event_id"])
    assert done["status"] == "done" and done["finished_at"]
    assert not json_keys(done) & {"candidate", "pseudonym", "application_id"}  # the site gets no pseudonym

    row = next(r for r in rows(site, P1) if r["application_id"] == row_of(site, "A-0001").id)
    assert row["channel"] == "site" and row["screening"]["status"] == "hold"
    assert {r["channel"] for r in rows(site, P1) if r["application_id"] != row["application_id"]} == {"upload"}
    detail = site.get(f"/api/applications/{row['application_id']}").json()
    profile = detail["application"]["profile"]
    assert profile["education"][0]["school"].startswith("[학교-")
    assert profile["experience"][0]["company"].startswith("[회사-")
    assert set(person.a.skills) <= set(profile["skills"])
    assert detail["application"]["channel"] == "site" and detail["document"]["format"] == "site"
    text = json.dumps(detail, ensure_ascii=False)
    for value in (person.a.name, person.a.phone, person.a.email, person.a.school[0], person.a.company, person.a.applicant_no):
        assert value not in text
    # Form fields are the profile: no model call to structure them, one to assess.
    app_id = row["application_id"]
    assert not [a for a in audits(site, "profile.extracted") if a.target_id == app_id]
    assert [a for a in audits(site, "screening.assessed") if a.target_id == app_id]
    received = [a for a in audits(site, "application.received") if a.target_id == app_id]
    assert received and received[0].actor_type.value == "system"
    with site.runtime.session_factory() as db:
        stored = db.scalar(select(IntakeEvent).where(IntakeEvent.event_id == event["event_id"]))
        assert stored.encrypted_payload is None  # applied: the copy of the payload is gone
        assert stored.result["consent_version"] == "2026-10-v1"


def test_essays_only_and_attachments_go_through_the_document_path(site):
    person = Person(11, family=1)
    essays_only = {"essays": person.form["essays"]}
    data = (RESUMES / "이력서_문태오.docx").read_bytes()
    event = person.event(
        "submitted",
        "A-0002",
        P2_NO,
        form=essays_only,
        attachments=[{"part": "resume", "kind": "resume", "filename": "이력서_문태오.docx"}],
    )
    code, body = send(site, event, {"resume": ("이력서_문태오.docx", data)})
    assert code == 202, body
    assert finish(site, event["event_id"])["status"] == "done"
    app = row_of(site, "A-0002")
    assert app.document_info["format"] == "site+docx" and app.document_info["replacements"] > 0
    assert [a for a in audits(site, "profile.extracted") if a.target_id == app.id]  # no form: the model structures
    assert any(p.read_bytes() == data for p in Path(site.runtime.uploads_dir).rglob("1-resume.docx"))
    assert "문태오" not in app.source_file_uri
    assert not list((Path(site.runtime.uploads_dir) / "intake").glob("*/*"))  # staging cleared


def test_a_resent_event_is_applied_once_and_a_changed_one_is_refused(site):
    person = Person(12)
    event = person.event("submitted", "A-0003", P1_NO)
    assert send(site, event)[0] == 202
    finish(site, event["event_id"])
    before = len(rows(site, P1))
    for _ in range(3):  # retries after a timeout: same answer, nothing applied again
        code, body = send(site, event)
        assert code == 202 and body["duplicate"] is True and body["status"] == "done"
    changed = copy.deepcopy(event)
    changed["form"]["skills"].append("Kafka")
    code, body = send(site, changed)
    assert code == 409 and body["code"] == "event_id_conflict"
    time.sleep(0.2)
    assert len(rows(site, P1)) == before
    with site.runtime.session_factory() as db:
        assert len(db.scalars(select(IntakeEvent).where(IntakeEvent.event_id == event["event_id"])).all()) == 1


def test_the_same_applicant_number_is_one_candidate_across_postings(site):
    person, other = Person(13), Person(14)
    assert submit(site, person, "A-0004", P1_NO)["status"] == "done"
    assert submit(site, person, "A-0005", P2_NO)["status"] == "done"
    assert submit(site, other, "A-0006", P1_NO)["status"] == "done"
    first, second, third = (row_of(site, n) for n in ("A-0004", "A-0005", "A-0006"))
    assert first.candidate_id == second.candidate_id != third.candidate_id
    index = site.get("/api/candidates").json()
    pseudonyms = {i["application_id"]: i["pseudonym"] for i in index}
    assert pseudonyms[first.id] == pseudonyms[second.id] != pseudonyms[third.id]
    with site.runtime.session_factory() as db:
        candidate = db.get(Candidate, first.candidate_id)
        assert candidate.site_applicant_hash and person.a.applicant_no not in candidate.site_applicant_hash
    raw = Path(site.runtime.settings.database_url.split("///", 1)[1]).read_bytes()
    assert person.a.applicant_no.encode() not in raw  # the number is never stored


def test_an_update_rescreens_and_puts_a_decided_screening_back_on_hold(site):
    person = Person(15)
    assert submit(site, person, "A-0007", P1_NO)["status"] == "done"
    app = row_of(site, "A-0007")
    first = site.get(f"/api/applications/{app.id}").json()["screening"]
    assert site.patch(f"/api/screenings/{first['id']}", json={"status": "passed"}).status_code == 200

    updated = person.event("updated", "A-0007", P1_NO, revision=2)
    updated["form"]["skills"].append("Kubernetes")
    assert send(site, updated)[0] == 202
    assert finish(site, updated["event_id"])["status"] == "done"
    detail = site.get(f"/api/applications/{app.id}").json()
    assert detail["application"]["id"] == app.id  # the same application
    assert detail["screening"]["id"] != first["id"] and detail["screening"]["status"] == "hold"
    assert "Kubernetes" in detail["application"]["profile"]["skills"]
    log = [a for a in audits(site, "application.updated") if a.target_id == app.id]
    assert log and log[0].details["screening_reset"] is True
    assert len([r for r in rows(site, P1) if r["application_id"] == app.id]) == 1


def test_events_out_of_order_end_in_the_newest_version(site):
    person = Person(16)
    update = person.event("updated", "A-0008", P1_NO, revision=2)
    update["form"]["skills"] = ["Spotfire"]
    late_submit = person.event("submitted", "A-0008", P1_NO, revision=1)
    assert send(site, update)[0] == 202
    assert finish(site, update["event_id"])["status"] == "done"  # created from the update
    assert send(site, late_submit)[0] == 202
    stale = finish(site, late_submit["event_id"])
    assert stale["status"] == "skipped" and stale["code"] == "stale_revision"
    app = row_of(site, "A-0008")
    assert app.profile["skills"][:1] == ["Spotfire"]


def test_withdrawal_hides_the_application_cancels_interviews_and_blocks_other_versions(site):
    person = Person(17)
    assert submit(site, person, "A-0009", P1_NO)["status"] == "done"
    app = row_of(site, "A-0009")
    people = [i["id"] for i in site.get("/api/interviewers").json()]
    # 1차 opens once a person passed the screening.
    screening = site.get(f"/api/applications/{app.id}").json()["screening"]
    site.patch(f"/api/screenings/{screening['id']}", json={"status": "passed"})
    booked = site.post(
        "/api/sessions",
        json={
            "application_id": app.id,
            "mode": "remote",
            "scheduled_at": "2026-12-01T10:00:00+09:00",
            "interviewers": [{"interviewer_id": people[0], "role": "lead"}],
        },
    )
    assert booked.status_code == 201
    count = site.get(f"/api/postings/{P1}").json()["counts"]["applications"]

    withdraw = person.event("withdrawn", "A-0009", P1_NO, revision=2)
    code, body = send(site, withdraw)
    assert code == 202 and body["event_type"] == "application.withdrawn"
    done = finish(site, withdraw["event_id"])
    assert done["status"] == "done"
    assert app.id not in [r["application_id"] for r in rows(site, P1)]
    assert app.id not in [i["application_id"] for i in site.get("/api/candidates").json()]
    assert site.get(f"/api/postings/{P1}").json()["counts"]["applications"] == count - 1
    detail = site.get(f"/api/applications/{app.id}").json()
    assert detail["application"]["withdrawn_at"] and detail["sessions"][0]["status"] == "cancelled"
    with site.runtime.session_factory() as db:
        assert db.get(InterviewSession, booked.json()["id"]).status.value == "cancelled"

    newer = person.event("updated", "A-0009", P1_NO, revision=3)
    assert send(site, newer)[0] == 202
    refused = finish(site, newer["event_id"])
    assert refused["status"] == "failed" and refused["code"] == "application_withdrawn"
    again = site.post(
        "/api/sessions",
        json={
            "application_id": app.id,
            "mode": "remote",
            "scheduled_at": "2026-12-02T10:00:00+09:00",
            "interviewers": [{"interviewer_id": people[0], "role": "lead"}],
        },
    )
    assert again.status_code == 409

    # A withdrawal that arrives before its submission: the submission is never applied.
    early = Person(18)
    first = early.event("withdrawn", "A-0010", P1_NO, revision=2)
    assert send(site, first)[0] == 202
    assert finish(site, first["event_id"])["status"] == "done"
    late = early.event("submitted", "A-0010", P1_NO, revision=1)
    assert send(site, late)[0] == 202
    skipped = finish(site, late["event_id"])
    assert skipped["status"] == "skipped" and skipped["code"] == "withdrawn"
    assert row_of(site, "A-0010") is None


def test_reapplying_after_withdrawal_with_a_new_number_reuses_the_place(site):
    person = Person(19)
    assert submit(site, person, "A-0011", P1_NO)["status"] == "done"
    withdraw = person.event("withdrawn", "A-0011", P1_NO, revision=2)
    send(site, withdraw)
    finish(site, withdraw["event_id"])
    assert submit(site, person, "A-0012", P1_NO)["status"] == "done"
    app = row_of(site, "A-0012")
    assert app.withdrawn_at is None and app.id in [r["application_id"] for r in rows(site, P1)]
    duplicate = submit(site, person, "A-0013", P1_NO)  # a second active number for the same posting
    assert duplicate["status"] == "failed" and duplicate["code"] == "duplicate_application"


def test_a_withdrawal_cancels_an_event_being_applied(seeded_db, tmp_path, no_external_network):
    slow = instant_providers()
    slow.llm["screening"] = FakeLLM(model="fake-llm-screening", speed=4)  # ~3.6 s per call
    with app_client(seeded_db, tmp_path / "slow.db", tmp_path, providers=slow) as client:
        person = Person(20)
        before = len(client.get("/api/candidates").json())
        submitted = person.event("submitted", "A-0014", P1_NO)
        assert send(client, submitted)[0] == 202
        deadline = time.monotonic() + 10
        while site_mod.status(transport(client), SECRET, submitted["event_id"])[1]["status"] != "processing":
            assert time.monotonic() < deadline
            time.sleep(0.02)
        time.sleep(0.2)  # inside the model call
        withdraw = person.event("withdrawn", "A-0014", P1_NO, revision=2)
        assert send(client, withdraw)[0] == 202
        stopped = finish(client, submitted["event_id"], timeout=10)
        assert stopped["status"] == "skipped" and stopped["code"] == "withdrawn"
        assert finish(client, withdraw["event_id"])["status"] == "done"
        assert row_of(client, "A-0014") is None
        with client.runtime.session_factory() as db:  # the candidate created on the way is gone too
            assert db.scalar(select(Candidate).where(Candidate.site_applicant_hash.is_not(None))) is None
        assert len(client.get("/api/candidates").json()) == before


# --- failures -------------------------------------------------------------------------------


def test_failures_are_classified_and_an_unknown_posting_can_be_processed_after_linking(site):
    # Without OCR (읽기 방식 '텍스트만') a scan cannot be read: ocr_required, retriable later.
    text_only = {"impl": "standard", "options": {"mode": "text_only"}, "reason": "OCR 없이 받는 경우"}
    assert site.post("/api/admin/models/document.reading/apply", json=text_only).status_code == 200
    p = [Person(30 + i) for i in range(6)]
    unknown = p[0].event("submitted", "A-0020", "DS-2026-0103")  # P3 is not linked yet
    image = p[1].event("submitted", "A-0021", P1_NO, attachments=[{"part": "f", "kind": "resume", "filename": "이력서.gif"}])
    scan = p[2].event("submitted", "A-0022", P1_NO, attachments=[{"part": "f", "kind": "portfolio", "filename": "scan.pdf"}])
    broken = p[3].event("submitted", "A-0023", P1_NO, attachments=[{"part": "f", "kind": "resume", "filename": "x.docx"}])
    closed = p[4].event("submitted", "A-0024", P2_NO)
    with site.runtime.session_factory() as db:
        db.get(JobPosting, P2).status = PostingStatus.closed
        db.commit()
    assert send(site, unknown)[0] == 202
    assert send(site, image, {"f": ("x.gif", b"GIF89a fictional picture")})[0] == 202
    assert send(site, scan, {"f": ("scan.pdf", (RESUMES / "봉채원_scan.pdf").read_bytes())})[0] == 202
    assert send(site, broken, {"f": ("x.docx", b"PK\x03\x04 not a zip")})[0] == 202
    assert send(site, closed)[0] == 202
    results = {e["application_no"]: finish(site, e["event_id"]) for e in (unknown, image, scan, broken, closed)}
    codes = {k: (v["status"], v["code"]) for k, v in results.items()}
    assert codes == {
        "A-0020": ("failed", "unknown_posting"),
        "A-0021": ("failed", "unsupported_attachment"),
        "A-0022": ("failed", "ocr_required"),
        "A-0023": ("failed", "unreadable_attachment"),
        "A-0024": ("failed", "posting_closed"),
    }
    assert results["A-0021"]["detail"].startswith("첨부 1(이력서): ")
    assert "OCR" in results["A-0022"]["detail"] and results["A-0022"]["fields"] == ["attachments[0]"]
    for body in results.values():  # a message names fields, never values
        assert p[1].a.name not in body["detail"] and "이력서.gif" not in body["detail"]
    with site.runtime.session_factory() as db:  # nothing half-made is left behind
        assert db.scalar(select(Candidate).where(Candidate.site_applicant_hash.is_not(None))) is None

    events = site.get("/api/admin/intake/events?status=failed").json()
    failed = {e["application_no"]: e for e in events}
    assert failed["A-0020"]["retriable"] and failed["A-0020"]["candidate"] is None
    summary = site.get("/api/admin/intake/summary").json()
    assert summary["configured"] and summary["totals"]["failed"] == 5
    by_no = {row["posting_no"]: row for row in summary["postings"]}
    assert by_no["DS-2026-0103"]["posting"] is None and by_no["DS-2026-0103"]["failed"] == 1
    assert by_no[P1_NO]["posting"]["id"] == P1

    # Link P3 on its posting screen, then 다시 처리.
    linked = site.patch(f"/api/postings/{P3}", json={"site_posting_no": "DS-2026-0103"})
    assert linked.status_code == 200 and linked.json()["site_posting_no"] == "DS-2026-0103"
    retried = site.post(f"/api/admin/intake/events/{failed['A-0020']['id']}/retry")
    assert retried.status_code == 200 and retried.json()["status"] == "queued"
    assert finish(site, unknown["event_id"])["status"] == "done"
    assert row_of(site, "A-0020").posting_id == P3
    assert site.post(f"/api/admin/intake/events/{failed['A-0020']['id']}/retry").status_code == 409

    with site.runtime.session_factory() as db:  # reopen P2, then retry every posting_closed in bulk
        db.get(JobPosting, P2).status = PostingStatus.open
        db.commit()
    bulk = site.post("/api/admin/intake/retry", json={"failure_code": "posting_closed"})
    assert bulk.json() == {"requeued": 1}
    assert finish(site, closed["event_id"])["status"] == "done"
    assert [a.details["previous"] for a in audits(site, "intake.retried")] == ["unknown_posting", "posting_closed"]


def test_posting_link_is_validated_unique_and_audited(site):
    taken = site.patch(f"/api/postings/{P3}", json={"site_posting_no": P1_NO})
    assert taken.status_code == 409
    bad = site.patch(f"/api/postings/{P3}", json={"site_posting_no": "공고 1"})
    assert bad.status_code == 422
    assert site.patch(f"/api/postings/{P1}", json={"site_posting_no": None}).json()["site_posting_no"] is None
    assert next(p for p in site.get("/api/postings").json() if p["id"] == P2)["site_posting_no"] == P2_NO
    [log] = audits(site, "posting.site_linked")
    assert log.details == {"from": P1_NO, "to": None}


def test_refused_items_and_unknown_fields_are_never_stored(seeded_db, tmp_path, no_external_network):
    with app_client(seeded_db, tmp_path / "min.db", tmp_path, intake_workers=0) as client:
        p = Person(40)
        rrn = "900101-1234567"
        photo = "iVBORw0KGgoAAAANSUhEUgfictionalphoto"
        cases = {
            "A-0030": ({"applicant": {**site_mod.applicant_block(p.a), "photo": photo}}, {}),
            "A-0031": ({"applicant": {**site_mod.applicant_block(p.a), "resident_registration_number": rrn}}, {}),
            "A-0032": ({"family": [{"relation": "부", "occupation": "가족직업값"}]}, {}),
            "A-0033": (
                {"attachments": [{"part": "pic", "kind": "photo", "filename": "me.jpg"}]},
                {"pic": ("me.jpg", b"\xff\xd8\xff fictional-photo-bytes")},
            ),
        }
        refused = {}
        for number, (extra, files) in cases.items():
            event = p.event("submitted", number, P1_NO, **extra)
            code, body = send(client, event, files)
            assert code == 422, body
            refused[number] = body
        assert {k: v["code"] for k, v in refused.items()} == dict.fromkeys(cases, "forbidden_field")
        assert refused["A-0030"]["fields"] == ["applicant.photo"]
        assert refused["A-0031"]["fields"] == ["applicant.resident_registration_number"]
        assert refused["A-0032"]["fields"] == ["family"] and "가족" in refused["A-0032"]["detail"]
        assert refused["A-0033"]["fields"] == ["attachments[0].kind"]
        again = send(client, p.event("submitted", "A-0030", P1_NO, applicant={**site_mod.applicant_block(p.a), "photo": photo}))
        assert again[0] == 422  # a new event id: refused again (a resend of the same id gets the same 422)

        missing = p.event("submitted", "A-0034", P1_NO)
        del missing["applicant"]["name"]
        del missing["consent"]
        code, body = send(client, missing)
        assert code == 422 and body["code"] == "missing_field"
        assert set(body["fields"]) == {"applicant.name", "consent"}

        extra = p.event("submitted", "A-0035", P1_NO)
        extra["applicant"]["military_service"] = "군필값"
        extra["form"]["hobby"] = "취미값"
        extra["form"]["career"][0]["salary"] = "연봉값"
        code, body = send(client, extra)
        assert code == 202
        assert sorted(body["dropped_fields"]) == ["applicant.military_service", "form.career[0].salary", "form.hobby"]

        with client.runtime.session_factory() as db:
            stored = {e.application_no: e for e in db.scalars(select(IntakeEvent)).all()}
            for number in cases:
                assert stored[number].status.value == "rejected" and stored[number].encrypted_payload is None
            payload = client.runtime.deid.open_payload(stored["A-0035"].encrypted_payload)
        for value in ("군필값", "취미값", "연봉값"):
            assert value not in payload
        assert p.a.name in payload  # what is kept is the spec's fields, encrypted
        raw = Path(client.runtime.settings.database_url.split("///", 1)[1]).read_bytes()
        for value in (rrn, photo, "가족직업값", "군필값", "취미값", p.a.name, p.a.phone):
            assert value.encode() not in raw
        assert not [
            f for f in Path(client.runtime.uploads_dir).rglob("*") if f.is_file() and b"fictional-photo" in f.read_bytes()
        ]


def test_events_left_in_the_queue_are_applied_after_a_restart(seeded_db, tmp_path, no_external_network):
    path = tmp_path / "restart.db"
    people = [Person(50 + i) for i in range(3)]
    events = [p.event("submitted", f"A-004{i}", P1_NO) for i, p in enumerate(people)]
    with app_client(seeded_db, path, tmp_path, intake_workers=0) as client:
        for event in events:
            assert send(client, event)[0] == 202
        statuses = {site_mod.status(transport(client), SECRET, e["event_id"])[1]["status"] for e in events}
        assert statuses == {"queued"}
        summary = client.get("/api/admin/intake/summary").json()
        assert summary["totals"]["queued"] == 3 and summary["workers"] == 0
    with app_client(seeded_db, path, tmp_path, intake_workers=2) as client:
        assert {finish(client, e["event_id"])["status"] for e in events} == {"done"}


def test_the_fake_site_scenario_applies_concurrently_without_duplicates(seeded_db, tmp_path, no_external_network):
    with app_client(seeded_db, tmp_path / "scenario.db", tmp_path, intake_workers=4) as client:
        plans = site_mod.scenario(["DS-2026-0101", "DS-2026-0102", "DS-2026-0103"], 80, seed=3)
        report = site_mod.run(transport(client), SECRET, plans, wait=60, poll=0.05)
        assert report.unexpected == [] and report.pending_ids == []
        assert report.duplicates >= report.labels["resend"]
        assert report.refused_codes and set(report.refused_codes) <= {"forbidden_field", "missing_field"}
        # P3 is not linked (and the 9999 number); the deliberate HWP is unsupported or, where HWP can be
        # read, a broken file
        assert set(report.failures) <= {"unknown_posting", "unsupported_attachment", "unreadable_attachment"}
        assert report.final["done"] > 40

        submits = [p for p in plans if p.label in ("submit", "update", "update-before-submit")]
        with client.runtime.session_factory() as db:
            apps = db.scalars(select(Application).where(Application.site_application_no.is_not(None))).all()
            numbers = [a.site_application_no for a in apps]
            assert len(numbers) == len(set(numbers))
            per_person: dict[str, set[str]] = {}
            for plan in submits:
                app = next((a for a in apps if a.site_application_no == plan.event["application_no"]), None)
                if app is not None:
                    per_person.setdefault(plan.event["applicant"]["applicant_no"], set()).add(app.candidate_id)
            assert per_person and all(len(ids) == 1 for ids in per_person.values())
            candidates = {a.candidate_id for a in apps}
            assert len(candidates) == len(per_person)


# --- privacy over every response ------------------------------------------------------------


def test_no_response_or_screen_carries_names_numbers_or_raw_paths(site):
    people = [Person(60 + i) for i in range(3)]
    data = (RESUMES / "이력서_문태오.docx").read_bytes()
    submit(site, people[0], "A-0050", P1_NO)
    submit(site, people[0], "A-0051", P2_NO)
    with_file = people[1].event(
        "submitted", "A-0052", P2_NO, attachments=[{"part": "cv", "kind": "resume", "filename": "이력서_문태오.docx"}]
    )
    send(site, with_file, {"cv": ("이력서_문태오.docx", data)})
    finish(site, with_file["event_id"])
    submit(site, people[2], "A-0053", "DS-NOT-LINKED")
    paths = get_paths(site) + ["/api/admin/intake/summary", "/api/admin/intake/events?limit=1000"]
    secrets = []
    for p in people:
        secrets += [p.a.name, p.a.phone, p.a.phone.replace("-", ""), p.a.email, p.a.applicant_no, p.a.english, p.a.address]
    for path in paths:
        response = site.get(path)
        assert response.status_code == 200, path
        for value in secrets:
            assert value not in response.text, (path, value)
        for marker in ("uploads", "file:", "encrypted"):
            assert marker not in response.text, (path, marker)
        if not path.endswith("/stream"):
            assert not json_keys(response.json()) & {"applicant_no", "encrypted_payload", "fingerprint", "source_file_uri"}
    events = site.get("/api/admin/intake/events").json()
    assert {e["candidate"]["pseudonym"] for e in events if e["candidate"]} >= {"CAND-0021"}
    for key, value in walk_json(events):
        if key.endswith("pseudonym"):
            assert value.startswith("CAND-")


def test_admin_screens_are_admins_only(site):
    with site.runtime.session_factory() as db:
        from interview_assistant.models import Interviewer

        for person in db.scalars(select(Interviewer)).all():
            person.is_admin = False
        db.commit()
    assert site.get("/api/admin/intake/summary").status_code == 403
    assert site.get("/api/admin/intake/events").status_code == 403
    assert site.post("/api/admin/intake/retry", json={}).status_code == 403


# --- forms ----------------------------------------------------------------------------------


def test_career_months_count_overlaps_once_and_open_ends_until_now():
    from datetime import date

    career = [
        CareerField(company="가", start="2020-01", end="2020-12"),
        CareerField(company="나", start="2020-07", end="2021-06"),
        CareerField(company="다", start="2023-01"),
    ]
    assert career_months(career, today=date(2023, 12, 15)) == 18 + 12
    profile = build_profile(FormFields(career=career, skills=["Python"]), today=date(2023, 12, 15))
    assert profile.years_experience == 2.5 and profile.experience[0].period == "2023.01 – 현재"
    with pytest.raises(ValueError):
        CareerField(company="가", start="2021-01", end="2020-01")
