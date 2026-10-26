"""Local Whisper (faster-whisper) on the built-in Korean sample, batch and streaming, and switching
the STT through the admin API for real.

Needs `uv sync --extra whisper` and downloaded weights (admin > 모델 설정, or IA_WEIGHTS_DIR);
skipped otherwise. Prefers medium (accurate enough, moderate load time); small gets a looser error
bound, it misses a quarter of the sample's characters (docs/whisper-benchmark.md). No network: the
weights are read locally.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
from pathlib import Path

import pytest

from interview_assistant.ai_models.probe import cer
from interview_assistant.providers.audio import SAMPLE, SAMPLE_TEXT, decode_pcm16, pcm_chunks
from interview_assistant.providers.weights import WHISPER, is_complete

ROOT = Path(__file__).resolve().parents[1]
WEIGHTS = Path(os.environ.get("IA_WEIGHTS_DIR") or ROOT / "weights")
SIZE = next(
    (
        s
        for s in ("medium", "large-v3-turbo", "small", "large-v3")
        if is_complete(WHISPER[s], WEIGHTS)
    ),
    None,
)
MAX_CER = 0.4 if SIZE == "small" else 0.15

pytestmark = [
    pytest.mark.skipif(
        importlib.util.find_spec("faster_whisper") is None, reason="uv sync --extra whisper"
    ),
    pytest.mark.skipif(SIZE is None, reason=f"no faster-whisper weights in {WEIGHTS}"),
]


@pytest.fixture(scope="module")
def whisper():
    from interview_assistant.providers.stt.faster_whisper import FasterWhisperSTT

    stt = FasterWhisperSTT(model=SIZE, weights_dir=WEIGHTS, beam_size=1)
    asyncio.run(stt.warm_up())
    return stt


def test_batch_transcribes_the_korean_sample(whisper, no_external_network):
    segments = asyncio.run(whisper.transcribe(SAMPLE.as_uri()))
    text = " ".join(s.text for s in segments)
    assert cer(SAMPLE_TEXT, text) < MAX_CER, text
    assert segments[0].start_ms < segments[-1].end_ms <= 12000
    assert whisper.model == f"faster-whisper-{SIZE}"


def test_stream_yields_partials_then_finals(whisper, no_external_network):
    async def run():
        return [s async for s in whisper.stream(pcm_chunks(decode_pcm16(SAMPLE)))]

    segments = asyncio.run(run())
    finals = [s for s in segments if s.is_final]
    assert finals and segments[-1].is_final
    assert cer(SAMPLE_TEXT, " ".join(s.text for s in finals)) < MAX_CER + 0.05
    assert all(s.end_ms >= s.start_ms for s in segments)


def test_switching_batch_stt_to_whisper_through_the_api(api, no_external_network):
    api.runtime.settings.weights_dir = WEIGHTS  # the downloaded weights, not the test's empty dir
    spec = {"impl": "faster_whisper", "options": {"model": SIZE, "beam_size": 1}}
    import json

    result = api.post("/api/admin/models/stt.batch/test", data={"spec": json.dumps(spec)}).json()
    assert result["ok"] and result["output"]["cer"] < MAX_CER, result
    state = api.post(
        "/api/admin/models/stt.batch/apply", json={**spec, "reason": "로컬 Whisper"}
    ).json()
    assert state["model"] == f"faster-whisper-{SIZE}" and state["data_location"] == "local"
    assert api.runtime.models.active.get("stt.batch").model == f"faster-whisper-{SIZE}"
    change = api.get("/api/admin/models/history?role=stt.batch").json()[0]
    back = api.post(
        f"/api/admin/models/history/{change['id']}/revert", json={"reason": "원복"}
    ).json()
    assert back["spec"]["impl"] == "fake"
