"""The real OCR engines on the fixtures: leak check with OCR, error rate, the reading record.

Skipped unless the engine and its model files are on this machine: PaddleOCR needs
`uv sync --extra ocr` and the PP-OCRv5 bundle in IA_WEIGHTS_DIR (weights/), Tesseract its program
and tessdata. Both download from 관리자 > 모델 설정. Nothing here uses the network.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

from interview_assistant.deid.leaks import CHECKED, load_document_samples, run_document_leak_check
from interview_assistant.documents.reading import DocumentReader, ReadingPolicy
from interview_assistant.providers import programs
from interview_assistant.providers.weights import PADDLEOCR, TESSDATA, is_complete

from .conftest import ROOT

MANIFEST = ROOT / "tests" / "fixtures" / "resumes" / "manifest.yaml"
WEIGHTS = Path(os.environ.get("IA_WEIGHTS_DIR") or ROOT / "weights")
OCR_SAMPLES = ("R18", "R19", "R20", "R21", "R24", "R25", "R26", "R27", "R28", "R30")

paddle_ready = importlib.util.find_spec("paddleocr") is not None and is_complete(PADDLEOCR["ppocrv5-mobile"], WEIGHTS)
tesseract_ready = programs.TESSERACT.find() is not None and is_complete(TESSDATA["best"], WEIGHTS)


def _check(ocr, deid_config):
    samples = [s for s in load_document_samples(MANIFEST) if s.id in OCR_SAMPLES]
    reader = DocumentReader(policy=ReadingPolicy(), ocr=ocr)
    return {r.sample.id: r for r in run_document_leak_check(samples, deid_config, reader=reader)}


@pytest.fixture(scope="module")
def paddle():
    from interview_assistant.providers.ocr.paddle import PaddleOCRProvider

    provider = PaddleOCRProvider(weights_dir=WEIGHTS)
    yield provider
    provider.close()


@pytest.mark.skipif(not paddle_ready, reason="paddleocr or the PP-OCRv5 model files are missing")
def test_paddleocr_samples_leak_nothing_and_read_well(paddle, deid_config, no_external_network):
    reports = _check(paddle, deid_config)
    failures = {i: (r.problems, r.leaks, r.near, r.residual, r.lost, r.not_in_source) for i, r in reports.items() if not r.ok}
    assert failures == {}
    assert all(r.status == CHECKED for r in reports.values())
    assert sum(r.leaked_values for r in reports.values()) == 0
    rates = {i: r.cer for i, r in reports.items() if r.cer is not None}
    assert set(rates) == {"R18", "R19", "R20", "R21", "R24", "R25", "R26", "R27", "R28", "R30"}
    assert max(rates.values()) < 0.05, rates  # character error rate below 5% on every sample
    page = reports["R24"].document.pages[0]  # the phone photo
    assert page.tool.startswith("PaddleOCR 3.7.0") and page.confidence > 0.9
    assert "paddle" not in sys.modules  # it ran in its worker process (tests/test_engines_together.py)


@pytest.mark.skipif(not tesseract_ready, reason="tesseract or its tessdata (best) is missing")
def test_tesseract_samples_leak_nothing(deid_config, no_external_network):
    from interview_assistant.providers.ocr.tesseract import TesseractOCR

    reports = _check(TesseractOCR(model="best", weights_dir=WEIGHTS), deid_config)
    leaked = {i: (r.leaks, r.near, r.residual) for i, r in reports.items() if r.leaked_values}
    assert leaked == {}
    assert reports["R19"].cer is not None and reports["R19"].cer < 0.10  # clean scan; R25 measures ~28%
