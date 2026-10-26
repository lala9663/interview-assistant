"""Local OCR on CPU with PaddleOCR 3 and PP-OCRv5 (Apache-2.0). Images never leave the machine.

Detection (mobile or server) plus the Korean recognizer (Korean, English, digits), loaded from the
admin screen's download (providers/weights.py) on `warm_up` or first use; nothing is fetched at
run time and PaddleX's model-host check is switched off. Optional orientation classifiers turn
lines and pages the right way up (phone photos). Both are off by default: on upright scans the
line classifier turned some correct lines upside down and wrecked them ("성명: 설도현" read as
"S눌공Y"), costing more than it saves.

paddlepaddle is pinned to 3.2.x: 3.3.1's oneDNN path fails on Windows CPUs ("ConvertPirAttribute2
RuntimeAttribute not support"), and without oneDNN a page takes 4x longer. Should another version
fail the same way anyway, the pipeline is rebuilt once with oneDNN off.

Measured on this laptop (i7-1360P, docs/ocr-benchmark.md): mobile detection 2-7 s per A4 page at
200 dpi (two to three times that while other work loads the CPU), 1.3-1.6 GB peak for the process,
character error rate 0.5% on the Korean samples; server detection 30 s or more and 2.9 GB.
"""

from __future__ import annotations

import asyncio
import os
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from interview_assistant.providers.base import OCRProvider, OcrLine, OcrResult, ProviderUnavailable
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
        self.textline_orientation = textline_orientation
        self.doc_orientation = doc_orientation
        self.max_side = max_side
        self.cpu_threads = cpu_threads or max(4, (os.cpu_count() or 8) - 4)
        size = _LABELS[model]
        self.model = f"PP-OCRv5 {size} 한국어"
        self.version = f"PaddleOCR · PP-OCRv5_{size}_det + korean_PP-OCRv5_mobile_rec"
        self._pipeline: Any = None
        self._mkldnn = True
        self._lock = threading.Lock()

    async def warm_up(self) -> None:
        await asyncio.to_thread(self._load)

    def _load(self) -> Any:
        with self._lock:
            if self._pipeline is None:
                self._pipeline = self._build()
            return self._pipeline

    def _build(self) -> Any:
        if not is_complete(self.weights, self.weights_dir):
            raise ProviderUnavailable(
                f"PaddleOCR 모델 파일이 없습니다 ({self.weights.key}). 관리자 > 모델 설정에서 내려받으세요."
            )
        # No connectivity check against PaddleX's model hosts: everything is on disk already.
        os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
        try:
            import paddleocr
        except ImportError as exc:
            raise ProviderUnavailable(
                "paddleocr 패키지가 없습니다 (uv sync --extra ocr)."
            ) from exc
        root = self.weights.path(self.weights_dir)
        det = "PP-OCRv5_server_det" if "server" in self.weights.key else "PP-OCRv5_mobile_det"
        pipeline = paddleocr.PaddleOCR(
            text_detection_model_name=det,
            text_detection_model_dir=str(root / "det"),
            text_recognition_model_name="korean_PP-OCRv5_mobile_rec",
            text_recognition_model_dir=str(root / "rec"),
            use_textline_orientation=self.textline_orientation,
            textline_orientation_model_name="PP-LCNet_x1_0_textline_ori",
            textline_orientation_model_dir=str(root / "textline_ori"),
            use_doc_orientation_classify=self.doc_orientation,
            doc_orientation_classify_model_name="PP-LCNet_x1_0_doc_ori",
            doc_orientation_classify_model_dir=str(root / "doc_ori"),
            use_doc_unwarping=False,
            device="cpu",
            enable_mkldnn=self._mkldnn,
            cpu_threads=self.cpu_threads,
        )
        engine = " ".join(filter(None, ("PaddleOCR", getattr(paddleocr, "__version__", ""))))
        self.version = f"{engine} · {det} + korean_PP-OCRv5_mobile_rec"
        return pipeline

    def recognize(self, image: Image) -> OcrResult:
        import numpy as np

        started = time.perf_counter()
        pipeline = self._load()
        rgb = image.convert("RGB")
        scale = min(1.0, self.max_side / max(rgb.size))
        if scale < 1.0:
            rgb = rgb.resize((round(rgb.width * scale), round(rgb.height * scale)))
        bgr = np.asarray(rgb)[:, :, ::-1]
        with self._lock:
            try:
                results = pipeline.predict(bgr)
            except NotImplementedError:
                if not self._mkldnn:
                    raise
                self._mkldnn = False  # see the module docstring
                self._pipeline = pipeline = self._build()
                results = pipeline.predict(bgr)
        lines: list[OcrLine] = []
        for result in results:
            texts, scores, boxes = result["rec_texts"], result["rec_scores"], result["rec_boxes"]
            for text, score, box in zip(texts, scores, boxes, strict=False):
                if text.strip():
                    x0, y0, x1, y1 = (float(v) / scale for v in box[:4])
                    lines.append(OcrLine(text, float(score), (x0, y0, x1, y1)))
        elapsed = round((time.perf_counter() - started) * 1000)
        return OcrResult(tuple(lines), self.model, elapsed)
