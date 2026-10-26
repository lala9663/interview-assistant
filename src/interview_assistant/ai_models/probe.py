"""Connection tests on the admin screen: does a provider answer, how fast, and what.

A test runs only when an admin presses the button; providers that send data beyond this PC and
the company GCP also need the admin's confirmation (api/routes/admin.py). The LLM test sends a
fixed, made-up prompt through the AI gateway (guard + audit) and checks the structured answer. STT
transcribes a voice sample, the built-in clip or the admin's own recording, through the role's own
path: batch `transcribe` on a file, streaming `stream` on 16 kHz PCM chunks. Embedding checks the
vector dimension, diarization the speaker turns. 서류 읽기 roles read a built-in fictional resume
or the admin's file with the candidate setting (`read_document`) and show how each page was read
and a de-identified preview; the raw text never leaves the server. Nothing a test sends or
returns is stored; the audit log keeps who tested what, the model, the outcome and the timings.
"""

from __future__ import annotations

import json
import math
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from interview_assistant.ai.gateway import AiCall, AiGateway, model_name
from interview_assistant.ai.prompts import (
    CONNECTION_TEST_ECHO,
    CONNECTION_TEST_PROMPT,
    CONNECTION_TEST_SCHEMA,
    CONNECTION_TEST_SYSTEM,
    connection_test_prompt,
)
from interview_assistant.ai_models.manager import Prepared, describe
from interview_assistant.deid.config import DeidConfig
from interview_assistant.deid.types import KnownIdentity
from interview_assistant.providers.audio import decode_pcm16, pcm_chunks, pcm_seconds
from interview_assistant.providers.base import ProviderUnavailable
from interview_assistant.textmetrics import cer

EMBED_TEXTS = ("연결 테스트 문장입니다.", "모델 설정 화면에서 보낸 두 번째 문장")


@dataclass
class ProbeResult:
    ok: bool
    model: str
    latency_ms: int
    summary: str
    output: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


async def run(
    prepared: Prepared,
    provider: Any,
    db: Session,
    *,
    audio: Path,
    expected_text: str | None = None,
) -> ProbeResult:
    """Test `provider` in `prepared.role`. `audio` is the voice sample for STT and diarization;
    `expected_text` is its transcript when known (the built-in sample)."""
    model = model_name(provider)
    started = time.perf_counter()
    try:
        kind = prepared.role.kind
        if kind == "llm":
            ok, summary, output = await _llm(prepared, provider, db)
        elif kind == "stt":
            ok, summary, output = await _stt(prepared, provider, audio, expected_text, started)
        elif kind == "embedding":
            ok, summary, output = await _embedding(provider)
        else:
            ok, summary, output = await _diarization(provider, audio)
    except Exception as exc:
        elapsed = round((time.perf_counter() - started) * 1000)
        return ProbeResult(False, model, elapsed, "테스트가 실패했습니다.", error=describe(exc))
    elapsed = round((time.perf_counter() - started) * 1000)
    return ProbeResult(ok, model, elapsed, summary, output)


async def _llm(prepared: Prepared, provider: Any, db: Session) -> tuple[bool, str, dict[str, Any]]:
    slot = prepared.role.key.split(".", 1)[1]
    gateway = AiGateway({slot: provider, "primary": provider})
    result = await gateway.generate(
        db,
        AiCall(
            action="model.connection_test",
            prompt_version=CONNECTION_TEST_PROMPT,
            system=CONNECTION_TEST_SYSTEM,
            prompt=connection_test_prompt(),
            role=slot,
            schema=CONNECTION_TEST_SCHEMA,
            max_tokens=200,
            target_type="ai_model",
            target_id=prepared.role.key,
        ),
    )
    structured = result.structured or {}
    echo_ok = CONNECTION_TEST_ECHO in str(structured.get("echo") or "")
    sum_ok = structured.get("sum") == 42
    output = {
        "structured": structured,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
    }
    if echo_ok and sum_ok:
        return True, "구조화 출력(JSON)으로 지시대로 답했습니다.", output
    missing = [
        name for name, ok in (("문장 그대로 옮기기", echo_ok), ("두 수 더하기", sum_ok)) if not ok
    ]
    return False, f"응답은 왔지만 형식이나 내용이 맞지 않습니다: {', '.join(missing)}", output


async def _stt(
    prepared: Prepared,
    provider: Any,
    audio: Path,
    expected_text: str | None,
    started: float,
) -> tuple[bool, str, dict[str, Any]]:
    pcm = decode_pcm16(audio)
    seconds = pcm_seconds(pcm)
    output: dict[str, Any] = {"audio_seconds": round(seconds, 2)}
    if prepared.role.key == "stt.streaming":
        finals: list[str] = []
        partials = 0
        first_ms: int | None = None
        async for segment in provider.stream(pcm_chunks(pcm)):
            if first_ms is None:
                first_ms = round((time.perf_counter() - started) * 1000)
            if segment.is_final:
                finals.append(segment.text)
            else:
                partials += 1
        text = " ".join(t for t in finals if t)
        output |= {"partials": partials, "finals": len(finals), "first_result_ms": first_ms}
    else:
        segments = await provider.transcribe(audio.resolve().as_uri())
        text = " ".join(s.text for s in segments if s.text)
        output["segments"] = len(segments)
    elapsed = time.perf_counter() - started
    output["text"] = text
    output["realtime_factor"] = round(elapsed / seconds, 3) if seconds else None
    if expected_text:
        output["expected_text"] = expected_text
        output["cer"] = round(cer(expected_text, text), 4)
    if not text.strip():
        return False, f"{seconds:.1f}초 음성에서 아무것도 받아 적지 못했습니다.", output
    speed = f", 실시간 대비 {output['realtime_factor']:.2f}배 시간" if seconds else ""
    return True, f"{seconds:.1f}초 음성을 전사했습니다{speed}.", output


async def _embedding(provider: Any) -> tuple[bool, str, dict[str, Any]]:
    vectors = await provider.embed(list(EMBED_TEXTS))
    dims = sorted({len(v) for v in vectors})
    expected = getattr(provider, "dimensions", None) or None
    finite = all(math.isfinite(x) for v in vectors for x in v)
    output = {"vectors": len(vectors), "dimensions": dims[0] if len(dims) == 1 else dims}
    output["expected_dimensions"] = expected
    if len(vectors) != len(EMBED_TEXTS) or len(dims) != 1 or not finite:
        return False, "벡터 개수나 차원이 맞지 않습니다.", output
    if expected is not None and dims[0] != expected:
        return False, f"차원이 설정({expected})과 다릅니다: {dims[0]}", output
    return True, f"{dims[0]}차원 벡터 {len(vectors)}개를 받았습니다.", output


async def _diarization(provider: Any, audio: Path) -> tuple[bool, str, dict[str, Any]]:
    turns = await provider.diarize(audio.resolve().as_uri())
    speakers = sorted({t.speaker for t in turns})
    output = {"turns": len(turns), "speakers": speakers}
    if not turns:
        return False, "화자 구간을 하나도 받지 못했습니다.", output
    return True, f"화자 {len(speakers)}명, 구간 {len(turns)}개를 받았습니다.", output


SAMPLES = Path(__file__).resolve().parents[1] / "providers" / "samples" / "documents"
PREVIEW_CHARS = 2000


@dataclass(frozen=True)
class DocumentSample:
    data: bytes
    filename: str
    identity: KnownIdentity
    ocr_truth: str | None


def document_sample(role: str) -> DocumentSample:
    """The built-in fictional resume for a 서류 읽기 role (providers/samples/NOTICE.md)."""
    index = json.loads((SAMPLES / "samples.json").read_text(encoding="utf-8"))
    entry = index.get(role) or index["document.reading"]
    return DocumentSample(
        (SAMPLES / entry["file"]).read_bytes(),
        entry["file"],
        KnownIdentity.from_dict(entry["identity"]),
        entry.get("ocr_truth"),
    )


def read_document(
    prepared: Prepared,
    provider: Any,
    active: Mapping[str, Any],
    sample: DocumentSample,
    deid_config: DeidConfig,
) -> ProbeResult:
    """Read `sample` with `provider` in its role and the active settings for the other 서류 읽기
    roles, then de-identify it on a throwaway store (nothing is saved). Runs in a worker thread.
    The result holds how each page was read and a de-identified preview, never the raw text."""
    from interview_assistant.ai_models.manager import reader_for
    from interview_assistant.deid.documents import deidentify_document
    from interview_assistant.deid.leaks import real_path, residual_scan
    from interview_assistant.documents.base import ExtractionError

    started = time.perf_counter()
    by_role = {**active, prepared.role.key: provider}
    model = str(getattr(provider, "model", "") or prepared.spec.impl)
    try:
        document = reader_for(by_role, None).read(sample.data, sample.filename)
    except (ExtractionError, ProviderUnavailable) as exc:
        elapsed = round((time.perf_counter() - started) * 1000)
        return ProbeResult(False, model, elapsed, "읽지 못했습니다.", {"format": None}, describe(exc))
    read_ms = round((time.perf_counter() - started) * 1000)
    output: dict[str, Any] = {
        "format": document.format,
        "pages": document.page_summary(),
        "images": [
            {"label": i.label, "decision": i.decision, "confidence": i.confidence, "detail": i.detail}
            for i in document.images
        ],
        "tools": list(document.reading.tools) if document.reading else [],
        "warnings": list(document.warnings),
        "read_ms": read_ms,
    }
    ocr_text = "\n".join(b.text for b in document.blocks if b.ocr)
    if sample.ocr_truth and ocr_text:
        output["cer"] = round(cer(sample.ocr_truth, ocr_text), 4)
    held = [p for p in document.pages if p.needs_ocr]
    if held:
        reasons = "; ".join(f"{p.number}쪽: {p.reason}" for p in held)
        elapsed = round((time.perf_counter() - started) * 1000)
        if all("텍스트만" in p.reason for p in held):
            # The setting works as intended: such documents are held, not read. Testable, appliable.
            pages = ", ".join(str(p.number) for p in held)
            summary = f"텍스트만 설정이라 {pages}쪽은 OCR하지 않고 보류합니다. 적용하면 이런 서류는 처리 보류됩니다."
            return ProbeResult(True, model, elapsed, summary, output)
        return ProbeResult(False, model, elapsed, f"읽지 못한 쪽이 있어 보류됩니다 ({reasons}).", output)
    with real_path(deid_config) as (deid, enroll):
        candidate_id, known = enroll("MODEL-TEST", sample.identity)
        result = deidentify_document(deid, document, candidate_id=candidate_id, known=known)
    preview = result.text
    for _, surface in residual_scan(preview):  # belt and braces: no contact shape is shown
        preview = preview.replace(surface, "■" * len(surface))
    output["preview"] = preview[:PREVIEW_CHARS]
    output["preview_truncated"] = len(preview) > PREVIEW_CHARS
    output["replacements"] = result.replacements
    ocr_pages = sum(1 for p in document.pages if p.method.value == "ocr")
    pictures = sum(1 for i in document.images if i.decision == "ocr")
    elapsed = round((time.perf_counter() - started) * 1000)
    summary = f"{document.format.upper()} {len(document.pages)}쪽을 읽었습니다" + (
        f" (OCR {ocr_pages}쪽" + (f", 그림 {pictures}개" if pictures else "") + ")" if ocr_pages or pictures else ""
    )
    return ProbeResult(True, model, elapsed, summary + ".", output)


def summary_for_audit(result: ProbeResult) -> dict[str, Any]:
    """What the audit log keeps of a test: outcome and timings, never text."""
    keep = ("audio_seconds", "realtime_factor", "cer", "dimensions", "turns", "partials", "format", "read_ms")
    details = {k: result.output[k] for k in keep if k in result.output}
    details |= {"ok": result.ok, "latency_ms": result.latency_ms}
    if result.error:
        details["error"] = re.sub(r"\s+", " ", result.error)[:200]
    return details
