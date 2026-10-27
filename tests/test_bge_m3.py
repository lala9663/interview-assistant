"""BGE-M3 on this machine: sparse weights on technical terms, retrieval of the evaluation set, the
duplicate threshold, and loading beside faster-whisper in one process.

Skipped unless onnxruntime/tokenizers and the model files are here (`uv sync --extra embedding`,
관리자 > 모델 설정 > 임베딩 > 다운로드). No network.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
import yaml

from interview_assistant.providers.weights import BGE_M3, WHISPER, is_complete
from interview_assistant.retrieval.index import Doc, MemoryIndex
from interview_assistant.retrieval.vectors import cosine

from .conftest import ROOT

WEIGHTS = Path(os.environ.get("IA_WEIGHTS_DIR") or ROOT / "weights")

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("onnxruntime") is None or not is_complete(BGE_M3["bge-m3"], WEIGHTS),
    reason="onnxruntime or the BGE-M3 model files are missing",
)


@pytest.fixture(scope="module")
def bge():
    from interview_assistant.providers.embedding.bge_m3 import BgeM3Embedding

    provider = BgeM3Embedding(weights_dir=WEIGHTS)
    asyncio.run(provider.warm_up())
    return provider


def encode(provider, texts):
    return asyncio.run(provider.encode(texts))


def test_dense_and_sparse_outputs(bge):
    [e] = encode(bge, ["FDC 데이터에서 RF 시간과 CVD 두께 산포를 봤습니다."])
    assert len(e.dense) == 1024 and abs(sum(x * x for x in e.dense) - 1) < 1e-4
    tokens = {bge._engine.tokenizer.id_to_token(t): w for t, w in e.sparse.items()}
    for term in ("DC", "▁RF", "▁CV"):  # FDC is "▁F" + "DC", CVD "▁CV" + "D" in this vocabulary
        assert tokens.get(term, 0) > 0.1, (term, tokens)
    assert not {"<s>", "</s>", "<pad>"} & set(tokens)
    assert bge.index_key == "BAAI/bge-m3@5617a9f/1024"


def _eval():
    from interview_assistant.demo import mock_data

    docs = []
    for item in mock_data()["question_bank"]:
        if item["status"] == "approved":
            meta = {"job_family": item["job_family"]}
            docs.append(Doc("question", item["key"], 0, item["question"], meta))
            docs += [Doc("question", item["key"], i, f, meta) for i, f in enumerate(item["follow_ups"], 1)]
    pairs = yaml.safe_load((ROOT / "tests/fixtures/retrieval_eval.yaml").read_text(encoding="utf-8"))["pairs"]
    return docs, pairs


def _rank(hits, expected):
    seen = list(dict.fromkeys(h.doc.owner_id for h in hits))
    return next((i for i, key in enumerate(seen, 1) if key in expected), None)


def test_technical_terms_and_korean_answers_find_their_questions(bge):
    docs, pairs = _eval()
    index = MemoryIndex()
    index.put(list(zip(docs, encode(bge, [d.text for d in docs]), strict=True)))
    queries = encode(bge, [p["answer"] for p in pairs])
    ranks = {"hybrid": [], "dense": []}
    for pair, query in zip(pairs, queries, strict=True):
        for mode, weight in (("hybrid", bge.sparse_weight), ("dense", 0.0)):
            hits = index.search(query, owner_type="question", where={"job_family": pair["family"]}, k=40, sparse_weight=weight)
            ranks[mode].append((pair["kind"], _rank(hits, set(pair["expected"]))))

    def hit(mode, k, kinds=("term", "paraphrase", "mixed")):
        chosen = [r for kind, r in ranks[mode] if kind in kinds]
        return sum(1 for r in chosen if r is not None and r <= k) / len(chosen)

    # Abbreviations and terms (FDC, SPC, DOE, CVD, SLO, GPU ...): always in the top 3.
    assert hit("hybrid", 3, ("term", "mixed")) == 1.0
    assert hit("hybrid", 1, ("term", "mixed")) >= hit("dense", 1, ("term", "mixed"))
    assert hit("hybrid", 3) >= 0.9  # measured 0.946 (35/37), docs/embedding-benchmark.md
    assert hit("hybrid", 1) >= hit("dense", 1)


def test_duplicate_threshold_tells_the_same_question(bge):
    same = [
        ("담당했던 공정에서 균일도에 가장 큰 영향을 준 변수는 무엇이었고, 그 이유는 무엇인가요?",
         "담당 공정에서 균일도에 가장 큰 영향을 준 장비 변수는 무엇이었고, 왜 그런가요?"),
        ("권한이 없는 다른 조직을 설득해 계획이나 일정을 바꾼 경험을 말씀해 주세요.", "권한 없이 다른 조직의 계획을 바꾼 경험이 있나요?"),
        ("원인을 어떻게 좁혀 갔고, 다른 가설은 어떻게 배제했나요?", "다른 가능성은 어떻게 배제하고 원인을 좁혔나요?"),
    ]
    different = [
        ("FDC 데이터에서 이상 징후를 찾을 때 어떤 변수부터 보나요?", "SPC 관리도에서 이상 구간을 판단하는 기준은 무엇인가요?"),
        ("맡은 범위 밖의 문제를 스스로 정의해 해결을 이끈 경험이 있나요?", "본인 판단으로 생긴 문제를 수습한 경험을 말씀해 주세요."),
        ("엣지 링 교체 주기를 RF 시간 기준으로 바꿀 때 생산성 손실과 수율 개선 효과를 어떻게 비교해 판단했나요?",
         "엣지 링 마모가 플라즈마 쉬스를 휘게 만드는 원리를 조금 더 구체적으로 설명해 주실 수 있나요?"),
    ]
    for pairs, is_same in ((same, True), (different, False)):
        vectors = encode(bge, [t for p in pairs for t in p])
        for i in range(0, len(vectors), 2):
            score = cosine(vectors[i].dense, vectors[i + 1].dense)
            assert (score >= bge.duplicate_threshold) is is_same, (pairs[i // 2], score)


@pytest.mark.skipif(
    importlib.util.find_spec("faster_whisper") is None or not is_complete(WHISPER["small"], WEIGHTS),
    reason="faster-whisper small is not downloaded",
)
@pytest.mark.parametrize("order", ["bge-first", "whisper-first"])
def test_loads_beside_faster_whisper_in_one_process(order):
    """ONNX Runtime ships no Intel OpenMP (the DLL that broke CTranslate2 next to Paddle)."""
    script = textwrap.dedent(
        f"""
        import asyncio, json
        from pathlib import Path
        from interview_assistant.providers.audio import SAMPLE
        from interview_assistant.providers.embedding.bge_m3 import BgeM3Embedding
        from interview_assistant.providers.stt.faster_whisper import FasterWhisperSTT
        weights = Path({str(WEIGHTS)!r})
        bge = BgeM3Embedding(weights_dir=weights)
        stt = FasterWhisperSTT(model="small", weights_dir=weights, beam_size=1)
        steps = [bge.warm_up, stt.warm_up] if {order!r} == "bge-first" else [stt.warm_up, bge.warm_up]
        for step in steps:
            asyncio.run(step())
        text = " ".join(s.text for s in asyncio.run(stt.transcribe(SAMPLE.as_uri())))
        [vector] = asyncio.run(bge.embed(["전사와 임베딩을 한 프로세스에서"]))
        print(json.dumps({{"text": text, "dims": len(vector)}}))
        """
    )
    done = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, timeout=600, cwd=ROOT,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    out = done.stdout.decode("utf-8", "replace").strip().splitlines()
    assert done.returncode == 0 and out, done.stderr.decode("utf-8", "replace")[-3000:]
    result = json.loads(out[-1])
    assert result["text"].strip() and result["dims"] == 1024
