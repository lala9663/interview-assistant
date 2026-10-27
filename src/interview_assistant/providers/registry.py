"""Resolve `impl` names to provider classes.

Register a new implementation by adding its import path below and its entry in catalog.py (what
the admin screen shows). Modules are imported lazily, so optional dependencies (anthropic,
google-cloud-speech, faster-whisper ...) are only required when selected.
"""

from __future__ import annotations

from collections.abc import Mapping
from importlib import import_module
from typing import Any

from interview_assistant.config import ProviderSpec

_IMPLS: dict[str, dict[str, str]] = {
    "llm": {
        "fake": "interview_assistant.providers.fake:FakeLLM",
        "anthropic_vertex": "interview_assistant.providers.llm.anthropic_vertex:AnthropicVertexLLM",
    },
    "stt": {
        "fake": "interview_assistant.providers.fake:FakeSTT",
        "google_stt_v2": "interview_assistant.providers.stt.google_stt_v2:GoogleSTTv2",
        "faster_whisper": "interview_assistant.providers.stt.faster_whisper:FasterWhisperSTT",
    },
    "embedding": {
        "fake": "interview_assistant.providers.fake:FakeEmbedding",
        "bge_m3": "interview_assistant.providers.embedding.bge_m3:BgeM3Embedding",
        "vertex_embedding": "interview_assistant.providers.embedding.vertex:VertexEmbedding",
    },
    "diarization": {
        "fake": "interview_assistant.providers.fake:FakeDiarization",
        "google_stt_v2": "interview_assistant.providers.diarization.google_stt_v2:GoogleDiarization",
    },
    # 서류 읽기 (documents/reading.py puts them together for each application)
    "ocr": {
        "fake": "interview_assistant.providers.fake:FakeOCR",
        "paddleocr": "interview_assistant.providers.ocr.paddle:PaddleOCRProvider",
        "tesseract": "interview_assistant.providers.ocr.tesseract:TesseractOCR",
        "google_document_ai": "interview_assistant.providers.ocr.google_document_ai:DocumentAIOCR",
        "clova_ocr": "interview_assistant.providers.ocr.clova:ClovaOCR",
    },
    "pdf_reader": {"pdfplumber": "interview_assistant.documents.pdf:PdfExtractor"},
    "hwp_reader": {
        "syhwp": "interview_assistant.documents.hwp:HwpReader",
        "hwplib": "interview_assistant.documents.hwplib:HwplibReader",
    },
    "office_converter": {"libreoffice": "interview_assistant.documents.legacy:LibreOfficeConverter"},
    "reading": {"standard": "interview_assistant.documents.reading:ReadingPolicyProvider"},
}


class UnknownProviderError(LookupError):
    pass


def is_registered(kind: str, impl: str) -> bool:
    return impl in _IMPLS.get(kind, {})


def import_path(kind: str, impl: str) -> str | None:
    return _IMPLS.get(kind, {}).get(impl)


def resolve(kind: str, spec: ProviderSpec, context: Mapping[str, Any] | None = None) -> Any:
    """Build the provider. `context` holds runtime values (the weights folder ...) a class asks
    for by listing their names in `context_keys`; they override same-named spec options."""
    try:
        path = _IMPLS[kind][spec.impl]
    except KeyError as e:
        known = ", ".join(sorted(_IMPLS.get(kind, {})))
        raise UnknownProviderError(
            f"{kind}: impl '{spec.impl}' is not registered (known: {known})"
        ) from e
    module_name, class_name = path.split(":")
    try:
        module = import_module(module_name)
    except ModuleNotFoundError as e:
        raise UnknownProviderError(
            f"{kind}: impl '{spec.impl}' is registered but {module_name} is not implemented "
            f"or its dependency is missing ({e})"
        ) from e
    cls = getattr(module, class_name)
    wanted = {k: v for k, v in (context or {}).items() if k in getattr(cls, "context_keys", ())}
    return cls(**{**spec.options, **wanted})
