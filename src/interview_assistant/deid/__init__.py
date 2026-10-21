"""De-identification: replace identifying data with per-candidate tokens before text reaches an LLM.

    config = load_deid_config(Settings().deid_file)
    store = SqlTokenStore(session, FieldCipher.from_settings(), config.token_formats())
    deid = build_deidentifier(config, store)
    result = deid.deidentify(answer_text, candidate_id=candidate.id, known=identity)
    qa_item.answer_deidentified = result.text

Files go through `deidentify_document(deid, extract_document(data, filename), ...)`, which covers
every extracted block including the file name and properties and refuses scans (OcrRequired).

Reverse lookup lives in `interview_assistant.deid.reidentify` and is deliberately not exported here.
"""

from interview_assistant.deid.config import (
    DeidConfig,
    build_deidentifier,
    build_detectors,
    load_deid_config,
)
from interview_assistant.deid.deidentifier import Deidentifier
from interview_assistant.deid.documents import (
    DeidentifiedBlock,
    DeidentifiedDocument,
    OcrRequired,
    deidentify_document,
)
from interview_assistant.deid.identity import open_identity, seal_identity
from interview_assistant.deid.store import (
    InMemoryTokenStore,
    SqlTokenStore,
    TokenFormats,
    TokenStore,
)
from interview_assistant.deid.types import (
    DeidCategory,
    DeidResult,
    Detection,
    KnownIdentity,
    Replacement,
)

__all__ = [
    "DeidCategory",
    "DeidConfig",
    "DeidResult",
    "DeidentifiedBlock",
    "DeidentifiedDocument",
    "Deidentifier",
    "Detection",
    "InMemoryTokenStore",
    "KnownIdentity",
    "OcrRequired",
    "Replacement",
    "SqlTokenStore",
    "TokenFormats",
    "TokenStore",
    "build_deidentifier",
    "build_detectors",
    "deidentify_document",
    "load_deid_config",
    "open_identity",
    "seal_identity",
]
