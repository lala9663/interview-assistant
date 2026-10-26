"""관리자 > 모델 설정 > 서류 읽기: catalog, requirements, the reading test, apply and rollback,
settings pinned per application, and the intake's failure codes. Fake providers, no network."""

from __future__ import annotations

import json

from sqlalchemy import select

from interview_assistant.models import AuditLog
from interview_assistant.providers import catalog

from .conftest import ROOT

RESUMES = ROOT / "tests" / "fixtures" / "resumes"
P2 = "b1d6a0c2-1f3e-4b8a-9c41-5e2f7a9d0002"  # an open posting of the demo seed


def _check(api, role: str, impl: str, options: dict | None = None):
    return api.post(f"/api/admin/models/{role}/check", json={"impl": impl, "options": options or {}})


def _test(api, role: str, spec: dict, *, document: tuple[str, bytes] | None = None, **form):
    files = {"document": document} if document else None
    data = {"spec": json.dumps(spec), **{k: str(v).lower() if isinstance(v, bool) else v for k, v in form.items()}}
    return api.post(f"/api/admin/models/{role}/test", data=data, files=files)


def _apply(api, role: str, impl: str, options: dict | None = None, reason: str = "테스트"):
    return api.post(f"/api/admin/models/{role}/apply", json={"impl": impl, "options": options or {}, "reason": reason})


def _upload(api, name: str, data: bytes | None = None, person: str = "가나다"):
    data = data if data is not None else (RESUMES / name).read_bytes()
    return api.post(f"/api/postings/{P2}/applications", data={"name": person}, files={"file": (name, data)})


def test_document_roles_are_their_own_group(api):
    roles = api.get("/api/admin/models").json()["roles"]
    groups = {r["role"]: r["group"] for r in roles}
    assert [k for k, g in groups.items() if g == "documents"] == [
        "document.reading", "document.ocr", "document.pdf", "document.hwp", "document.legacy",
    ]  # fmt: skip
    state = {r["role"]: r for r in roles}
    assert state["document.ocr"]["spec"]["impl"] == "fake" and state["document.ocr"]["status"] == "ready"
    assert state["document.reading"]["model"].startswith("자동")


def test_catalog_describes_engines_where_they_run_and_what_they_need(api):
    impls = {(i["kind"], i["impl"]): i for i in api.get("/api/admin/models/catalog").json()}
    paddle = impls[("ocr", "paddleocr")]
    assert paddle["data_location"] == "local" and "Apache-2.0" in paddle["license"]
    sizes = {c["value"]: c["size_bytes"] for c in paddle["options"][0]["choices"]}
    assert sizes["ppocrv5-mobile"] == 32288476 and sizes["ppocrv5-server"] > 100_000_000
    assert impls[("ocr", "clova_ocr")]["data_location"] == "external"
    assert impls[("ocr", "google_document_ai")]["data_location"] == "gcp"
    assert {i["impl"] for k, i in impls.items() if k[0] == "hwp_reader"} == {"syhwp", "hwplib"}
    assert {r["key"] for r in impls[("office_converter", "libreoffice")]["requirements"]} >= {"program:soffice"}


def test_requirements_report_models_programs_and_credentials_without_reading_secrets(api):
    paddle = _check(api, "document.ocr", "paddleocr", {"model": "ppocrv5-mobile"}).json()
    weights = next(r for r in paddle["requirements"] if r["key"].startswith("weights:"))
    assert not weights["ok"] and "32MB" in weights["detail"] and not paddle["ready"]
    clova = _check(api, "document.ocr", "clova_ocr").json()
    assert clova["external"] and not clova["ready"]
    unmet = {r["key"] for r in clova["requirements"] if not r["ok"]}
    assert {"implemented", "env:CLOVA_OCR_INVOKE_URL", "env:CLOVA_OCR_SECRET"} <= unmet
    assert _apply(api, "document.ocr", "paddleocr", {"model": "ppocrv5-mobile"}).status_code == 409


def test_reading_test_on_the_built_in_sample_shows_how_and_never_the_raw_text(api):
    res = _test(api, "document.hwp", {"impl": "syhwp", "options": {}})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] and body["document"] == "sample" and body["summary"].startswith("HWPX 1쪽")
    out = body["output"]
    assert out["format"] == "hwpx" and out["pages"][0]["method"] == "text"
    assert {i["decision"] for i in out["images"]} == {"photo", "ocr"}
    assert "도하윤" not in json.dumps(out, ensure_ascii=False)  # name, phone, e-mail only as tokens
    assert "010-0517-2846" not in out["preview"] and "[지원자]" in out["preview"]
    with api.runtime.session_factory() as db:
        row = db.scalars(select(AuditLog).where(AuditLog.action == "model.tested")).all()[-1]
    assert row.details["document"] == "sample" and row.details["format"] == "hwpx"
    assert "도하윤" not in json.dumps(row.details, ensure_ascii=False)


def test_reading_test_on_an_uploaded_file_with_the_candidate_setting(api):
    garbled = (RESUMES / "남주원_이력서(한글변환).pdf").read_bytes()
    spec = {"impl": "standard", "options": {"mode": "text_only"}}
    held = _test(api, "document.reading", spec, document=("x.pdf", garbled), name="남주원").json()
    assert held["ok"] and "보류합니다" in held["summary"] and held["document"] == "upload"  # as intended
    assert "preview" not in held["output"]  # nothing de-identified, nothing shown
    auto = _test(api, "document.reading", {"impl": "standard", "options": {"mode": "auto"}}, document=("x.pdf", garbled), name="남주원").json()
    assert auto["ok"] and [p["method"] for p in auto["output"]["pages"]] == ["ocr", "ocr"]
    assert all("깨짐" in p["reason"] for p in auto["output"]["pages"])
    assert "남주원" not in auto["output"]["preview"] and "ÀÌ" not in auto["output"]["preview"]


def test_apply_and_rollback_the_reading_mode_and_pin_work_in_progress(api):
    before = api.runtime.models.active.reader  # what an upload starting now would use
    res = _apply(api, "document.reading", "standard", {"mode": "text_only", "embedded_images": False}, "OCR 끄기")
    assert res.status_code == 200 and res.json()["model"] == "텍스트만 · 그림 OCR 끔 · 깨짐 판정 medium"
    after = api.runtime.models.active.reader
    assert before.policy.mode == "auto" and after.policy.mode == "text_only"  # in-flight work keeps its own
    assert after.revision == before.revision + 1
    change = api.get("/api/admin/models/history?role=document.reading").json()[0]
    reverted = api.post(f"/api/admin/models/history/{change['id']}/revert", json={"reason": "원래대로"})
    assert reverted.status_code == 200 and api.runtime.models.active.reader.policy.mode == "auto"


def test_uploads_record_how_they_were_read_and_name_why_not(api, monkeypatch, tmp_path):
    hwpx = _upload(api, "이력서_도하윤.hwpx", person="도하윤")
    assert hwpx.status_code == 201, hwpx.text
    reading = hwpx.json()["document"]["reading"]
    assert reading["files"][0]["format"] == "hwpx" and reading["files"][0]["photos_dropped"] == 1
    assert any(t.startswith("syhwp") for t in reading["tools"])

    locked = _upload(api, "변예준_이력서_암호.hwp", person="변예준")
    assert locked.status_code == 422 and "암호" in locked.json()["detail"][0]["msg"]

    monkeypatch.setenv("SOFFICE_CMD", str(tmp_path / "missing-soffice.exe"))
    legacy = _upload(api, "탁서아_이력서_구버전.doc", person="탁서아")
    assert legacy.status_code == 422 and "LibreOffice" in legacy.json()["detail"][0]["msg"]

    photo = _upload(api, "KakaoTalk_20261012_093015123.jpg", person="기서윤")
    assert photo.status_code == 201 and photo.json()["document"]["reading"]["files"][0]["ocr_pages"] == [1]


def test_every_document_role_is_in_the_catalog():
    roles = {r.key for r in catalog.ROLES if r.group == "documents"}
    assert roles == {"document.reading", "document.ocr", "document.pdf", "document.hwp", "document.legacy"}
    for role in roles:
        assert any(role in i.roles for i in catalog.all_impls()), role
