"""관리자 > 모델 설정: catalog, admin-only API, connection tests, switching without a restart,
session pinning, rollback, external-transfer confirmation. Fake providers, no network."""

from __future__ import annotations

import io
import json
import math
import shutil
import struct
import threading
import wave

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from interview_assistant.main import create_app
from interview_assistant.models import (
    AiModelChange,
    AiModelSetting,
    AuditLog,
    Interviewer,
    InterviewSession,
    Score,
    TranscriptSegment,
)
from interview_assistant.providers import catalog, registry
from interview_assistant.providers.catalog import ROLES, DataLocation, ImplInfo, OptionField
from interview_assistant.providers.fake import FakeLLM, FakeSTT
from tests.api_util import (
    COMPLETED,
    LIVE,
    LIVE2,
    P3,
    SCHEDULED,
    round_id,
    sse_events,
    wait_for,
)
from tests.conftest import ROOT, api_settings, file_session_factory, instant_providers

FAST_LLM = {"impl": "fake", "options": {"model": "fake-llm-v2", "speed": 0}}

# The first start seeds one revision per role (AI models and 서류 읽기).
INITIAL = len(ROLES)


def _apply(api, role: str, spec: dict, reason: str = "테스트로 교체", **extra):
    return api.post(f"/api/admin/models/{role}/apply", json={**spec, "reason": reason, **extra})


def _test(api, role: str, spec: dict, audio: bytes | None = None, **form):
    files = {"audio": ("rec.wav", audio, "audio/wav")} if audio is not None else None
    data = {"spec": json.dumps(spec), **{k: str(v).lower() for k, v in form.items()}}
    return api.post(f"/api/admin/models/{role}/test", data=data, files=files)


def _audits(api, action: str) -> list[AuditLog]:
    with api.runtime.session_factory() as db:
        return list(db.scalars(select(AuditLog).where(AuditLog.action == action)))


def _tone_wav(seconds: float) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        n = int(seconds * 16000)
        w.writeframes(
            struct.pack(
                f"<{n}h", *(int(8000 * math.sin(i * 440 * 2 * math.pi / 16000)) for i in range(n))
            )
        )
    return buf.getvalue()


# --- catalog and requirements ----------------------------------------------------------------


def test_catalog_lists_every_role_and_whisper_needs_its_weights(api, tmp_path):
    impls = api.get("/api/admin/models/catalog").json()
    by = {(i["kind"], i["impl"]): i for i in impls}
    whisper = by[("stt", "faster_whisper")]
    assert whisper["data_location"] == "local" and set(whisper["roles"]) == {
        "stt.streaming",
        "stt.batch",
    }
    sizes = next(f for f in whisper["options"] if f["key"] == "model")["choices"]
    assert [c["value"] for c in sizes] == ["small", "medium", "large-v3", "large-v3-turbo"]
    assert all(c["downloaded"] is False and c["size_bytes"] > 400_000_000 for c in sizes)
    assert whisper["role_defaults"]["stt.streaming"]["model"] == "medium"
    assert whisper["role_defaults"]["stt.batch"]["model"] == "large-v3"
    language = next(f for f in whisper["options"] if f["key"] == "language")
    assert language["fixed"] and language["default"] == "ko-KR"

    vertex = by[("llm", "anthropic_vertex")]
    assert vertex["data_location"] == "gcp"
    reqs = {r["key"]: r for r in vertex["requirements"]}
    assert reqs["implemented"]["ok"] is False
    assert {"env:GOOGLE_CLOUD_PROJECT", "gcp_credentials"} <= set(reqs)
    for role in (
        "llm.primary",
        "llm.screening",
        "stt.streaming",
        "stt.batch",
        "embedding",
        "diarization",
    ):
        assert any(role in i["roles"] for i in impls), role


def test_requirements_say_whether_credentials_exist_never_what_they_are(api, monkeypatch, tmp_path):
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "secret-project-4242")
    key = tmp_path / "sa.json"
    key.write_text('{"private_key": "-----BEGIN SECRET-----"}', encoding="utf-8")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(key))
    body = api.get("/api/admin/models/catalog").text
    assert (
        "secret-project-4242" not in body and "BEGIN SECRET" not in body and "sa.json" not in body
    )
    vertex = next(i for i in json.loads(body) if i["impl"] == "anthropic_vertex")
    reqs = {r["key"]: r for r in vertex["requirements"]}
    assert reqs["env:GOOGLE_CLOUD_PROJECT"]["ok"] and reqs["gcp_credentials"]["ok"]
    assert not reqs["implemented"]["ok"]  # still cannot be applied


def test_check_validates_options_and_never_calls_the_provider(api):
    ok = api.post(
        "/api/admin/models/stt.batch/check",
        json={
            "impl": "faster_whisper",
            "options": {"model": "small", "initial_prompt": " CMP, 식각 "},
        },
    ).json()
    assert ok["spec"]["options"]["initial_prompt"] == "CMP, 식각"
    assert ok["spec"]["options"]["beam_size"] == 5  # batch default filled in
    assert ok["ready"] is False
    assert (
        next(r for r in ok["requirements"] if r["key"] == "weights:faster-whisper/small")["ok"]
        is False
    )

    def detail(body):
        response = api.post("/api/admin/models/stt.batch/check", json=body)
        assert response.status_code == 422, response.text
        return response.json()["detail"][0]

    assert detail({"impl": "faster_whisper", "options": {"weights_dir": "C:/"}})["loc"] == [
        "body",
        "weights_dir",
    ]
    assert detail({"impl": "faster_whisper", "options": {"model": "tiny"}})["loc"][-1] == "model"
    assert detail({"impl": "faster_whisper", "options": {"beam_size": 9}})["loc"][-1] == "beam_size"
    assert (
        detail({"impl": "faster_whisper", "options": {"language": "en-US"}})["loc"][-1]
        == "language"
    )
    assert detail({"impl": "fake", "options": {"dimensions": 4}})["loc"][-1] == "dimensions"
    wrong_role = api.post("/api/admin/models/llm.primary/check", json={"impl": "faster_whisper"})
    assert wrong_role.status_code == 422


# --- admin only ------------------------------------------------------------------------------


def test_only_admins_reach_model_settings(api):
    assert api.get("/api/me").json()["is_admin"] is True
    with api.runtime.session_factory() as db:
        me = db.scalars(select(Interviewer).where(Interviewer.employee_no == "E24017")).one()
        me.is_admin = False
        db.commit()
    assert api.get("/api/me").json()["is_admin"] is False
    calls = [
        ("get", "/api/admin/models", None),
        ("get", "/api/admin/models/catalog", None),
        ("get", "/api/admin/models/history", None),
        ("get", "/api/admin/models/downloads", None),
        ("post", "/api/admin/models/llm.primary/check", {"impl": "fake"}),
        ("post", "/api/admin/models/llm.primary/apply", {**FAST_LLM, "reason": "x"}),
        ("post", "/api/admin/models/downloads", {"impl": "faster_whisper", "model": "small"}),
        ("delete", "/api/admin/models/downloads/faster_whisper/small", None),
    ]
    for method, path, body in calls:
        response = getattr(api, method)(path, **({"json": body} if body else {}))
        assert response.status_code == 403, path
        assert response.json()["detail"] == "관리자만 쓸 수 있습니다."
    assert _test(api, "llm.primary", FAST_LLM).status_code == 403
    with api.runtime.session_factory() as db:
        assert db.scalar(select(AiModelChange).where(AiModelChange.kind == "apply")) is None


# --- settings seeded from the YAML ------------------------------------------------------------


def test_first_start_seeds_the_settings_from_the_yaml_once(
    seeded_db, tmp_path, no_external_network
):
    template, key = seeded_db
    path = tmp_path / "seed.db"
    shutil.copyfile(template, path)
    factory = file_session_factory(path)
    settings = api_settings(path, key, tmp_path)
    with TestClient(
        create_app(settings, providers=instant_providers(), session_factory=factory)
    ) as api:
        body = api.get("/api/admin/models").json()
        assert body["revision"] == INITIAL and body["persistent"] is True
        assert {r["role"]: r["spec"]["impl"] for r in body["roles"]} == {
            "llm.primary": "fake",
            "llm.screening": "fake",
            "stt.streaming": "fake",
            "stt.batch": "fake",
            "embedding": "fake",
            "diarization": "fake",
            "document.reading": "standard",
            "document.ocr": "fake",
            "document.pdf": "pdfplumber",
            "document.hwp": "syhwp",
            "document.legacy": "libreoffice",
            "audio.vad": "silero",
            "audio.turn": "silence",
            "audio.denoise": "off",
        }
        history = api.get("/api/admin/models/history").json()
        assert [h["kind"] for h in history] == ["initial"] * INITIAL
        assert all(h["actor"] is None and h["reason"] == "providers YAML 기본값" for h in history)
        assert _apply(api, "llm.primary", FAST_LLM).status_code == 200

    # Later starts read the database; the YAML (even another one) no longer decides.
    other = tmp_path / "other.yaml"
    other.write_text(
        (ROOT / "config" / "providers.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    settings = api_settings(path, key, tmp_path, providers_file=other)
    with TestClient(create_app(settings, session_factory=factory)) as api:
        body = api.get("/api/admin/models").json()
        assert body["revision"] == INITIAL + 1
        primary = next(r for r in body["roles"] if r["role"] == "llm.primary")
        assert primary["spec"] == FAST_LLM and primary["model"] == "fake-llm-v2"
        assert api.get("/health").json()["providers"]["stt"]["batch"] == "FakeSTT"
    factory.kw["bind"].dispose()


def test_a_broken_stored_spec_does_not_stop_the_server(seeded_db, tmp_path, no_external_network):
    template, key = seeded_db
    path = tmp_path / "broken.db"
    shutil.copyfile(template, path)
    factory = file_session_factory(path)
    with TestClient(create_app(api_settings(path, key, tmp_path), session_factory=factory)):
        pass
    with factory() as db:  # e.g. the weights folder was deleted after the switch
        row = db.get(AiModelSetting, "llm.primary")
        row.spec = {"impl": "anthropic_vertex", "options": {"model": "claude-opus-5-5"}}
        db.commit()
    with TestClient(create_app(api_settings(path, key, tmp_path), session_factory=factory)) as api:
        primary = next(
            r for r in api.get("/api/admin/models").json()["roles"] if r["role"] == "llm.primary"
        )
        assert primary["status"] == "unavailable" and "구현" in primary["status_detail"]
        response = api.post(f"/api/rounds/{round_id(api, P3)}/competency-sets/generate")
        assert response.status_code == 503
        assert "LLM 주 모델" in response.json()["detail"]
    factory.kw["bind"].dispose()


# --- connection tests ------------------------------------------------------------------------


def test_llm_test_checks_structured_output_through_the_gateway(api):
    result = _test(api, "llm.primary", FAST_LLM).json()
    assert result["ok"] is True and result["model"] == "fake-llm-v2"
    assert result["output"]["structured"] == {"echo": "모델 연결 확인 문장입니다", "sum": 42}
    assert result["output"]["first_token_ms"] is not None and "첫 토큰" in result["summary"]
    rows = _audits(api, "model.connection_test")  # the structured call and the stream
    assert len(rows) == 2
    assert all(r.model == "fake-llm-v2" and r.actor_type.value == "ai" for r in rows)
    [user_row] = _audits(api, "model.tested")
    assert user_row.target_id == "llm.primary" and user_row.details["ok"] is True
    assert "structured" not in user_row.details  # outcome only, never content
    # Testing changes nothing.
    assert api.get("/api/admin/models").json()["revision"] == INITIAL


def test_stt_embedding_and_diarization_tests(api):
    batch = _test(api, "stt.batch", {"impl": "fake", "options": {"speed": 0}}).json()
    assert batch["ok"] and batch["audio"] == "sample"
    assert batch["output"]["text"].startswith("[fake 전사] 오디오 11.5초")
    assert batch["output"]["expected_text"].startswith("커리는") and batch["output"]["cer"] > 0.5

    streaming = _test(
        api, "stt.streaming", {"impl": "fake", "options": {"speed": 0}}, audio=_tone_wav(3)
    ).json()
    assert streaming["ok"] and streaming["audio"] == "upload"
    assert streaming["output"]["text"].startswith("[fake 전사] 오디오 3.0초")
    assert "expected_text" not in streaming["output"]

    embedding = _test(api, "embedding", {"impl": "fake", "options": {"dimensions": 16}}).json()
    assert embedding["ok"] and embedding["output"]["dimensions"] == 16
    diarization = _test(api, "diarization", {"impl": "fake", "options": {}}).json()
    assert diarization["ok"] and diarization["output"]["turns"] == 2

    too_long = _test(api, "stt.batch", {"impl": "fake", "options": {}}, audio=_tone_wav(61))
    assert too_long.status_code == 422
    not_audio = _test(api, "stt.batch", {"impl": "fake", "options": {}}, audio=b"not audio at all")
    assert not_audio.status_code == 422
    assert {r.details["audio"] for r in _audits(api, "model.tested")} == {"sample", "upload", None}


def test_testing_a_model_without_its_weights_is_refused(api):
    response = _test(api, "stt.batch", {"impl": "faster_whisper", "options": {"model": "small"}})
    assert response.status_code == 409
    assert "모델 파일 small" in response.json()["detail"]


# --- switching without a restart --------------------------------------------------------------


def test_apply_swaps_new_work_while_sessions_keep_their_providers(api):
    live = api.get(f"/api/sessions/{LIVE}").json()
    answered = next(q for q in live["qa_items"] if q["answer_deidentified"])

    state = _apply(api, "llm.primary", FAST_LLM, reason="새 모델 시험").json()
    assert state["model"] == "fake-llm-v2" and state["status"] == "ready"
    assert state["last_change"]["actor"]["employee_no"] == "E24017"
    assert state["last_change"]["reason"] == "새 모델 시험"
    assert state["pinned_sessions"] >= 1  # LIVE in progress (and C4 if its scoring still runs)
    assert api.get("/health").json()["ai_config_revision"] == INITIAL + 1
    [audit] = _audits(api, "model.applied")
    assert audit.details["revision"] == INITIAL + 1 and audit.details["model"] == "fake-llm-v2"

    # New work outside sessions: the new model.
    assert api.post(f"/api/rounds/{round_id(api, P3)}/competency-sets/generate").status_code == 201
    assert _audits(api, "competency_set.generated")[-1].model == "fake-llm-v2"

    # The interview already running keeps the model it started with ...
    batch = sse_events(
        api.post(f"/api/sessions/{LIVE}/follow-ups", json={"qa_item_id": answered["id"]}).text
    )[0][1]
    assert batch["model"] == "fake-llm"
    # ... and so does its AI scoring after it ends.
    api.post(f"/api/sessions/{LIVE}/end")
    wait_for(api, f"/api/sessions/{LIVE}/evaluation", lambda b: b["ai"]["status"] == "completed")
    with api.runtime.session_factory() as db:
        models = {
            s.model
            for s in db.scalars(
                select(Score).where(Score.session_id == LIVE, Score.evaluator_type == "ai")
            )
        }
        assert models == {"fake-llm"}
        assert db.get(InterviewSession, LIVE).ai_config_revision == INITIAL

    # An interview that starts now uses the new one.
    api.post(f"/api/sessions/{SCHEDULED}/consent", json={"consent_recording": True})
    api.post(f"/api/sessions/{SCHEDULED}/start")
    qa = api.post(
        f"/api/sessions/{SCHEDULED}/qa-items",
        json={"question": "자기소개 부탁드립니다.", "question_source": "interviewer"},
    ).json()
    wait_for(api, f"/api/sessions/{SCHEDULED}", lambda b: b["qa_items"][-1]["answer_deidentified"])
    batch = sse_events(
        api.post(f"/api/sessions/{SCHEDULED}/follow-ups", json={"qa_item_id": qa["id"]}).text
    )[0][1]
    assert batch["model"] == "fake-llm-v2"
    with api.runtime.session_factory() as db:
        assert db.get(InterviewSession, SCHEDULED).ai_config_revision == INITIAL + 1
        segments = db.scalars(
            select(TranscriptSegment).where(
                TranscriptSegment.session_id == SCHEDULED, TranscriptSegment.speaker == "candidate"
            )
        ).all()
        assert segments and {s.model for s in segments} == {"fake-stt"}
    assert _audits(api, "transcript.listened")[-1].model == "fake-stt"


class _GatedLLM(FakeLLM):
    """FakeLLM whose scoring calls wait until the test opens the gate."""

    gate = threading.Event()
    entered = threading.Event()

    async def generate(self, system, prompt, **kwargs):
        if (kwargs.get("schema") or {}).get("title") == "AnswerScores":
            import asyncio

            _GatedLLM.entered.set()
            await asyncio.to_thread(_GatedLLM.gate.wait, 10)
        return await super().generate(system, prompt, **kwargs)


def test_ai_scoring_in_flight_finishes_on_the_provider_it_started_with(api, monkeypatch):
    monkeypatch.setitem(registry._IMPLS["llm"], "gated", f"{__name__}:_GatedLLM")
    gated = ImplInfo(
        "llm",
        "gated",
        "Gated",
        "",
        DataLocation.local,
        "",
        "test",
        ("llm.primary",),
        options=(OptionField("model", "모델", "string", "gated-llm"),),
    )
    catalog.register(gated)
    try:
        _GatedLLM.gate.clear()
        _GatedLLM.entered.clear()
        assert _apply(api, "llm.primary", {"impl": "gated", "options": {}}).status_code == 200
        api.post(f"/api/sessions/{SCHEDULED}/consent", json={"consent_recording": False})
        api.post(f"/api/sessions/{SCHEDULED}/start")
        qa = api.post(
            f"/api/sessions/{SCHEDULED}/qa-items",
            json={"question": "가장 어려웠던 문제는?", "question_source": "interviewer"},
        ).json()
        api.patch(
            f"/api/qa-items/{qa['id']}",
            json={"answer_text": "식각 공정에서 수율 문제를 데이터로 풀었습니다."},
        )
        api.post(f"/api/sessions/{SCHEDULED}/end")
        assert _GatedLLM.entered.wait(5)
        # Switch while scoring waits inside the old provider.
        assert _apply(api, "llm.primary", FAST_LLM).status_code == 200
        running = api.get(f"/api/sessions/{SCHEDULED}/evaluation").json()["ai"]
        assert running["status"] == "running" and running["model"] == "gated-llm"
        _GatedLLM.gate.set()
        done = wait_for(
            api, f"/api/sessions/{SCHEDULED}/evaluation", lambda b: b["ai"]["status"] == "completed"
        )
        assert done["ai"]["model"] == "gated-llm"
        assert {s["model"] for s in done["ai"]["scores"]} <= {"gated-llm"}
    finally:
        _GatedLLM.gate.set()
        catalog.unregister(gated)


def test_apply_refuses_what_it_cannot_run(api):
    def refused(spec, status, **extra):
        response = _apply(api, "llm.primary", spec, **extra)
        assert response.status_code == status, response.text
        return response.json()["detail"]

    assert "지금 쓰는 설정과 같습니다" in refused(
        {"impl": "fake", "options": {"model": "fake-llm", "speed": 1}}, 409
    )
    vertex = {"impl": "anthropic_vertex", "options": {}}
    assert "회사 밖" in refused(vertex, 409)  # Google Cloud is outside the company
    assert "구현" in refused(vertex, 409, confirm_external=True)
    assert (
        refused({"impl": "fake", "options": {"temperature": 1}}, 422)[0]["loc"][-1] == "temperature"
    )
    assert refused(FAST_LLM, 422, reason="  ")[0]["loc"][-1] == "reason"
    assert refused({"impl": "nope", "options": {}}, 422)[0]["loc"][-1] == "impl"
    whisper = api.post(
        "/api/admin/models/stt.batch/apply",
        json={"impl": "faster_whisper", "options": {"model": "large-v3"}, "reason": "정확도"},
    )
    assert whisper.status_code == 409 and "모델 파일 large-v3" in whisper.json()["detail"]
    assert api.get("/api/admin/models").json()["revision"] == INITIAL
    assert not _audits(api, "model.applied")


def test_rollback_restores_the_previous_spec_and_is_recorded(api):
    _apply(api, "llm.primary", FAST_LLM)
    change = api.get("/api/admin/models/history?role=llm.primary").json()[0]
    assert change["kind"] == "apply" and change["previous"]["impl"] == "fake"
    assert change["new_label"] == "Fake LLM · fake-llm-v2" and change["role_label"] == "LLM 주 모델"

    state = api.post(
        f"/api/admin/models/history/{change['id']}/revert", json={"reason": "원래대로"}
    ).json()
    assert state["model"] == "fake-llm" and state["spec"]["options"]["speed"] == 1
    latest = api.get("/api/admin/models/history").json()[0]
    assert latest["kind"] == "rollback" and latest["reverts_change_id"] == change["id"]
    assert latest["revision"] == INITIAL + 2 and latest["reason"] == "원래대로"
    assert _audits(api, "model.reverted")[0].details["revision"] == INITIAL + 2

    again = api.post(
        f"/api/admin/models/history/{change['id']}/revert", json={"reason": "한 번 더"}
    )
    assert again.status_code == 409  # already the active spec
    initial = api.get("/api/admin/models/history?role=embedding").json()[0]
    assert (
        api.post(
            f"/api/admin/models/history/{initial['id']}/revert", json={"reason": "x"}
        ).status_code
        == 409
    )
    assert (
        api.post("/api/admin/models/history/nope/revert", json={"reason": "x"}).status_code == 404
    )


def test_providers_sending_data_outside_need_confirmation_and_a_reason(api, monkeypatch):
    monkeypatch.setitem(
        registry._IMPLS["llm"], "outside", "interview_assistant.providers.fake:FakeLLM"
    )
    outside = ImplInfo(
        "llm",
        "outside",
        "Outside API",
        "",
        DataLocation.external,
        "회사 밖",
        "test",
        ("llm.primary",),
        options=(OptionField("model", "모델", "string", "outside-llm"),),
    )
    catalog.register(outside)
    try:
        spec = {"impl": "outside", "options": {}}
        assert _test(api, "llm.primary", spec).status_code == 409
        assert _test(api, "llm.primary", spec, confirm_external=True).json()["ok"] is True
        refused = _apply(api, "llm.primary", spec)
        assert refused.status_code == 409 and "회사 밖" in refused.json()["detail"]
        assert _apply(api, "llm.primary", spec, reason="", confirm_external=True).status_code == 422
        state = _apply(
            api, "llm.primary", spec, reason="외부 API 평가", confirm_external=True
        ).json()
        assert state["data_location"] == "external" and state["model"] == "outside-llm"
        change = api.get("/api/admin/models/history").json()[0]
        assert change["details"]["confirmed_external"] is True
        assert _audits(api, "model.applied")[0].details["confirmed_external"] is True
    finally:
        catalog.unregister(outside)


def test_a_streaming_stt_that_cannot_read_the_simulated_candidate_goes_manual(api, monkeypatch):
    class PcmOnly(FakeSTT):
        accepts = frozenset({"audio/pcm;rate=16000"})

    monkeypatch.setitem(registry._IMPLS["stt"], "pcm_only", f"{__name__}:PcmOnly")
    globals()["PcmOnly"] = PcmOnly
    info = ImplInfo(
        "stt", "pcm_only", "PCM only", "", DataLocation.local, "", "test", ("stt.streaming",)
    )
    catalog.register(info)
    try:
        assert _apply(api, "stt.streaming", {"impl": "pcm_only", "options": {}}).status_code == 200
        api.post(f"/api/sessions/{SCHEDULED}/consent", json={"consent_recording": True})
        api.post(f"/api/sessions/{SCHEDULED}/start")
        api.post(
            f"/api/sessions/{SCHEDULED}/qa-items",
            json={"question": "자기소개 부탁드립니다.", "question_source": "interviewer"},
        )
        for _ in range(200):
            if _audits(api, "transcript.unsupported_audio"):
                break
            threading.Event().wait(0.01)
        [row] = _audits(api, "transcript.unsupported_audio")
        assert row.details["audio"] == "text/plain"
        assert api.runtime.hub.status(SCHEDULED)["stt"] == "down"
        # The interviewer types the answer instead.
        qa = api.get(f"/api/sessions/{SCHEDULED}").json()["qa_items"][-1]
        assert (
            api.patch(f"/api/qa-items/{qa['id']}", json={"answer_text": "수기 답변"}).status_code
            == 200
        )
    finally:
        catalog.unregister(info)


def test_unused_provider_instances_are_dropped(api):
    old = api.runtime.models.active.get("llm.primary")
    _apply(api, "llm.primary", FAST_LLM)
    for live in (LIVE, LIVE2):  # both interviews in progress keep the old provider until they end
        api.post(f"/api/sessions/{live}/end")
        wait_for(api, f"/api/sessions/{live}/evaluation", lambda b: b["ai"]["status"] == "completed")
    c4 = "0a1b2c3d-0000-4000-9000-c40000000000"
    wait_for(api, f"/api/sessions/{c4}/evaluation", lambda b: b["ai"]["status"] == "completed")
    api.runtime.models.evict()
    held = list(api.runtime.models._instances.values())
    assert all(p is not old for p in held)
    assert api.runtime.models.active.get("llm.primary").model == "fake-llm-v2"
    assert api.get(f"/api/sessions/{COMPLETED}/evaluation").json()["ai"]["model"] == "fake-llm"


# --- downloads (no network: an in-memory opener) ----------------------------------------------


class _Response(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_download_api_reports_progress_and_completes(api, monkeypatch):
    from interview_assistant.providers.weights import WHISPER, WeightFile, WeightSet

    blobs = {"config.json": b"{}", "model.bin": b"x" * 3000}
    import hashlib

    tiny = WeightSet(
        "faster-whisper/small",
        "Systran/faster-whisper-small",
        "rev",
        (
            WeightFile("config.json", 2),
            WeightFile("model.bin", 3000, hashlib.sha256(blobs["model.bin"]).hexdigest()),
        ),
    )
    monkeypatch.setitem(WHISPER, "small", tiny)
    requested = []

    def opener(request):
        requested.append(request.full_url)
        return _Response(blobs[request.full_url.rsplit("/", 1)[1]])

    api.runtime.models.downloads.opener = opener
    listed = {d["model"]: d for d in api.get("/api/admin/models/downloads").json()}
    assert {"small", "medium", "large-v3", "large-v3-turbo"} <= set(listed)
    assert listed["small"]["status"] == "missing"

    started = api.post(
        "/api/admin/models/downloads", json={"impl": "faster_whisper", "model": "small"}
    )
    assert started.status_code == 202
    api.runtime.models.downloads.wait(tiny, 5)
    done = next(d for d in api.get("/api/admin/models/downloads").json() if d["model"] == "small")
    assert done["status"] == "done" and done["downloaded_bytes"] == 3002
    assert requested[0].startswith(
        "https://huggingface.co/Systran/faster-whisper-small/resolve/rev/"
    )
    [row] = _audits(api, "model.download_started")
    assert row.details["model"] == "small" and row.details["revision"] == "rev"
    check = api.post(
        "/api/admin/models/stt.batch/check",
        json={"impl": "faster_whisper", "options": {"model": "small"}},
    )
    assert check.json()["ready"] is True
    assert (
        api.post(
            "/api/admin/models/downloads", json={"impl": "faster_whisper", "model": "nope"}
        ).status_code
        == 404
    )


@pytest.mark.parametrize("role", ["stt.streaming", "stt.batch"])
def test_whisper_needs_downloaded_weights_to_be_applied(api, role):
    response = api.post(
        f"/api/admin/models/{role}/apply",
        json={"impl": "faster_whisper", "options": {"model": "medium"}, "reason": "로컬 STT"},
    )
    assert response.status_code == 409
    assert "모델 파일 medium" in response.json()["detail"]
