"""Connection tests on the admin screen: does a provider answer, how fast, and what.

A test runs only when an admin presses the button; providers that send data out of the company
also need the admin's confirmation (api/routes/admin.py). The LLM test sends a
fixed, made-up prompt through the AI gateway (guard + audit) and checks the structured answer. STT
transcribes a voice sample, the built-in clip or the admin's own recording, through the role's own
path: batch `transcribe` on a file, streaming `stream` on 16 kHz PCM chunks. Embedding checks the
vector dimension, diarization the speaker turns. 음성 입력 roles run the voice sample through the
microphone path offline: the VAD's speech stretches, or where the end-of-answer detector would
close the answer (with 3 s of silence after the sample), or for noise suppression the delay, the
time per second of audio and how much quieter speech and the rest came out. 서류 읽기 roles read a built-in fictional resume
or the admin's file with the candidate setting (`read_document`) and show how each page was read
and a de-identified preview; the raw text never leaves the server. Nothing a test sends or
returns is stored; the audit log keeps who tested what, the model, the outcome and the timings.
"""

from __future__ import annotations

import asyncio
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
    CONNECTION_STREAM_SYSTEM,
    CONNECTION_TEST_ECHO,
    CONNECTION_TEST_PROMPT,
    CONNECTION_TEST_SCHEMA,
    CONNECTION_TEST_SYSTEM,
    connection_stream_prompt,
    connection_test_prompt,
)
from interview_assistant.ai_models.manager import Prepared, describe
from interview_assistant.deid.config import DeidConfig
from interview_assistant.deid.types import KnownIdentity
from interview_assistant.providers.audio import decode_pcm16, pcm_chunks, pcm_seconds
from interview_assistant.providers.base import ProviderUnavailable
from interview_assistant.textmetrics import cer

# A sentence, a paraphrase sharing an abbreviation, and an unrelated sentence (made up).
EMBED_TEXTS = (
    "식각 공정에서 웨이퍼 가장자리 CD 산포가 커진 원인을 FDC 데이터로 찾았습니다.",
    "FDC 데이터를 보고 에지 쪽 선폭 편차가 왜 생겼는지 분석했습니다.",
    "점심 메뉴로 김치찌개와 계란말이를 골랐습니다.",
)


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
        elif kind in ("vad", "turn", "denoise"):
            ok, summary, output = await _audio_input(kind, provider, audio)
        else:
            ok, summary, output = await _diarization(provider, audio)
    except Exception as exc:
        return failed(model, round((time.perf_counter() - started) * 1000), exc)
    elapsed = round((time.perf_counter() - started) * 1000)
    return ProbeResult(ok, model, elapsed, summary, output)


def failed(model: str, elapsed_ms: int, exc: BaseException, summary: str = "테스트가 실패했습니다.") -> ProbeResult:
    """A test that raised. Providers that tell the cause apart (`kind`, `label`: the model
    server's address, authentication, model name, timeout) name it in the summary."""
    kind = getattr(exc, "kind", None)
    label = getattr(exc, "label", None)
    if kind and label:
        return ProbeResult(False, model, elapsed_ms, f"테스트 실패: {label}", {"failure": kind}, describe(exc))
    return ProbeResult(False, model, elapsed_ms, summary, error=describe(exc))


def _ms(since: float) -> int:
    return round((time.perf_counter() - since) * 1000)


async def _llm(prepared: Prepared, provider: Any, db: Session) -> tuple[bool, str, dict[str, Any]]:
    """Structured output through the gateway, then a short stream (as follow-ups use it): the
    response time, the time to the first token and the model name the server reports."""
    slot = prepared.role.key.split(".", 1)[1]
    gateway = AiGateway({slot: provider, "primary": provider})
    started = time.perf_counter()
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
    generate_ms = _ms(started)
    structured = result.structured or {}
    echo_ok = CONNECTION_TEST_ECHO in str(structured.get("echo") or "")
    sum_ok = structured.get("sum") == 42
    output: dict[str, Any] = {
        "structured": structured,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "server_model": result.model,
        "generate_ms": generate_ms,
    }
    served = getattr(provider, "served_models", None)
    if served is not None:
        output["server_models"] = list(served)[:20]

    started = time.perf_counter()
    _, pieces = gateway.stream(
        db,
        AiCall(
            action="model.connection_test",
            prompt_version=CONNECTION_TEST_PROMPT,
            system=CONNECTION_STREAM_SYSTEM,
            prompt=connection_stream_prompt(),
            role=slot,
            max_tokens=100,
            target_type="ai_model",
            target_id=prepared.role.key,
            details={"stream": True},
        ),
    )
    first_ms: int | None = None
    streamed: list[str] = []
    async for piece in pieces:
        if first_ms is None and piece.strip():
            first_ms = _ms(started)
        streamed.append(piece)
    text = "".join(streamed).strip()
    output |= {"first_token_ms": first_ms, "stream_ms": _ms(started), "stream_text": text[:200]}

    timing = f" 응답 {generate_ms / 1000:.1f}초" + (
        f", 스트리밍 첫 토큰 {first_ms / 1000:.1f}초." if first_ms is not None else "."
    )
    problems = [
        name
        for name, ok in (
            ("문장 그대로 옮기기", echo_ok),
            ("두 수 더하기", sum_ok),
            ("스트리밍", bool(text)),
        )
        if not ok
    ]
    if not problems:
        return True, "구조화 출력(JSON)과 스트리밍으로 지시대로 답했습니다." + timing, output
    return False, f"응답은 왔지만 형식이나 내용이 맞지 않습니다: {', '.join(problems)}." + timing, output


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


async def _audio_input(kind: str, provider: Any, audio: Path) -> tuple[bool, str, dict[str, Any]]:
    import numpy as np

    from interview_assistant.live.microphone import FRAME_MS, speech_flags
    from interview_assistant.providers.vad.silero import SileroVAD

    pcm = decode_pcm16(audio)
    seconds = pcm_seconds(pcm)
    output: dict[str, Any] = {"audio_seconds": round(seconds, 2)}
    if kind == "denoise":
        if not getattr(provider, "enabled", False):
            return True, "잡음 억제를 하지 않습니다 (끔). 브라우저가 보낸 소리가 그대로 VAD와 STT로 갑니다.", output
        await provider.warm_up()
        output |= await asyncio.to_thread(_denoise, provider, pcm, seconds)
        if not output["same_length"]:
            return False, "처리한 음성의 길이가 입력과 다릅니다.", output
        levels = (
            f" 소리 크기: 말소리 구간 {output['speech_change_db']:+.1f}dB, 그 밖 {output['other_change_db']:+.1f}dB."
            if output.get("speech_change_db") is not None and output.get("other_change_db") is not None
            else ""
        )
        return (
            True,
            f"{seconds:.1f}초 음성을 100ms 조각으로 처리했습니다. 지연 {output['delay_ms']}ms, "
            f"처리 시간 음성 1초당 {output['cpu_ms_per_second']}ms.{levels}",
            output,
        )
    vad = provider if kind == "vad" else SileroVAD()
    await vad.warm_up()
    samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
    if kind == "turn":
        samples = np.concatenate([samples, np.zeros(3 * 16000, dtype=np.float32)])
    flags = speech_flags(vad, samples)
    stretches: list[list[float]] = []
    for i, speech in enumerate(flags):
        at = round(i * FRAME_MS / 1000, 2)
        if speech and (not stretches or i and not flags[i - 1]):
            stretches.append([at, at])
        if speech:
            stretches[-1][1] = round(at + FRAME_MS / 1000, 2)
    output["speech"] = stretches[:30]
    speech_s = float(flags.sum()) * FRAME_MS / 1000
    output["speech_seconds"] = round(speech_s, 2)
    if not stretches:
        return False, f"{seconds:.1f}초 음성에서 말소리를 찾지 못했습니다.", output
    if kind == "vad":
        return True, f"{seconds:.1f}초 중 말소리 {speech_s:.1f}초, 구간 {len(stretches)}개를 찾았습니다.", output
    tracker = provider.tracker(FRAME_MS)
    ends: list[dict[str, Any]] = []
    for i, speech in enumerate(flags):
        if await tracker.push(bool(speech), samples[i * 512 : (i + 1) * 512]):
            ends.append({"at": round((i + 1) * FRAME_MS / 1000, 2), "reason": tracker.reason, "probability": tracker.probability})
            tracker = provider.tracker(FRAME_MS)
    output["ends"] = ends
    last = stretches[-1][1]
    final = next((e for e in ends if e["at"] >= last), None)
    early = [e for e in ends if e["at"] < last]
    if final is None:
        return False, f"마지막 말소리({last:.1f}초) 뒤 3초 안에 답변 끝으로 판정하지 않았습니다.", output
    note = f", 그 전에 {len(early)}번 끊음" if early else ""
    return True, f"마지막 말소리 {last:.1f}초 → {final['at'] - last:.1f}초 뒤 답변 끝 ({final['reason']}){note}.", output


def _denoise(provider: Any, pcm: bytes, seconds: float) -> dict[str, Any]:
    """The sample through a fresh stream in the browser's 100 ms chunks: the delay, the time per
    second of audio, and how much louder or quieter the speech (Silero VAD on the input) and
    everything else came out."""
    import numpy as np

    from interview_assistant.live.microphone import speech_flags
    from interview_assistant.providers.vad.silero import SileroVAD

    stream = provider.stream()
    started = time.perf_counter()
    cleaned = b"".join(stream.process(pcm[i : i + 3200]) for i in range(0, len(pcm), 3200))
    elapsed = time.perf_counter() - started
    output: dict[str, Any] = {
        "same_length": len(cleaned) == len(pcm),
        "delay_ms": round(stream.delay_samples / 16),
        "cpu_ms_per_second": round(elapsed / seconds * 1000) if seconds else None,
    }
    before = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
    after = np.frombuffer(cleaned, dtype="<i2").astype(np.float32)[stream.delay_samples :] / 32768.0
    after = np.concatenate([after, np.zeros(len(before) - len(after), dtype=np.float32)])
    try:
        flags = speech_flags(SileroVAD(), before)
    except ProviderUnavailable:
        return output
    frames = len(flags) * 512
    speech = np.repeat(flags, 512)
    for key, part in (("speech_change_db", speech), ("other_change_db", ~speech)):
        energy = float((before[:frames][part] ** 2).sum())
        output[key] = round(10 * math.log10(float((after[:frames][part] ** 2).sum() + 1e-12) / energy), 1) if energy else None
    return output


async def _embedding(provider: Any) -> tuple[bool, str, dict[str, Any]]:
    """Fixed sentences (no candidate data): the sizes, and whether a paraphrase lands closer than
    an unrelated sentence. With a sparse model, also the lexical score the shared abbreviation
    (FDC) gives."""
    from interview_assistant.retrieval.vectors import cosine, lexical

    encoded = await provider.encode(list(EMBED_TEXTS))
    vectors = [e.dense for e in encoded]
    dims = sorted({len(v) for v in vectors})
    expected = getattr(provider, "dimensions", None) or None
    finite = all(math.isfinite(x) for v in vectors for x in v)
    output: dict[str, Any] = {
        "vectors": len(vectors),
        "dimensions": dims[0] if len(dims) == 1 else dims,
        "expected_dimensions": expected,
        "sparse": all(e.sparse is not None for e in encoded),
    }
    if len(vectors) != len(EMBED_TEXTS) or len(dims) != 1 or not finite:
        return False, "벡터 개수나 차원이 맞지 않습니다.", output
    if expected is not None and dims[0] != expected:
        return False, f"차원이 설정({expected})과 다릅니다: {dims[0]}", output
    base, similar, unrelated = encoded
    output["similar"] = round(cosine(base.dense, similar.dense), 3)
    output["unrelated"] = round(cosine(base.dense, unrelated.dense), 3)
    if output["sparse"]:
        output["lexical"] = round(lexical(base.sparse or {}, similar.sparse or {}), 4)
    summary = (
        f"{dims[0]}차원 벡터 {len(vectors)}개" + (", 단어 일치 가중치 포함" if output["sparse"] else "")
        + f". 비슷한 문장 {output['similar']:.2f}, 무관한 문장 {output['unrelated']:.2f}."
    )
    if output["similar"] <= output["unrelated"]:
        return False, summary + " 비슷한 문장이 더 가깝지 않습니다.", output
    return True, summary, output


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
    keep = (
        "audio_seconds",
        "realtime_factor",
        "cer",
        "dimensions",
        "similar",
        "unrelated",
        "turns",
        "partials",
        "format",
        "read_ms",
        "server_model",
        "generate_ms",
        "first_token_ms",
        "failure",
    )
    details = {k: result.output[k] for k in keep if k in result.output}
    details |= {"ok": result.ok, "latency_ms": result.latency_ms}
    if result.error:
        details["error"] = re.sub(r"\s+", " ", result.error)[:200]
    return details
