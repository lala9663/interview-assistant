"""No response carries a real name, contact detail, raw answer, original file path or recording
path, and no prompt reaches the model with them, whatever goes in through the API."""

import re
import shutil
from typing import ClassVar

import yaml
from fastapi.testclient import TestClient

from interview_assistant.demo import mock_data
from interview_assistant.demo.seed import fake_identity
from interview_assistant.main import create_app
from interview_assistant.providers import registry
from interview_assistant.providers.fake import FakeLLM
from tests.api_util import (
    COMPLETED,
    LIVE,
    SCHEDULED,
    get_paths,
    json_keys,
    sse_events,
    wait_for,
)
from tests.conftest import ROOT, api_settings, file_session_factory
from tests.test_api_flows import P2, _manifest_identity, upload

FORBIDDEN_KEYS = {"answer_text", "encrypted_identity", "source_file_uri", "recording_uri"}
RAW_ZONE_MARKERS = ("uploads", "recordings", ".webm", "file:")


def _seeded_identity(n: int):
    return fake_identity(n, next(c for c in mock_data()["candidates"] if c["n"] == n)["profile"])


def _variants(value: str) -> list[str]:
    digits = re.sub(r"\D", "", value)
    return [value, digits] if len(digits) >= 8 else [value]


def _identifiers() -> list[str]:
    cand7 = _seeded_identity(7)
    cand11 = _seeded_identity(11)
    taeo = _manifest_identity("이력서_문태오.docx")
    values = [cand7.name, *cand7.phones, *cand7.emails, cand11.name, *cand11.phones]
    values.append(_seeded_identity(3).name)
    values += [taeo["name"], *taeo["phones"], *taeo["emails"], *taeo["aliases"]]
    return [v for value in values for v in _variants(value)]


def _assert_clean(body: str, where: str, extra: list[str]) -> None:
    for value in _identifiers() + extra:
        assert value not in body, (where, value)
    for marker in RAW_ZONE_MARKERS:
        assert marker not in body, (where, marker)


def _feed_identifiers(api) -> list[str]:
    """Put identifiers into every free-text input the API has. Returns the raw texts sent."""
    cand7, cand11 = _seeded_identity(7), _seeded_identity(11)
    raw = []
    assert upload(api, "이력서_문태오.docx").status_code == 201

    question = f"{cand7.name}님, 마지막 질문입니다. 연락은 {cand7.phones[0]}로 드리면 될까요?"
    qa = api.post(
        f"/api/sessions/{LIVE}/qa-items",
        json={"question": question, "question_source": "interviewer"},
    ).json()
    answer = f"네, 저 {cand7.name}입니다. {cand7.phones[0]}이나 {cand7.emails[0]}로 연락 주세요. 데이터로 3번 검증했습니다."
    raw += [question, answer]
    assert api.patch(f"/api/qa-items/{qa['id']}", json={"answer_text": answer}).status_code == 200
    note = f"{cand7.name} 지원자 메모: 번호 {cand7.phones[0]}"
    raw.append(note)
    assert api.post(f"/api/sessions/{LIVE}/notes", json={"content": note}).status_code == 201
    follow = api.post(f"/api/sessions/{LIVE}/follow-ups", json={"qa_item_id": qa["id"]})
    assert [e for e, _ in sse_events(follow.text)][-1] == "batch.done"
    _assert_clean(follow.text, "follow-ups", raw)

    api.post(f"/api/sessions/{SCHEDULED}/consent", json={"consent_recording": False})
    api.post(f"/api/sessions/{SCHEDULED}/start")
    manual = api.post(
        f"/api/sessions/{SCHEDULED}/qa-items",
        json={"question": "자기소개 부탁드립니다.", "question_source": "interviewer"},
    ).json()
    answer11 = f"{cand11.name}입니다. 휴대폰은 {cand11.phones[0]}입니다."
    raw.append(answer11)
    api.patch(f"/api/qa-items/{manual['id']}", json={"answer_text": answer11})

    me = api.get("/api/me").json()
    ev = api.get(f"/api/sessions/{COMPLETED}/evaluation").json()
    comment = f"{_seeded_identity(3).name} 지원자의 설명이 구체적"
    raw.append(comment)
    scores = [
        {"competency": c["name"], "score": 4, "comment": comment}
        for c in ev["competency_set"]["competencies"]
    ]
    assert (
        api.put(f"/api/sessions/{COMPLETED}/scores/{me['id']}", json={"scores": scores}).status_code
        == 200
    )

    api.post(f"/api/sessions/{LIVE}/end")
    wait_for(api, f"/api/sessions/{LIVE}/evaluation", lambda b: b["ai"]["status"] == "completed")
    return raw


def test_no_response_carries_identifiers_raw_text_or_raw_zone_paths(api):
    raw = _feed_identifiers(api)
    for path in get_paths(api):
        response = api.get(path)
        assert response.status_code == 200, path
        _assert_clean(response.text, path, raw)
        if not path.endswith("/stream"):
            assert not json_keys(response.json()) & FORBIDDEN_KEYS, path


def test_free_text_is_stored_tokenised_where_the_api_reads_it(api):
    _feed_identifiers(api)
    detail = api.get(f"/api/sessions/{LIVE}").json()
    typed = next(q for q in detail["qa_items"] if q["question_source"] == "interviewer")
    assert typed["question"].startswith("[지원자]님, 마지막 질문입니다.")
    assert "[전화-1]" in typed["question"]
    assert (
        "[지원자]" in typed["answer_deidentified"] and "[이메일-1]" in typed["answer_deidentified"]
    )
    assert detail["notes"][-1]["content"].startswith("[지원자] 지원자 메모")


class SpyLLM(FakeLLM):
    """FakeLLM that records every prompt it is sent."""

    prompts: ClassVar[list[str]] = []

    async def generate(self, system, prompt, **kwargs):
        SpyLLM.prompts.append(prompt)
        return await super().generate(system, prompt, **kwargs)

    async def stream(self, system, prompt, **kwargs):
        SpyLLM.prompts.append(prompt)
        async for piece in super().stream(system, prompt, **kwargs):
            yield piece


def test_providers_come_from_the_yaml_and_only_see_deidentified_text(
    seeded_db, tmp_path, monkeypatch, no_external_network
):
    """Swapping the model is a config change: a provider named only in the YAML gets every call
    (screening, follow-ups, scoring, competency drafts), and no prompt holds an identifier."""
    monkeypatch.setitem(registry._IMPLS["llm"], "spy", f"{__name__}:SpyLLM")
    SpyLLM.prompts = []
    config = yaml.safe_load((ROOT / "config" / "providers.fake.yaml").read_text(encoding="utf-8"))
    config["providers"]["llm"] = {
        "primary": {"impl": "spy", "model": "spy-primary"},
        "screening": {"impl": "spy", "model": "spy-screening"},
    }
    for spec in config["providers"]["stt"].values():
        spec["speed"] = 0
    providers_file = tmp_path / "providers.yaml"
    providers_file.write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")

    template, key = seeded_db
    db_path = tmp_path / "spy.db"
    shutil.copyfile(template, db_path)
    factory = file_session_factory(db_path)
    app = create_app(
        api_settings(db_path, key, tmp_path, providers_file=providers_file), session_factory=factory
    )
    with TestClient(app) as api:
        assert api.get("/health").json()["providers"]["llm"] == {
            "primary": "SpyLLM",
            "screening": "SpyLLM",
        }
        raw = _feed_identifiers(api)
        assert (
            api.post(
                "/api/postings/b1d6a0c2-1f3e-4b8a-9c41-5e2f7a9d0003/competency-sets/generate"
            ).status_code
            == 201
        )
        ev = api.get(f"/api/sessions/{LIVE}/evaluation").json()
        assert ev["ai"]["model"] == "spy-primary"
        upload_result = api.get(f"/api/postings/{P2}/applications").json()[-1]
        assert upload_result["screening"]["model"] == "spy-screening"
    factory.kw["bind"].dispose()

    kinds = {"<document>", "<follow_up_request>", "<answer>", "<job_posting>"}
    assert all(any(k in p for p in SpyLLM.prompts) for k in kinds)
    taeo = _manifest_identity("이력서_문태오.docx")
    org_values = [*taeo["schools"], *taeo["companies"], *_seeded_identity(7).companies]
    for prompt in SpyLLM.prompts:
        _assert_clean(prompt, "prompt", raw + org_values)
