"""PaddleOCR and faster-whisper active together in one server process, whichever loads first.

Paddle's bundled Intel OpenMP is older than CTranslate2's; with both in one process,
faster-whisper failed to load after PaddleOCR (WinError 127). PaddleOCR now runs in a worker
process (providers/isolated.py). These tests turn both engines on through the admin API and use
them in turn, check that paddle never enters the server process, and replay the failing order in
a fresh interpreter, independent of what this test session has already loaded.

Skipped unless both engines and their model files are on this machine (`uv sync --extra whisper
--extra ocr`, downloads from 관리자 > 모델 설정). No network.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from interview_assistant.providers.weights import BGE_M3, PADDLEOCR, WHISPER, is_complete

from .conftest import ROOT

WEIGHTS = Path(os.environ.get("IA_WEIGHTS_DIR") or ROOT / "weights")
SIZE = next((s for s in ("small", "medium", "large-v3-turbo", "large-v3") if is_complete(WHISPER[s], WEIGHTS)), None)

pytestmark = [
    pytest.mark.skipif(
        importlib.util.find_spec("paddleocr") is None or not is_complete(PADDLEOCR["ppocrv5-mobile"], WEIGHTS),
        reason="paddleocr or the PP-OCRv5 model files are missing",
    ),
    pytest.mark.skipif(
        importlib.util.find_spec("faster_whisper") is None or SIZE is None,
        reason="faster-whisper or its model files are missing",
    ),
]

OCR = {"impl": "paddleocr", "options": {"model": "ppocrv5-mobile"}}
STT = {"impl": "faster_whisper", "options": {"model": SIZE, "beam_size": 1}}


def _paddle_loaded() -> bool:
    return any(name == "paddle" or name.startswith(("paddle.", "paddleocr", "paddlex")) for name in sys.modules)


def _test(api, role: str, spec: dict) -> dict:
    result = api.post(f"/api/admin/models/{role}/test", data={"spec": json.dumps(spec)}).json()
    assert result["ok"], (role, result)
    return result


def test_ocr_and_whisper_turned_on_together_both_work(api):
    api.runtime.settings.weights_dir = WEIGHTS  # the downloaded weights, not the test's empty dir
    for role, spec, reason in (
        ("document.ocr", OCR, "스캔본 읽기"),  # OCR first: the order that used to break Whisper
        ("stt.batch", STT, "로컬 Whisper"),
    ):
        state = api.post(f"/api/admin/models/{role}/apply", json={**spec, "reason": reason}).json()
        assert state["status"] == "ready", state
    active = api.runtime.models.active
    assert active.get("document.ocr").model == "PP-OCRv5 mobile 한국어"
    assert active.get("stt.batch").model == f"faster-whisper-{SIZE}"

    first = _test(api, "document.ocr", OCR)  # reads the built-in scan sample with PaddleOCR
    assert first["output"]["pages"][0]["method"] == "ocr" and first["output"]["cer"] < 0.05
    heard = _test(api, "stt.batch", STT)  # loads CTranslate2 after Paddle ran
    assert heard["output"]["text"].strip()
    again = _test(api, "document.ocr", OCR)
    assert again["output"]["cer"] == first["output"]["cer"]
    assert not _paddle_loaded(), "PaddleOCR must run in its worker process, not in the server"


def test_paddleocr_first_then_whisper_in_a_fresh_process():
    script = textwrap.dedent(
        f"""
        import asyncio, json, sys
        from pathlib import Path
        from PIL import Image
        from interview_assistant.providers.audio import SAMPLE
        from interview_assistant.providers.ocr.paddle import PaddleOCRProvider
        from interview_assistant.providers.stt.faster_whisper import FasterWhisperSTT

        weights = Path({str(WEIGHTS)!r})
        ocr = PaddleOCRProvider(weights_dir=weights)
        page = Image.open({str(ROOT / "src/interview_assistant/providers/samples/documents/ocr-sample.png")!r})
        lines = len(ocr.recognize(page).lines)
        stt = FasterWhisperSTT(model={SIZE!r}, weights_dir=weights, beam_size=1)
        asyncio.run(stt.warm_up())
        text = " ".join(s.text for s in asyncio.run(stt.transcribe(SAMPLE.as_uri())))
        again = len(ocr.recognize(page).lines)
        paddle = any(m == "paddle" or m.startswith("paddle.") for m in sys.modules)
        print(json.dumps({{"lines": lines, "again": again, "text": text, "paddle": paddle}}))
        """
    )
    done = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, timeout=600, cwd=ROOT, env={**os.environ, "PYTHONIOENCODING": "utf-8"}
    )
    out = done.stdout.decode("utf-8", "replace").strip().splitlines()
    assert done.returncode == 0 and out, done.stderr.decode("utf-8", "replace")[-3000:]
    result = json.loads(out[-1])
    assert result["lines"] > 10 and result["again"] == result["lines"]
    assert result["text"].strip() and result["paddle"] is False


@pytest.mark.skipif(
    importlib.util.find_spec("onnxruntime") is None or not is_complete(BGE_M3["bge-m3"], WEIGHTS),
    reason="onnxruntime or the BGE-M3 model files are missing",
)
def test_bge_m3_joins_ocr_and_whisper(api):
    """All three local engines on at once through the admin API, each still answering."""
    api.runtime.settings.weights_dir = WEIGHTS
    for role, spec, reason in (
        ("document.ocr", OCR, "스캔본 읽기"),
        ("stt.batch", STT, "로컬 Whisper"),
        ("embedding", {"impl": "bge_m3", "options": {"model": "bge-m3"}}, "질문 은행 검색"),
    ):
        state = api.post(f"/api/admin/models/{role}/apply", json={**spec, "reason": reason}).json()
        assert state["status"] == "ready", state
    embedded = _test(api, "embedding", {"impl": "bge_m3", "options": {"model": "bge-m3"}})
    assert embedded["output"]["dimensions"] == 1024 and embedded["output"]["sparse"]
    assert embedded["output"]["similar"] > embedded["output"]["unrelated"]
    assert _test(api, "stt.batch", STT)["output"]["text"].strip()
    assert _test(api, "document.ocr", OCR)["output"]["cer"] < 0.05
    assert not _paddle_loaded()
