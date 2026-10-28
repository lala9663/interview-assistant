"""관리자 > 모델 설정: pick, test and switch the AI provider of each role without a restart.

Admins only (403 otherwise). Credentials are never sent or shown here: requirements report only
whether a package, an environment variable or a credentials file exists. Tests run only when the
admin asks, and a provider that sends data out of the company (an outside API, Google Cloud)
needs `confirm_external` to be tested or applied (plus a reason to apply). Every test, change, rollback
and download is in the audit log; changes also in the model history (`ai_model_changes`).

서류 읽기 roles (OCR engine, readers, converter, reading mode) are tested by reading a document:
a built-in fictional resume or the admin's file (10 MB, deleted when the test ends). The answer
holds how each page was read and a de-identified preview, never the raw text.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Form, Query, UploadFile
from pydantic import ValidationError
from sqlalchemy.orm import Session

from interview_assistant.ai_models import probe, store
from interview_assistant.ai_models.manager import ChangeRefused, Prepared
from interview_assistant.api import schemas as s
from interview_assistant.api.deps import Admin, Db, RuntimeDep, audit
from interview_assistant.api.errors import conflict, invalid, not_found
from interview_assistant.deid.types import KnownIdentity
from interview_assistant.documents.reading import MODE_LABELS
from interview_assistant.models import AiModelChange, Interviewer, ModelChangeKind
from interview_assistant.providers import catalog
from interview_assistant.providers.audio import (
    SAMPLE,
    SAMPLE_TEXT,
    AudioDecodeError,
    decode_pcm16,
    pcm_seconds,
)
from interview_assistant.providers.catalog import ROLE_BY_KEY, ROLES, ImplInfo
from interview_assistant.providers.weights import WeightSet, is_complete
from interview_assistant.runtime import Runtime

router = APIRouter(prefix="/admin/models", tags=["admin"])

MAX_TEST_AUDIO_BYTES = 10 * 1024 * 1024
MAX_TEST_DOCUMENT_BYTES = 10 * 1024 * 1024
MAX_TEST_AUDIO_SECONDS = 60
AUDIO_SUFFIXES = {".wav", ".webm", ".ogg", ".oga", ".mp3", ".m4a", ".mp4", ".flac", ".aac"}


# --- views ------------------------------------------------------------------------------------


def _info(kind: str, impl: str) -> ImplInfo:
    return catalog.impl_info(kind, impl) or catalog.bare(kind, impl)


def _spec_label(kind: str, spec: dict | None) -> str | None:
    if spec is None:
        return None
    info = _info(kind, spec["impl"])
    options = spec.get("options") or {}
    model = options.get("model") or MODE_LABELS.get(str(options.get("mode")))  # 읽기 방식: its mode
    return f"{info.label} · {model}" if model else info.label


def _requirements(runtime: Runtime, info: ImplInfo, options: dict) -> list[s.ModelRequirement]:
    reqs = catalog.requirements(info, options, weights_dir=runtime.settings.weights_dir)
    return [s.ModelRequirement(**r.__dict__) for r in reqs]


def change_view(db: Session, row: AiModelChange) -> s.ModelChange:
    role = ROLE_BY_KEY.get(row.role)
    kind = role.kind if role else row.role
    actor = db.get(Interviewer, row.actor_id) if row.actor_id else None
    return s.ModelChange(
        id=row.id,
        revision=row.revision,
        occurred_at=row.occurred_at,
        role=row.role,
        role_label=role.label if role else row.role,
        kind=row.kind.value,
        actor=s.ModelActor.model_validate(actor) if actor else None,
        previous=s.ModelSpec(**row.previous) if row.previous else None,
        new=s.ModelSpec(**row.new),
        previous_label=_spec_label(kind, row.previous),
        new_label=_spec_label(kind, row.new) or "",
        reason=row.reason,
        reverts_change_id=row.reverts_change_id,
        details=row.details,
    )


def role_state(db: Session, runtime: Runtime, role_key: str) -> s.ModelRoleState:
    role = ROLE_BY_KEY[role_key]
    active = runtime.models.active
    spec = active.specs.get(role_key)
    provider = active.get(role_key)
    if spec is None:
        info = catalog.bare(role.kind, "-")
        options: dict = {}
        reqs: list[s.ModelRequirement] = []
    else:
        info = _info(role.kind, spec.impl)
        options = spec.options
        reqs = _requirements(runtime, info, options)
    error = active.errors.get(role_key)
    unmet = [r.label for r in reqs if not r.ok]
    detail = (f"요구 조건 미충족: {', '.join(unmet)}" if unmet else None) or error
    pinned = 0
    for revision, count in runtime.models.live_revisions().items():
        if revision != active.revision:
            old = runtime.models.for_revision(revision).specs.get(role_key)
            if not store.same(old, spec):
                pinned += count
    last = store.history(db, role=role_key, limit=1)
    return s.ModelRoleState(
        role=role.key,
        label=role.label,
        description=role.description,
        kind=role.kind,
        group=role.group,
        spec=s.ModelSpec(impl=spec.impl if spec else "-", options=options),
        impl_label=info.label,
        model=str(getattr(provider, "model", "") or (spec.impl if spec else "")),
        data_location=info.data_location.value,
        status="unavailable" if detail else "ready",
        status_detail=detail,
        requirements=reqs,
        note=info.role_notes.get(role_key),
        last_change=change_view(db, last[0]) if last else None,
        pinned_sessions=pinned,
    )


def impl_view(runtime: Runtime, info: ImplInfo) -> s.ModelImpl:
    weights_dir = runtime.settings.weights_dir
    fields = []
    for f in info.options:
        choices = [
            s.ModelOptionChoice(
                value=c.value,
                label=c.label,
                note=c.note,
                size_bytes=c.size_bytes,
                recommended_for=list(c.recommended_for),
                downloaded=(
                    is_complete(info.weights[c.value], weights_dir)
                    if f.key == "model" and c.value in info.weights
                    else None
                ),
            )
            for c in f.choices
        ]
        fields.append(
            s.ModelOptionField(
                key=f.key,
                label=f.label,
                type=f.type,
                default=f.default,
                help=f.help,
                minimum=f.minimum,
                maximum=f.maximum,
                max_length=f.max_length,
                choices=choices,
                roles=list(f.roles),
                fixed=f.fixed,
            )
        )
    reqs = [r for r in _requirements(runtime, info, {}) if not r.key.startswith("weights:")]
    return s.ModelImpl(
        kind=info.kind,
        impl=info.impl,
        label=info.label,
        description=info.description,
        data_location=info.data_location.value,
        data_note=info.data_note,
        license=info.license,
        roles=list(info.roles),
        options=fields,
        role_defaults={k: dict(v) for k, v in info.role_defaults.items()},
        role_notes=dict(info.role_notes),
        requirements=reqs,
    )


def _check_view(runtime: Runtime, prepared: Prepared) -> s.ModelCheck:
    reqs = [s.ModelRequirement(**r.__dict__) for r in prepared.requirements]
    return s.ModelCheck(
        role=prepared.role.key,
        spec=s.ModelSpec(impl=prepared.spec.impl, options=prepared.spec.options),
        data_location=prepared.info.data_location.value,
        external=prepared.external,
        requirements=reqs,
        ready=not prepared.unmet,
        same_as_active=store.same(
            runtime.models.active.specs.get(prepared.role.key), prepared.spec
        ),
    )


# --- settings, catalog, checks ----------------------------------------------------------------


@router.get("", response_model=s.ModelSettings)
def model_settings(db: Db, admin: Admin, runtime: RuntimeDep) -> s.ModelSettings:
    return s.ModelSettings(
        revision=runtime.models.active.revision,
        persistent=runtime.models.persistent,
        roles=[role_state(db, runtime, r.key) for r in ROLES],
    )


@router.get("/catalog", response_model=list[s.ModelImpl])
def model_catalog(admin: Admin, runtime: RuntimeDep) -> list[s.ModelImpl]:
    return [impl_view(runtime, info) for info in catalog.all_impls()]


@router.post("/{role}/check", response_model=s.ModelCheck)
def check_model(
    role: str, body: s.ModelSpecRequest, admin: Admin, runtime: RuntimeDep
) -> s.ModelCheck:
    """Validate options and report requirements. Never contacts the provider."""
    return _check_view(runtime, runtime.models.prepare(role, body.impl, body.options))


# --- connection test --------------------------------------------------------------------------


async def _test_audio(upload: UploadFile | None, folder: Path) -> tuple[Path, str | None, str]:
    if upload is None:
        return SAMPLE, SAMPLE_TEXT, "sample"
    data = await upload.read(MAX_TEST_AUDIO_BYTES + 1)
    if len(data) > MAX_TEST_AUDIO_BYTES:
        raise invalid("audio", "음성 파일이 너무 큽니다 (최대 10MB).")
    if not data:
        raise invalid("audio", "빈 음성 파일입니다.")
    suffix = Path(upload.filename or "").suffix.lower()
    if suffix not in AUDIO_SUFFIXES:
        suffix = ".webm" if "webm" in (upload.content_type or "") else ".wav"
    path = folder / f"test-audio{suffix}"
    path.write_bytes(data)
    try:
        seconds = pcm_seconds(decode_pcm16(path))
    except AudioDecodeError as exc:
        raise invalid("audio", str(exc)) from exc
    if seconds > MAX_TEST_AUDIO_SECONDS:
        raise invalid("audio", f"음성은 {MAX_TEST_AUDIO_SECONDS}초 이하로 올려 주세요.")
    if seconds < 0.5:
        raise invalid("audio", "음성이 너무 짧습니다.")
    return path, None, "upload"


async def _test_document(upload: UploadFile | None, name: str, role: str) -> tuple[probe.DocumentSample, str]:
    if upload is None:
        return probe.document_sample(role), "sample"
    data = await upload.read(MAX_TEST_DOCUMENT_BYTES + 1)
    if len(data) > MAX_TEST_DOCUMENT_BYTES:
        raise invalid("document", "파일이 너무 큽니다 (최대 10MB).")
    if not data:
        raise invalid("document", "빈 파일입니다.")
    # Only the name typed on the screen is known: without it, names without a title may stay.
    identity = KnownIdentity(name=name.strip() or None)
    return probe.DocumentSample(data, upload.filename or "upload", identity, None), "upload"


@router.post("/{role}/test", response_model=s.ModelTestResult)
async def test_model(
    role: str,
    db: Db,
    admin: Admin,
    runtime: RuntimeDep,
    spec: str = Form(...),
    confirm_external: bool = Form(False),
    audio: UploadFile | None = File(None),
    document: UploadFile | None = File(None),
    name: str = Form(""),
) -> s.ModelTestResult:
    """Run the role's connection test on a spec (applied or not). `spec` is the JSON of
    {impl, options}. STT and diarization take `audio` (a recording or file, at most 60 s), or the
    built-in Korean sample without it. 서류 읽기 roles take `document` (10 MB) and optionally the
    applicant's `name` for the preview's de-identification, or a built-in fictional resume. Files
    are deleted when the test ends."""
    try:
        body = s.ModelSpecRequest.model_validate(json.loads(spec))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise invalid("spec", "모델 설정(JSON)을 읽을 수 없습니다.") from exc
    prepared = runtime.models.prepare(role, body.impl, body.options)
    if prepared.external and not confirm_external:
        raise conflict("회사 밖으로 데이터를 보내는 provider입니다. 경고를 확인한 뒤 테스트하세요.")
    if prepared.role.group == "documents":
        return await _test_reading(db, admin, runtime, prepared, document, name)
    kind = prepared.role.kind
    with tempfile.TemporaryDirectory(prefix="ia-model-test-") as tmp:
        path, expected, source = SAMPLE, SAMPLE_TEXT, "sample"
        if kind in ("stt", "diarization", "vad", "turn"):
            path, expected, source = await _test_audio(audio, Path(tmp))
        try:
            provider = await runtime.models.provider_for(prepared)
        except ChangeRefused as exc:
            if exc.status != 502:
                raise
            cause = exc.__cause__
            if getattr(cause, "kind", None):  # e.g. the model server is unreachable at warm-up
                result = probe.failed(prepared.spec.impl, 0, cause)
            else:
                result = probe.ProbeResult(
                    False, prepared.spec.impl, 0, "모델을 불러오지 못했습니다.", error=exc.message
                )
        else:
            result = await probe.run(prepared, provider, db, audio=path, expected_text=expected)
    audio_source = source if kind in ("stt", "diarization", "vad", "turn") else None
    audit(
        db,
        admin,
        "model.tested",
        "ai_model",
        role,
        impl=prepared.spec.impl,
        model=result.model,
        audio=audio_source,
        data_location=prepared.info.data_location.value,
        **probe.summary_for_audit(result),
    )
    db.commit()
    return s.ModelTestResult(
        ok=result.ok,
        model=result.model,
        latency_ms=result.latency_ms,
        summary=result.summary,
        output=result.output,
        error=result.error,
        audio=audio_source,
    )


async def _test_reading(
    db: Db,
    admin: Interviewer,
    runtime: Runtime,
    prepared: Prepared,
    upload: UploadFile | None,
    name: str,
) -> s.ModelTestResult:
    sample, source = await _test_document(upload, name, prepared.role.key)
    try:
        provider = await runtime.models.provider_for(prepared)
    except ChangeRefused as exc:
        if exc.status != 502:
            raise
        result = probe.ProbeResult(
            False, prepared.spec.impl, 0, "도구를 불러오지 못했습니다.", error=exc.message
        )
    else:
        active = dict(runtime.models.active.by_role)
        result = await asyncio.to_thread(
            probe.read_document, prepared, provider, active, sample, runtime.deid.config
        )
    audit(
        db,
        admin,
        "model.tested",
        "ai_model",
        prepared.role.key,
        impl=prepared.spec.impl,
        model=result.model,
        document=source,
        data_location=prepared.info.data_location.value,
        **probe.summary_for_audit(result),
    )
    db.commit()
    return s.ModelTestResult(
        ok=result.ok,
        model=result.model,
        latency_ms=result.latency_ms,
        summary=result.summary,
        output=result.output,
        error=result.error,
        audio=None,
        document=source,
    )


# --- apply, history, rollback -----------------------------------------------------------------


def _audit_change(admin: Interviewer, action: str, prepared: Prepared):
    def write(db: Session, change: AiModelChange) -> None:
        audit(
            db,
            admin,
            action,
            "ai_model",
            change.role,
            revision=change.revision,
            impl=prepared.spec.impl,
            model=(change.details or {}).get("model"),
            previous_impl=(change.previous or {}).get("impl"),
            data_location=prepared.info.data_location.value,
            confirmed_external=bool((change.details or {}).get("confirmed_external")),
        )

    return write


@router.post("/{role}/apply", response_model=s.ModelRoleState)
async def apply_model(
    role: str, body: s.ApplyModelRequest, db: Db, admin: Admin, runtime: RuntimeDep
) -> s.ModelRoleState:
    """Build, warm up and swap in the provider for new work. Sessions in progress keep theirs."""
    prepared = runtime.models.prepare(role, body.impl, body.options)
    await runtime.models.change(
        prepared,
        kind=ModelChangeKind.apply,
        actor_id=admin.id,
        reason=body.reason,
        confirm_external=body.confirm_external,
        also=_audit_change(admin, "model.applied", prepared),
    )
    return role_state(db, runtime, role)


@router.get("/history", response_model=list[s.ModelChange])
def model_history(
    db: Db,
    admin: Admin,
    role: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
) -> list[s.ModelChange]:
    if role is not None and role not in ROLE_BY_KEY:
        raise invalid("role", "알 수 없는 역할입니다.")
    return [change_view(db, row) for row in store.history(db, role=role, limit=limit)]


@router.post("/history/{change_id}/revert", response_model=s.ModelRoleState)
async def revert_model(
    change_id: str, body: s.RevertModelRequest, db: Db, admin: Admin, runtime: RuntimeDep
) -> s.ModelRoleState:
    """Put the role back to what it was before `change_id` (recorded as a new rollback change)."""
    change = db.get(AiModelChange, change_id)
    if change is None:
        raise not_found("변경 이력")
    if change.previous is None:
        raise conflict("처음 설정이라 되돌릴 이전 설정이 없습니다.")
    target = store.spec_from(change.previous)
    prepared = runtime.models.prepare(change.role, target.impl, target.options, stored=True)
    await runtime.models.change(
        prepared,
        kind=ModelChangeKind.rollback,
        actor_id=admin.id,
        reason=body.reason,
        confirm_external=body.confirm_external,
        reverts_change_id=change.id,
        also=_audit_change(admin, "model.reverted", prepared),
    )
    return role_state(db, runtime, change.role)


# --- weights downloads ------------------------------------------------------------------------


def _weights(impl: str, model: str) -> WeightSet:
    for info in catalog.all_impls():
        if info.impl == impl and model in info.weights:
            return info.weights[model]
    raise not_found("모델 파일")


def _download_view(runtime: Runtime, impl: str, model: str, weights: WeightSet) -> s.ModelDownload:
    state = runtime.models.downloads.state(weights)
    return s.ModelDownload(
        impl=impl,
        model=model,
        status=state.status,
        total_bytes=state.total_bytes,
        downloaded_bytes=state.downloaded_bytes,
        error=state.error,
    )


@router.get("/downloads", response_model=list[s.ModelDownload])
def model_downloads(admin: Admin, runtime: RuntimeDep) -> list[s.ModelDownload]:
    return [
        _download_view(runtime, info.impl, model, weights)
        for info in catalog.all_impls()
        for model, weights in info.weights.items()
    ]


@router.post("/downloads", response_model=s.ModelDownload, status_code=202)
def start_download(
    body: s.DownloadRequest, db: Db, admin: Admin, runtime: RuntimeDep
) -> s.ModelDownload:
    """Fetch the weights from Hugging Face in the background (pinned revision, sha256 checked).
    Poll GET /downloads for progress."""
    weights = _weights(body.impl, body.model)
    before = runtime.models.downloads.state(weights)
    if before.status not in ("done", "downloading"):
        runtime.models.downloads.start(weights)
        audit(
            db,
            admin,
            "model.download_started",
            "ai_model",
            body.impl,
            model=body.model,
            repo_id=weights.repo_id,
            revision=weights.revision,
            bytes=weights.size_bytes,
        )
        db.commit()
    return _download_view(runtime, body.impl, body.model, weights)


@router.delete("/downloads/{impl}/{model}", response_model=s.ModelDownload)
def cancel_download(
    impl: str, model: str, db: Db, admin: Admin, runtime: RuntimeDep
) -> s.ModelDownload:
    weights = _weights(impl, model)
    if runtime.models.downloads.state(weights).status == "downloading":
        runtime.models.downloads.cancel(weights)
        audit(db, admin, "model.download_cancelled", "ai_model", impl, model=model)
        db.commit()
    return _download_view(runtime, impl, model, weights)
