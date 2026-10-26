"""Local OCR with Tesseract 5 (Apache-2.0), for comparison with PaddleOCR. Images stay on the machine.

The `tesseract` program is a system install (providers/programs.py); the Korean and English language
data come from the admin screen's download (tessdata best or fast, pinned commit). Each page is a
temporary PNG handed to the command line, which answers in TSV (word boxes and confidences); no
Python binding is needed.

Tesseract segments Korean into syllables more often than PaddleOCR ("설 도 현"); de-identification
already accepts spaces inside a known name, and error rates are measured without spaces.
"""

from __future__ import annotations

import subprocess
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from interview_assistant.providers.base import OCRProvider, OcrLine, OcrResult, ProviderUnavailable
from interview_assistant.providers.programs import TESSERACT
from interview_assistant.providers.weights import TESSDATA, is_complete

if TYPE_CHECKING:
    from PIL.Image import Image

TIMEOUT_S = 180


class TesseractOCR(OCRProvider):
    context_keys = ("weights_dir",)

    def __init__(
        self,
        model: str = "best",
        psm: int = 3,
        weights_dir: str | Path = "weights",
        **_: Any,
    ) -> None:
        if model not in TESSDATA:
            raise ValueError(f"unknown tessdata '{model}' (known: {', '.join(TESSDATA)})")
        self.weights = TESSDATA[model]
        self.weights_dir = Path(weights_dir)
        self.psm = psm
        self.model = f"Tesseract kor+eng ({model})"
        self.version = f"Tesseract · tessdata_{model} kor+eng"

    def _command(self) -> Path:
        exe = TESSERACT.find()
        if exe is None:
            raise ProviderUnavailable("tesseract 프로그램이 없습니다. " + TESSERACT.install)
        if not is_complete(self.weights, self.weights_dir):
            raise ProviderUnavailable(
                f"Tesseract 언어 데이터가 없습니다 ({self.weights.key}). 관리자 > 모델 설정에서 내려받으세요."
            )
        version = TESSERACT.version()
        if version:
            self.version = f"{version} · tessdata_{self.weights.key.rsplit('-', 1)[-1]} kor+eng"
        return exe

    async def warm_up(self) -> None:
        self._command()

    def recognize(self, image: Image) -> OcrResult:
        exe = self._command()
        started = time.perf_counter()
        with tempfile.TemporaryDirectory(prefix="ia-ocr-") as tmp:
            page = Path(tmp) / "page.png"
            image.convert("L").save(page, format="PNG")
            try:
                done = subprocess.run(
                    [
                        str(exe), str(page), "stdout",
                        "-l", "kor+eng",
                        "--tessdata-dir", str(self.weights.path(self.weights_dir)),
                        "--psm", str(self.psm),
                        "-c", "tessedit_create_tsv=1",
                    ],
                    capture_output=True,
                    timeout=TIMEOUT_S,
                    check=False,
                )  # fmt: skip
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError(f"Tesseract가 {TIMEOUT_S}초 안에 끝나지 않았습니다.") from exc
        if done.returncode != 0:
            message = done.stderr.decode("utf-8", "replace").strip().splitlines()[-1:]
            raise RuntimeError(f"Tesseract 실패: {' '.join(message) or done.returncode}")
        lines = parse_tsv(done.stdout.decode("utf-8", "replace"))
        elapsed = round((time.perf_counter() - started) * 1000)
        return OcrResult(tuple(lines), self.model, elapsed)


def parse_tsv(tsv: str) -> list[OcrLine]:
    """Word rows (level 5) grouped into their lines, with the line's box and mean confidence."""
    words: dict[tuple[str, str, str, str], list[tuple[str, float, tuple[int, int, int, int]]]] = {}
    for row in tsv.splitlines()[1:]:
        cols = row.split("\t")
        if len(cols) < 12 or cols[0] != "5" or not cols[11].strip():
            continue
        left, top, width, height = (int(v) for v in cols[6:10])
        key = (cols[1], cols[2], cols[3], cols[4])  # page, block, paragraph, line
        words.setdefault(key, []).append(
            (cols[11].strip(), max(0.0, float(cols[10])) / 100, (left, top, left + width, top + height))
        )
    lines = []
    for items in words.values():
        text = " ".join(w for w, _, _ in items)
        confidence = sum(c * len(w) for w, c, _ in items) / max(1, sum(len(w) for w, _, _ in items))
        box = (
            min(b[0] for _, _, b in items),
            min(b[1] for _, _, b in items),
            max(b[2] for _, _, b in items),
            max(b[3] for _, _, b in items),
        )
        lines.append(OcrLine(text, confidence, tuple(float(v) for v in box)))  # type: ignore[arg-type]
    return lines
