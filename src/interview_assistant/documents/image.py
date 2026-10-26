"""Picture files (JPG, PNG): a resume photographed with a phone or saved as an image.

The whole picture is one page and is read by OCR (no text layer exists); with the text-only
setting, or without an OCR engine, it is held. Text a phone or editor stores in the file (EXIF
author and description, PNG text chunks) is extracted as properties, like a PDF's author, so it
is de-identified too. The picture itself is never kept or forwarded.
"""

from __future__ import annotations

from typing import Any

from interview_assistant.documents.base import BlockCollector, DocumentExtractor, ExtractionError
from interview_assistant.documents.images import ImageError, open_image, text_metadata
from interview_assistant.documents.types import BlockKind, ExtractedDocument, PageInfo, ReadMethod


class ImageExtractor(DocumentExtractor):
    format = "image"
    tool = "Pillow"

    def __init__(self) -> None:
        from interview_assistant.documents.reading import package_version

        self.tool = package_version("pillow")

    def extract(self, data: bytes, filename: str, *, reading: Any = None) -> ExtractedDocument:
        try:
            image = open_image(data)
        except ImageError as exc:
            raise ExtractionError(str(exc)) from None
        out = BlockCollector(filename, self.format)
        for label, value in text_metadata(data):
            out.add(BlockKind.metadata, label, value)
        out.images = 1
        if reading is None:
            out.pages.append(PageInfo(1, 0, 1.0, True, ReadMethod.held, "그림 파일 (OCR 없음)"))
            out.warnings.append("그림 파일: OCR 필요")
            return out.build()
        method, reason = reading.plan(has_text=False)
        reason = "그림 파일" if method is ReadMethod.ocr and reason == "텍스트 층 없음" else reason
        if method is ReadMethod.held:
            out.pages.append(PageInfo(1, 0, 1.0, True, method, reason))
            out.warnings.append(f"그림 파일: {reason}")
            return out.build()
        result, problem = reading.read(image)
        if result is None:
            out.pages.append(PageInfo(1, 0, 1.0, True, ReadMethod.held, problem))
            out.warnings.append(f"그림 파일: {problem}, 처리 보류")
            return out.build()
        out.add(BlockKind.body, "그림 (OCR)", result.text, ocr=True)
        reading.check_confidence("그림", result)
        chars = sum(len("".join(line.text.split())) for line in result.lines)
        out.pages.append(
            PageInfo(
                1, chars, 1.0, False, ReadMethod.ocr, reason,
                getattr(reading.ocr, "version", "") or result.model,
                result.confidence, result.elapsed_ms,
            )
        )  # fmt: skip
        return out.build()
