"""Local OCR on CPU with PaddleOCR 3 and PP-OCRv5 (Apache-2.0). Images never leave the machine.

Detection (mobile or server) plus the Korean recognizer (Korean, English, digits), loaded from the
admin screen's download (providers/weights.py) on `warm_up` or first use; nothing is fetched at
run time and PaddleX's model-host check is switched off. Optional orientation classifiers turn
lines and pages the right way up (phone photos). Both are off by default: on upright scans the
line classifier turned some correct lines upside down and wrecked them ("성명: 설도현" read as
"S눌공Y"), costing more than it saves.

Paddle runs in its own worker process (`PaddleEngine` there, providers/isolated.py): its bundled
Intel OpenMP is older than the one CTranslate2 needs, and in one process with faster-whisper one of
the two fails to load. The server process never imports paddle; it sends the page image and gets
the lines back.

paddlepaddle is pinned to 3.2.x: 3.3.1's oneDNN path fails on Windows CPUs ("ConvertPirAttribute2
RuntimeAttribute not support"), and without oneDNN a page takes 4x longer. Should another version
fail the same way anyway, the pipeline is rebuilt once with oneDNN off.

Measured on this laptop (i7-1360P, docs/ocr-benchmark.md): mobile detection 2-7 s per A4 page at
200 dpi (two to three times that while other work loads the CPU), 1.3-1.6 GB peak for the worker,
character error rate 0.5% on the Korean samples; server detection 30 s or more and 2.9 GB.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import time
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import TYPE_CHECKING, Any

from interview_assistant.providers.base import OCRProvider, OcrLine, OcrResult, ProviderUnavailable
from interview_assistant.providers.isolated import WorkerProcess
from interview_assistant.providers.weights import PADDLEOCR, is_complete

if TYPE_CHECKING:
    from PIL.Image import Image

_LABELS = {"ppocrv5-mobile": "mobile", "ppocrv5-server": "server"}


class PaddleOCRProvider(OCRProvider):
    context_keys = ("weights_dir",)

    def __init__(
        self,
        model: str = "ppocrv5-mobile",
        textline_orientation: bool = False,
        doc_orientation: bool = False,
        max_side: int = 2400,
        cpu_threads: int = 0,
        weights_dir: str | Path = "weights",
        **_: Any,
    ) -> None:
        if model not in PADDLEOCR:
            raise ValueError(f"unknown PaddleOCR model '{model}' (known: {', '.join(PADDLEOCR)})")
        self.weights = PADDLEOCR[model]
        self.weights_dir = Path(weights_dir)
        self.max_side = max_side
        size = _LABELS[model]
        self.model = f"PP-OCRv5 {size} 한국어"
        try:
            engine = f"PaddleOCR {version('paddleocr')}"
        except PackageNotFoundError:
            engine = "PaddleOCR"
        self.version = f"{engine} · PP-OCRv5_{size}_det + korean_PP-OCRv5_mobile_rec"
        self._worker = WorkerProcess(
            f"{__name__}:PaddleEngine",
            {
                "root": str(self.weights.path(self.weights_dir)),
                "server": size == "server",
                "textline_orientation": textline_orientation,
                "doc_orientation": doc_orientation,
                "cpu_threads": cpu_threads or max(4, (os.cpu_count() or 8) - 4),
            },
            label="PaddleOCR",
        )
        self._loaded = False

    async def warm_up(self) -> None:
        await asyncio.to_thread(self._load)

    def _load(self) -> None:
        if self._loaded and self._worker.pid is not None:
            return
        if not is_complete(self.weights, self.weights_dir):
            raise ProviderUnavailable(
                f"PaddleOCR 모델 파일이 없습니다 ({self.weights.key}). 관리자 > 모델 설정에서 내려받으세요."
            )
        if importlib.util.find_spec("paddleocr") is None:
            raise ProviderUnavailable("paddleocr 패키지가 없습니다 (uv sync --extra ocr).")
        self._worker.call("load")
        self._loaded = True

    def recognize(self, image: Image) -> OcrResult:
        started = time.perf_counter()
        self._load()
        rgb = image.convert("RGB")
        scale = min(1.0, self.max_side / max(rgb.size))
        if scale < 1.0:
            rgb = rgb.resize((round(rgb.width * scale), round(rgb.height * scale)))
        found = self._worker.call("recognize", rgb)
        lines = tuple(
            OcrLine(text, score, (x0 / scale, y0 / scale, x1 / scale, y1 / scale))
            for text, score, (x0, y0, x1, y1) in found
        )
        elapsed = round((time.perf_counter() - started) * 1000)
        return OcrResult(lines, self.model, elapsed)

    def close(self) -> None:
        """Stop the worker process now (it also stops when this provider is dropped)."""
        self._worker.close()
        self._loaded = False


class PaddleEngine:
    """The PaddleOCR pipeline itself. Runs only inside the worker process: the one place that
    imports paddle."""

    def __init__(
        self,
        *,
        root: str,
        server: bool,
        textline_orientation: bool,
        doc_orientation: bool,
        cpu_threads: int,
    ) -> None:
        self.root = Path(root)
        self.det = "PP-OCRv5_server_det" if server else "PP-OCRv5_mobile_det"
        self.textline_orientation = textline_orientation
        self.doc_orientation = doc_orientation
        self.cpu_threads = cpu_threads
        self._pipeline: Any = None
        self._mkldnn = True

    def load(self) -> None:
        if self._pipeline is None:
            self._pipeline = self._build()

    def _build(self) -> Any:
        # No connectivity check against PaddleX's model hosts: everything is on disk already.
        os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
        try:
            import paddleocr
        except ImportError as exc:
            raise ProviderUnavailable("paddleocr 패키지가 없습니다 (uv sync --extra ocr).") from exc
        return paddleocr.PaddleOCR(
            text_detection_model_name=self.det,
            text_detection_model_dir=str(self.root / "det"),
            text_recognition_model_name="korean_PP-OCRv5_mobile_rec",
            text_recognition_model_dir=str(self.root / "rec"),
            use_textline_orientation=self.textline_orientation,
            textline_orientation_model_name="PP-LCNet_x1_0_textline_ori",
            textline_orientation_model_dir=str(self.root / "textline_ori"),
            use_doc_orientation_classify=self.doc_orientation,
            doc_orientation_classify_model_name="PP-LCNet_x1_0_doc_ori",
            doc_orientation_classify_model_dir=str(self.root / "doc_ori"),
            use_doc_unwarping=False,
            device="cpu",
            enable_mkldnn=self._mkldnn,
            cpu_threads=self.cpu_threads,
        )

    def recognize(self, image: Image) -> list[tuple[str, float, tuple[float, float, float, float]]]:
        """(text, confidence, box) per line, in the given image's pixels."""
        import numpy as np

        self.load()
        bgr = np.asarray(image)[:, :, ::-1]
        try:
            results = self._pipeline.predict(bgr)
        except NotImplementedError:
            if not self._mkldnn:
                raise
            self._mkldnn = False  # see the module docstring
            self._pipeline = self._build()
            results = self._pipeline.predict(bgr)
        lines = []
        for result in results:
            texts, scores, boxes = result["rec_texts"], result["rec_scores"], result["rec_boxes"]
            for text, score, box in zip(texts, scores, boxes, strict=False):
                if text.strip():
                    x0, y0, x1, y1 = (float(v) for v in box[:4])
                    lines.append((str(text), float(score), (x0, y0, x1, y1)))
        return lines
