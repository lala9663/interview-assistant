"""BGE-M3 on this machine: load time, embedding one answer, indexing 1,000 bank questions, search
time, and memory alone and beside faster-whisper and PaddleOCR (docs/embedding-benchmark.md).

Each step runs in this process the way the server does (BGE-M3 and Whisper in the server process,
PaddleOCR in its worker process). Memory is the resident set size (psutil). No network; the model
files come from 관리자 > 모델 설정.

    uv run --with psutil python scripts/bench_embedding.py
    uv run --with psutil python scripts/bench_embedding.py --whisper medium --json bench.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import psutil  # noqa: E402

from interview_assistant.demo import mock_data  # noqa: E402
from interview_assistant.retrieval.index import Doc, MemoryIndex  # noqa: E402

ANSWER = (
    "[회사-1]에서 DRAM 커패시터 식각 공정을 맡았을 때, 특정 챔버에서만 웨이퍼 가장자리 CD가 3나노 정도 "
    "커지는 불량이 반복됐습니다. 처음에는 포토 공정 문제로 의심했는데, 같은 로트를 다른 챔버로 돌리면 "
    "정상이어서 챔버 쪽으로 범위를 좁혔습니다. FDC 데이터를 보니 엣지 링 교체 후 RF 시간이 누적될수록 "
    "산포가 커지는 패턴이 있었습니다. 엣지 링 마모로 플라즈마 쉬스가 휜다는 가설을 세우고 엣지 링 높이를 "
    "바꿔 가며 DOE로 확인했습니다. 교체 주기를 RF 시간 기준으로 바꾼 뒤 가장자리 수율이 2.1%p 올랐습니다."
)
CHUNK = 16  # documents per call, as retrieval/service.py indexes them


def rss(pid: int | None = None) -> float:
    """Resident memory of a process and its children (on Windows a venv's python.exe is a launcher
    whose child is the real interpreter)."""
    process = psutil.Process(pid)
    return sum(p.memory_info().rss for p in [process, *process.children(recursive=True)]) / 1e9


def thousand_questions() -> list[str]:
    """1,000 bank-like questions: the demo bank's questions and follow-ups with varied contexts."""
    base = []
    for item in mock_data()["question_bank"]:
        base.append(item["question"])
        base.extend(item["follow_ups"])
    contexts = ["최근 프로젝트에서", "양산 이관 때", "신규 장비 도입 때", "팀을 옮긴 뒤", "가장 어려웠던 시기에",
                "고객 요청으로", "야간 대응 중", "분기 목표 때문에", "처음 맡은 업무에서", "협력사와 함께"]
    rng = random.Random(7)
    out = []
    while len(out) < 1000:
        out.append(f"{rng.choice(contexts)} {rng.choice(base)}")
    return out


def timed(fn, repeat: int) -> list[float]:
    times = []
    for _ in range(repeat):
        started = time.perf_counter()
        fn()
        times.append(time.perf_counter() - started)
    return times


def stats(times: list[float]) -> dict[str, float]:
    ordered = sorted(times)
    return {
        "median_ms": round(statistics.median(ordered) * 1000),
        "p90_ms": round(ordered[min(len(ordered) - 1, round(0.9 * (len(ordered) - 1)))] * 1000),
        "min_ms": round(ordered[0] * 1000),
        "runs": len(ordered),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--weights", default=str(ROOT / "weights"))
    parser.add_argument("--whisper", default="medium", help="faster-whisper size loaded beside it")
    parser.add_argument("--threads", type=int, default=0, help="BGE-M3 CPU threads (0: auto)")
    parser.add_argument("--json")
    args = parser.parse_args()
    weights = Path(args.weights)
    sys.stdout.reconfigure(encoding="utf-8")
    report: dict = {"cpu_threads_logical": psutil.cpu_count(), "ram_gb": round(psutil.virtual_memory().total / 1e9, 1)}
    report["rss_start_gb"] = round(psutil.Process().memory_info().rss / 1e9, 2)

    from interview_assistant.providers.embedding.bge_m3 import BgeM3Embedding

    bge = BgeM3Embedding(weights_dir=weights, cpu_threads=args.threads)
    report["threads"] = bge.threads
    started = time.perf_counter()
    asyncio.run(bge.warm_up())
    report["load_s"] = round(time.perf_counter() - started, 2)
    report["rss_after_load_gb"] = round(rss(), 2)

    encode = lambda texts: asyncio.run(bge.encode(texts))  # noqa: E731
    tokens = len(bge._engine.tokenizer.encode(ANSWER).ids)  # noqa: SLF001
    encode([ANSWER])  # first call warms the kernels
    report["answer_tokens"] = tokens
    report["answer"] = stats(timed(lambda: encode([ANSWER]), 10))
    report["short_question"] = stats(timed(lambda: encode(["FDC 데이터에서 이상 징후를 찾을 때 어떤 변수부터 보나요?"]), 10))

    questions = thousand_questions()
    started = time.perf_counter()
    embeddings = []
    for i in range(0, len(questions), CHUNK):
        embeddings.extend(encode(questions[i : i + CHUNK]))
    seconds = time.perf_counter() - started
    report["index_1000"] = {"seconds": round(seconds, 1), "per_question_ms": round(seconds * 1000 / len(questions))}
    report["rss_after_index_gb"] = round(rss(), 2)

    index = MemoryIndex()
    index.put([(Doc("question", str(i), 0, q, {"job_family": "공정개발"}), e) for i, (q, e) in enumerate(zip(questions, embeddings, strict=True))])
    [query] = encode([ANSWER])
    index.search(query, owner_type="question", k=24, sparse_weight=0.3)
    report["search_1000"] = stats(timed(lambda: index.search(query, owner_type="question", where={"job_family": "공정개발"}, k=24, sparse_weight=0.3), 100))
    report["rss_bge_alone_gb"] = round(rss(), 2)

    from interview_assistant.providers.stt.faster_whisper import FasterWhisperSTT
    from interview_assistant.providers.weights import WHISPER, is_complete

    if is_complete(WHISPER[args.whisper], weights):
        stt = FasterWhisperSTT(model=args.whisper, weights_dir=weights, beam_size=1)
        asyncio.run(stt.warm_up())
        report["whisper"] = args.whisper
        report["rss_with_whisper_gb"] = round(rss(), 2)
        report["answer_with_whisper_loaded"] = stats(timed(lambda: encode([ANSWER]), 5))
    from interview_assistant.providers.ocr.paddle import PaddleOCRProvider
    from interview_assistant.providers.weights import PADDLEOCR

    if is_complete(PADDLEOCR["ppocrv5-mobile"], weights):
        from PIL import Image

        ocr = PaddleOCRProvider(weights_dir=weights)
        page = Image.open(ROOT / "src/interview_assistant/providers/samples/documents/ocr-sample.png")
        ocr.recognize(page)
        worker = ocr._worker.pid  # noqa: SLF001
        report["paddle_worker_gb"] = round(rss(worker), 2) if worker else None
        report["total_server_plus_worker_gb"] = round(rss(), 2)  # the worker is a child of this process
        ocr.close()
    report["system_available_gb"] = round(psutil.virtual_memory().available / 1e9, 1)
    text = json.dumps(report, ensure_ascii=False, indent=1)
    print(text)
    if args.json:
        Path(args.json).write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
