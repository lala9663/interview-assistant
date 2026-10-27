"""Local BGE-M3 embeddings on CPU (ONNX Runtime, MIT; model BAAI/bge-m3, MIT). Text never leaves
the machine.

The official ONNX export gives two outputs per batch: `sentence_embedding`, the normalised [CLS]
vector (dense, 1024), and `token_embeddings`, the last hidden states. BGE-M3's sparse (lexical)
weights are its sparse head on those states, relu(h · w + b) per token, kept at the highest weight
per token id and without the special tokens, the way FlagEmbedding computes them. Two texts' lexical
score is the sum of weight products over the tokens they share. The head is 1024 float16 weights and
a bias in `sparse_linear.pt`; they are read straight from the archive's storages, so neither torch
nor the pickle inside is needed.

ONNX Runtime and tokenizers are the ones faster-whisper already loads (Silero VAD), so BGE-M3 runs
in the server process: onnxruntime ships no Intel OpenMP, unlike Paddle, and loads beside
CTranslate2 in either order (tests/test_engines_together.py). Weights come from the admin screen's
download (providers/weights.py); nothing is fetched at run time.

Loaded models are shared by every provider instance with the same weights and threads, so changing
a retrieval option on the admin screen (a threshold) does not load 2.3 GB again. One batch runs at a
time; long reindex jobs use small batches so a live query waits at most one of them.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import threading
import weakref
import zipfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from interview_assistant.providers.base import Embedding, EmbeddingProvider, ProviderUnavailable
from interview_assistant.providers.weights import BGE_M3, is_complete

DIMENSIONS = 1024
BATCH = 8
_PAD, _EOS = 1, 2
_SPECIAL = frozenset({0, 1, 2, 3})  # <s> <pad> </s> <unk>: no lexical meaning


def auto_threads() -> int:
    """More threads are slower on this laptop's hybrid CPU (the efficiency cores hold every step
    back): 6 measured best, 12 and 16 slower (docs/embedding-benchmark.md)."""
    return max(2, min(6, (os.cpu_count() or 8) // 2))


def read_sparse_head(path: Path) -> tuple[Any, float]:
    """The sparse head (a 1024 -> 1 linear layer) of `sparse_linear.pt`, a PyTorch zip archive whose
    two storages are float16. Only the raw storages are read; the archive's pickle is never loaded."""
    import numpy as np

    with zipfile.ZipFile(path) as archive:
        inside = {name.split("/", 1)[1]: name for name in archive.namelist() if "/" in name}
        if archive.read(inside["byteorder"]).strip() != b"little":
            raise ValueError("sparse_linear.pt: unexpected byte order")
        weight = np.frombuffer(archive.read(inside["data/0"]), dtype="<f2").astype(np.float32)
        bias = np.frombuffer(archive.read(inside["data/1"]), dtype="<f2").astype(np.float32)
    if weight.shape != (DIMENSIONS,) or bias.shape != (1,):
        raise ValueError("sparse_linear.pt: unexpected tensor sizes")
    return weight, float(bias[0])


class _Engine:
    """The ONNX session, tokenizer and sparse head of one weights folder."""

    def __init__(self, folder: Path, threads: int) -> None:
        import onnxruntime as ort
        from tokenizers import Tokenizer

        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        # Input shapes vary with every batch; without the arena memory goes back after each one.
        options.enable_cpu_mem_arena = False
        self.session = ort.InferenceSession(
            str(folder / "onnx" / "model.onnx"), options, providers=["CPUExecutionProvider"]
        )
        self.tokenizer = Tokenizer.from_file(str(folder / "onnx" / "tokenizer.json"))
        self.tokenizer.no_padding()
        self.tokenizer.no_truncation()
        self.weight, self.bias = read_sparse_head(folder / "sparse_linear.pt")
        self.lock = threading.Lock()

    def encode(self, texts: Sequence[str], max_length: int) -> list[Embedding]:
        import numpy as np

        ids = [e.ids for e in self.tokenizer.encode_batch(list(texts))]
        ids = [seq if len(seq) <= max_length else [*seq[: max_length - 1], _EOS] for seq in ids]
        out: list[Embedding | None] = [None] * len(ids)
        order = sorted(range(len(ids)), key=lambda i: len(ids[i]))
        for start in range(0, len(order), BATCH):
            batch = order[start : start + BATCH]
            width = max(len(ids[i]) for i in batch)
            input_ids = np.full((len(batch), width), _PAD, dtype=np.int64)
            mask = np.zeros((len(batch), width), dtype=np.int64)
            for row, i in enumerate(batch):
                input_ids[row, : len(ids[i])] = ids[i]
                mask[row, : len(ids[i])] = 1
            with self.lock:
                dense, tokens = self.session.run(
                    ["sentence_embedding", "token_embeddings"],
                    {"input_ids": input_ids, "attention_mask": mask},
                )
            weights = np.maximum(tokens @ self.weight + self.bias, 0.0)
            norms = np.linalg.norm(dense, axis=1, keepdims=True)
            dense = dense / np.where(norms == 0, 1.0, norms)
            for row, i in enumerate(batch):
                sparse: dict[int, float] = {}
                for token, w in zip(ids[i], weights[row, : len(ids[i])].tolist(), strict=True):
                    if token in _SPECIAL or w <= 0:
                        continue
                    if w > sparse.get(token, 0.0):
                        sparse[token] = w
                out[i] = Embedding(
                    dense[row].tolist(), {t: round(w, 5) for t, w in sparse.items()}
                )
        return [e for e in out if e is not None]


_ENGINES: weakref.WeakValueDictionary[tuple[str, int], _Engine] = weakref.WeakValueDictionary()
_ENGINES_LOCK = threading.Lock()


class BgeM3Embedding(EmbeddingProvider):
    context_keys = ("weights_dir",)

    def __init__(
        self,
        model: str = "bge-m3",
        max_length: int = 512,
        cpu_threads: int = 0,
        sparse_weight: float = 0.3,
        duplicate_threshold: float = 0.85,
        min_score: float = 0.55,
        weights_dir: str | Path = "weights",
        **_: Any,
    ) -> None:
        if model not in BGE_M3:
            raise ValueError(f"unknown BGE-M3 model '{model}' (known: {', '.join(BGE_M3)})")
        self.weights = BGE_M3[model]
        self.weights_dir = Path(weights_dir)
        self.model = "BAAI/bge-m3"
        self.dimensions = DIMENSIONS
        self.max_length = max_length
        self.threads = cpu_threads or auto_threads()
        self.sparse_weight = sparse_weight
        self.duplicate_threshold = duplicate_threshold
        self.min_score = min_score
        self._engine: _Engine | None = None

    @property
    def index_key(self) -> str:
        return f"{self.model}@{self.weights.revision[:7]}/{DIMENSIONS}"

    def _load(self) -> _Engine:
        if self._engine is not None:
            return self._engine
        if not is_complete(self.weights, self.weights_dir):
            raise ProviderUnavailable(
                "BGE-M3 모델 파일이 없습니다. 관리자 > 모델 설정 > 임베딩에서 내려받으세요."
            )
        for package in ("onnxruntime", "tokenizers"):
            if importlib.util.find_spec(package) is None:
                raise ProviderUnavailable(
                    f"{package}가 설치되어 있지 않습니다 (uv sync --extra embedding)."
                )
        folder = self.weights.path(self.weights_dir)
        key = (str(folder.resolve()), self.threads)
        with _ENGINES_LOCK:
            engine = _ENGINES.get(key)
            if engine is None:
                engine = _Engine(folder, self.threads)
                _ENGINES[key] = engine
        self._engine = engine
        return engine

    async def warm_up(self) -> None:
        await asyncio.to_thread(self._load)

    async def encode(self, texts: Sequence[str]) -> list[Embedding]:
        if not texts:
            return []
        engine = await asyncio.to_thread(self._load)
        return await asyncio.to_thread(engine.encode, list(texts), self.max_length)

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [e.dense for e in await self.encode(texts)]
