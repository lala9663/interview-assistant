"""Connection tests on the admin screen: does a provider answer, how fast, and what.

A test runs only when an admin presses the button; providers that send data beyond this PC and
the company GCP also need the admin's confirmation (api/routes/admin.py). The LLM test sends a
fixed, made-up prompt through the AI gateway (guard + audit) and checks the structured answer. STT
transcribes a voice sample, the built-in clip or the admin's own recording, through the role's own
path: batch `transcribe` on a file, streaming `stream` on 16 kHz PCM chunks. Embedding checks the
vector dimension, diarization the speaker turns. Nothing a test sends or returns is stored; the
audit log keeps who tested what, the model, the outcome and the timings.
"""

from __future__ import annotations

import math
import re
import time
import unicodedata
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
from interview_assistant.providers.audio import decode_pcm16, pcm_chunks, pcm_seconds

EMBED_TEXTS = ("연결 테스트 문장입니다.", "모델 설정 화면에서 보낸 두 번째 문장")


@dataclass
class ProbeResult:
    ok: bool
    model: str
    latency_ms: int
    summary: str
    output: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


def normalize(text: str) -> str:
    """For error rates: NFC, no spaces or punctuation, lower case."""
    text = unicodedata.normalize("NFC", text).lower()
    return "".join(c for c in text if not (c.isspace() or unicodedata.category(c).startswith("P")))


def cer(reference: str, hypothesis: str) -> float:
    """Character error rate: edit distance over the reference length, both normalized."""
    ref, hyp = normalize(reference), normalize(hypothesis)
    if not ref:
        return 0.0 if not hyp else 1.0
    previous = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        current = [i]
        for j, h in enumerate(hyp, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (r != h)))
        previous = current
    return previous[-1] / len(ref)


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


def summary_for_audit(result: ProbeResult) -> dict[str, Any]:
    """What the audit log keeps of a test: outcome and timings, never text."""
    keep = ("audio_seconds", "realtime_factor", "cer", "dimensions", "turns", "partials")
    details = {k: result.output[k] for k in keep if k in result.output}
    details |= {"ok": result.ok, "latency_ms": result.latency_ms}
    if result.error:
        details["error"] = re.sub(r"\s+", " ", result.error)[:200]
    return details
