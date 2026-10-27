"""Korean retrieval quality: does the question that fits an answer come up in the top 3?

The corpus is the demo question bank (approved questions and their follow-up examples, by job
family, from src/interview_assistant/demo/mock_data.json); the queries are the made-up answers of
tests/fixtures/retrieval_eval.yaml with the bank questions that should follow them. Reports hit@1,
hit@3 and MRR overall and per kind (term / paraphrase / mixed), for the hybrid score and for the
dense vector alone. No network; BGE-M3 needs its weights (관리자 > 모델 설정 > 임베딩 > 다운로드).

    uv run python scripts/eval_retrieval.py                 # BGE-M3 from weights/
    uv run python scripts/eval_retrieval.py --impl fake     # the fake embedding, for comparison
    uv run python scripts/eval_retrieval.py --json out.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from interview_assistant.config import ProviderSpec  # noqa: E402
from interview_assistant.demo import mock_data  # noqa: E402
from interview_assistant.providers import registry  # noqa: E402
from interview_assistant.retrieval.index import Doc, MemoryIndex  # noqa: E402

EVAL = ROOT / "tests" / "fixtures" / "retrieval_eval.yaml"


def corpus() -> list[Doc]:
    docs = []
    for item in mock_data()["question_bank"]:
        if item["status"] != "approved":
            continue
        meta = {"job_family": item["job_family"], "key": item["key"]}
        docs.append(Doc("question", item["key"], 0, item["question"], meta))
        for part, text in enumerate(item["follow_ups"], start=1):
            docs.append(Doc("question", item["key"], part, text, meta))
    return docs


def ranks(hits: list, expected: set[str]) -> int | None:
    """1-based rank of the first expected item, counting each bank item once."""
    seen: list[str] = []
    for hit in hits:
        if hit.doc.owner_id not in seen:
            seen.append(hit.doc.owner_id)
    for i, key in enumerate(seen, start=1):
        if key in expected:
            return i
    return None


def summary(found: list[tuple[str, int | None]]) -> dict[str, float]:
    n = len(found) or 1
    return {
        "n": len(found),
        "hit@1": round(sum(1 for _, r in found if r == 1) / n, 3),
        "hit@3": round(sum(1 for _, r in found if r is not None and r <= 3) / n, 3),
        "mrr": round(sum(1 / r for _, r in found if r) / n, 3),
    }


async def evaluate(provider, sparse_weight: float) -> dict:
    docs = corpus()
    started = time.perf_counter()
    embeddings = await provider.encode([d.text for d in docs])
    index_s = time.perf_counter() - started
    index = MemoryIndex()
    index.put(list(zip(docs, embeddings, strict=True)))
    pairs = yaml.safe_load(EVAL.read_text(encoding="utf-8"))["pairs"]
    queries = await provider.encode([p["answer"] for p in pairs])
    results: dict[str, list[tuple[str, int | None]]] = {"hybrid": [], "dense": []}
    misses: list[dict] = []
    for pair, query in zip(pairs, queries, strict=True):
        where = {"job_family": pair["family"]}
        for mode, weight in (("hybrid", sparse_weight), ("dense", 0.0)):
            hits = index.search(query, owner_type="question", where=where, k=40, sparse_weight=weight)
            rank = ranks(hits, set(pair["expected"]))
            results[mode].append((pair["kind"], rank))
            if mode == "hybrid" and (rank is None or rank > 3):
                top = []
                for h in hits:
                    if h.doc.owner_id not in top:
                        top.append(h.doc.owner_id)
                misses.append({"answer": pair["answer"][:40], "expected": pair["expected"], "top3": top[:3]})
    report = {"documents": len(docs), "queries": len(pairs), "index_seconds": round(index_s, 2)}
    for mode, found in results.items():
        report[mode] = {"all": summary(found)}
        for kind in ("term", "paraphrase", "mixed"):
            report[mode][kind] = summary([f for f in found if f[0] == kind])
    report["misses"] = misses
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--impl", default="bge_m3", choices=["bge_m3", "fake"])
    parser.add_argument("--weights", default=str(ROOT / "weights"))
    parser.add_argument("--sparse-weight", type=float, default=None)
    parser.add_argument("--json", help="write the report here as well")
    args = parser.parse_args()
    options = {"model": "bge-m3"} if args.impl == "bge_m3" else {"dimensions": 256}
    provider = registry.resolve("embedding", ProviderSpec(impl=args.impl, **options), {"weights_dir": Path(args.weights)})
    weight = args.sparse_weight if args.sparse_weight is not None else provider.sparse_weight
    report = asyncio.run(evaluate(provider, weight))
    report |= {"impl": args.impl, "model": provider.model, "sparse_weight": weight}
    text = json.dumps(report, ensure_ascii=False, indent=1)
    sys.stdout.reconfigure(encoding="utf-8")
    print(text)
    if args.json:
        Path(args.json).write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
