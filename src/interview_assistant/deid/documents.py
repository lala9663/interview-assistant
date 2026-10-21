"""De-identify an extracted document: every block, file name and properties included.

All blocks go through the de-identifier as one text, so a name first seen with a title in one
block ("오태호 팀장님") is also caught where it appears alone in another, and tokens stay
consistent across blocks. A separator no detector can match keeps spans from crossing block
boundaries; should one ever cross, each block is de-identified on its own instead.

A document with pages that need OCR is refused (`OcrRequired`): sending the readable part
alone would silently drop content, and the PoC has no OCR.
"""

from __future__ import annotations

from dataclasses import dataclass

from interview_assistant.deid.deidentifier import Deidentifier
from interview_assistant.deid.types import KnownIdentity, Replacement
from interview_assistant.documents.types import BlockKind, ExtractedDocument, render_blocks

_SEPARATOR = "\n\n␞\n\n"  # SYMBOL FOR RECORD SEPARATOR: not whitespace, letter or digit


class OcrRequired(Exception):
    def __init__(self, pages: list[int]) -> None:
        super().__init__(f"OCR 필요 (쪽: {', '.join(map(str, pages))}), 처리 보류")
        self.pages = pages


@dataclass(frozen=True)
class DeidentifiedBlock:
    kind: BlockKind
    label: str
    text: str
    replacements: tuple[Replacement, ...]  # offsets into the block's original text


@dataclass(frozen=True)
class DeidentifiedDocument:
    format: str
    blocks: tuple[DeidentifiedBlock, ...]
    images_dropped: int

    @property
    def text(self) -> str:
        """What may be sent to an LLM: every block, labelled, tokens in place of identifiers."""
        return render_blocks(self.blocks)

    @property
    def replacements(self) -> int:
        return sum(len(b.replacements) for b in self.blocks)


def deidentify_document(
    deidentifier: Deidentifier,
    document: ExtractedDocument,
    *,
    candidate_id: str,
    known: KnownIdentity | None = None,
) -> DeidentifiedDocument:
    if document.needs_ocr:
        raise OcrRequired(document.ocr_pages)
    texts = [b.text.replace("␞", " ") for b in document.blocks]
    result = deidentifier.deidentify(_SEPARATOR.join(texts), candidate_id=candidate_id, known=known)

    starts, pos = [], 0
    for text in texts:
        starts.append(pos)
        pos += len(text) + len(_SEPARATOR)
    per_block: list[list[Replacement]] = [[] for _ in texts]
    crossed = False
    for r in result.replacements:
        i = max(j for j, s in enumerate(starts) if s <= r.start)
        if r.end > starts[i] + len(texts[i]):
            crossed = True
            break
        per_block[i].append(
            Replacement(r.start - starts[i], r.end - starts[i], r.category, r.token, r.detector)
        )

    blocks = []
    for block, text, replacements in zip(document.blocks, texts, per_block, strict=True):
        if crossed:
            single = deidentifier.deidentify(text, candidate_id=candidate_id, known=known)
            blocks.append(DeidentifiedBlock(block.kind, block.label, single.text, single.replacements))
        else:
            blocks.append(
                DeidentifiedBlock(block.kind, block.label, _apply(text, replacements), tuple(replacements))
            )
    return DeidentifiedDocument(document.format, tuple(blocks), document.images_dropped)


def _apply(text: str, replacements: list[Replacement]) -> str:
    out, pos = [], 0
    for r in replacements:
        out.append(text[pos : r.start])
        out.append(r.token)
        pos = r.end
    out.append(text[pos:])
    return "".join(out)
