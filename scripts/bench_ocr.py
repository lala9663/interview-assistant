"""Measure local OCR (PaddleOCR, Tesseract) on the fictional resumes: time per page and picture,
peak memory, and character error rate against the drawn text (docs/ocr-benchmark.md).

    uv run python scripts/bench_ocr.py --engine paddleocr --model ppocrv5-mobile
    uv run python scripts/bench_ocr.py --engine tesseract --model best

Every manifest sample with OCR truth (scans, phone photos, pictures inside documents, garbled
text layers) is read through the app's 서류 읽기 path (`DocumentReader`, 자동 mode), so the times
include rendering, picture checks and look-alike fixes. Models must already be downloaded (admin >
모델 설정, or IA_WEIGHTS_DIR); legacy .ppt samples need LibreOffice. One untimed read first loads
the engine. Memory is the peak resident set of this process and, separately, of its child
processes (Tesseract runs as one per page), sampled every 50 ms with psutil (installed with the
ocr extra). Run one engine per process: PaddleOCR keeps its models loaded.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import statistics
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "tests" / "fixtures" / "resumes" / "manifest.yaml"


class PeakMemory:
    """Peak resident set of this process and of its children while the block runs."""

    def __init__(self) -> None:
        import psutil

        self._psutil = psutil
        self.process = psutil.Process()
        self.own = 0
        self.children = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._watch, daemon=True)

    def _watch(self) -> None:
        while True:
            self.own = max(self.own, self.process.memory_info().rss)
            kids = 0
            for child in self.process.children(recursive=True):
                try:
                    kids += child.memory_info().rss
                except self._psutil.Error:
                    pass
            self.children = max(self.children, kids)
            if self._stop.wait(0.05):
                return

    def __enter__(self) -> PeakMemory:
        self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._stop.set()
        self._thread.join()


def _mb(n: int) -> str:
    return f"{n / 2**20:,.0f} MB" if n else "-"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--engine", choices=("paddleocr", "tesseract"), required=True)
    parser.add_argument("--model", help="ppocrv5-mobile | ppocrv5-server, or best | fast")
    parser.add_argument("--weights", type=Path, help="model folder (default IA_WEIGHTS_DIR or weights/)")
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--only", nargs="*", default=(), help="sample ids, e.g. R18 R24")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    from interview_assistant.deid.leaks import load_document_samples
    from interview_assistant.documents.legacy import LibreOfficeConverter
    from interview_assistant.documents.reading import DocumentReader, ReadingPolicy
    from interview_assistant.textmetrics import cer

    weights = args.weights or Path(os.environ.get("IA_WEIGHTS_DIR") or ROOT / "weights")
    if args.engine == "paddleocr":
        from interview_assistant.providers.ocr.paddle import PaddleOCRProvider

        ocr = PaddleOCRProvider(model=args.model or "ppocrv5-mobile", weights_dir=weights)
    else:
        from interview_assistant.providers.ocr.tesseract import TesseractOCR

        ocr = TesseractOCR(model=args.model or "best", weights_dir=weights)
    reader = DocumentReader(policy=ReadingPolicy(), ocr=ocr, converter=LibreOfficeConverter())
    samples = [
        s
        for s in load_document_samples(args.manifest)
        if s.ocr_truth and (not args.only or s.id in args.only)
    ]
    if not samples:
        raise SystemExit("OCR 정답이 있는 샘플이 없습니다.")

    started = time.perf_counter()
    asyncio.run(ocr.warm_up())
    load_s = time.perf_counter() - started
    started = time.perf_counter()
    reader.read(samples[0].path.read_bytes(), samples[0].upload_name)  # first call warms the engine
    first_s = time.perf_counter() - started

    print(f"## {ocr.model} ({ocr.version})\n")
    print("| 샘플 | 형식 | OCR한 쪽 | 그림 OCR | 쪽·그림당 시간(초) | 최저 신뢰도 | 글자 오류율 |")
    print("| --- | --- | --- | --- | --- | --- | --- |")
    timings: list[float] = []
    rates: list[float] = []
    with PeakMemory() as peak:
        for sample in samples:
            try:
                document = reader.read(sample.path.read_bytes(), sample.upload_name)
            except Exception as exc:  # converter missing, unreadable file: report and go on
                print(f"| {sample.id} | {sample.format} | 건너뜀: {exc} | | | | |")
                continue
            pages = [p for p in document.pages if p.method.value == "ocr"]
            pictures = [i for i in document.images if i.decision == "ocr"]
            times = [x.elapsed_ms / 1000 for x in (*pages, *pictures) if x.elapsed_ms is not None]
            confidences = [x.confidence for x in (*pages, *pictures) if x.confidence is not None]
            text = "\n".join(b.text for b in document.blocks if b.ocr)
            rate = cer(sample.ocr_truth, text)
            timings += times
            rates.append(rate)
            shown = ", ".join(f"{t:.1f}" for t in times) or "-"
            low = f"{min(confidences):.0%}" if confidences else "-"
            print(
                f"| {sample.id} | {document.format} | {len(pages)} | {len(pictures)} | {shown} "
                f"| {low} | {rate:.1%} |"
            )
    print()
    print(f"- 엔진 준비 {load_s:.1f}초, 첫 읽기({samples[0].id}) {first_s:.1f}초")
    if timings:
        print(
            f"- 쪽·그림당 중앙값 {statistics.median(timings):.1f}초, "
            f"최소 {min(timings):.1f}초, 최대 {max(timings):.1f}초 ({len(timings)}개)"
        )
    if rates:
        print(f"- 글자 오류율 평균 {statistics.mean(rates):.1%}, 최대 {max(rates):.1%}")
    print(f"- 최대 메모리: 이 프로세스 {_mb(peak.own)}, 자식 프로세스 {_mb(peak.children)}")


if __name__ == "__main__":
    main()
