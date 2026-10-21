"""Document text extraction (PDF, DOCX, PPTX, HTML). Raw zone only.

    document = extract_document(upload_bytes, upload_filename)
    if document.needs_ocr:
        ...  # hold: no OCR in the PoC, nothing is sent
    result = deidentify_document(deid, document, candidate_id=cid, known=identity)
    prompt_text = result.text

Images are counted and dropped, never extracted. Swap an extractor by passing your own mapping
to `extract_document(..., extractors=...)`; each implements `DocumentExtractor`.
"""

from interview_assistant.documents.base import (
    DocumentExtractor,
    ExtractionError,
    UnsupportedFormat,
    default_extractors,
    detect_format,
    extract_document,
)
from interview_assistant.documents.normalize import normalize_text
from interview_assistant.documents.types import (
    BlockKind,
    ExtractedDocument,
    PageInfo,
    TextBlock,
    render_blocks,
)

__all__ = [
    "BlockKind",
    "DocumentExtractor",
    "ExtractedDocument",
    "ExtractionError",
    "PageInfo",
    "TextBlock",
    "UnsupportedFormat",
    "default_extractors",
    "detect_format",
    "extract_document",
    "normalize_text",
    "render_blocks",
]
