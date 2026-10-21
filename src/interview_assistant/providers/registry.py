"""Resolve `impl` names from providers.yaml to provider classes.

Register a new implementation by adding its import path below. Modules are imported lazily, so
optional dependencies (anthropic, google-cloud-speech, ...) are only required when selected.
"""

from __future__ import annotations

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
    },
    "embedding": {
        "fake": "interview_assistant.providers.fake:FakeEmbedding",
        "vertex_embedding": "interview_assistant.providers.embedding.vertex:VertexEmbedding",
    },
    "diarization": {
        "fake": "interview_assistant.providers.fake:FakeDiarization",
        "google_stt_v2": "interview_assistant.providers.diarization.google_stt_v2:GoogleDiarization",
    },
}


class UnknownProviderError(LookupError):
    pass


def is_registered(kind: str, impl: str) -> bool:
    return impl in _IMPLS.get(kind, {})


def resolve(kind: str, spec: ProviderSpec) -> Any:
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
    return cls(**spec.options)
