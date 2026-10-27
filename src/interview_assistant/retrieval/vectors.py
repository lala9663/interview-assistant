"""Vector arithmetic and the stored form of a vector.

Dense vectors are stored as float32 little-endian bytes, sparse weights as a JSON object of token
id -> weight: both fit SQLite, PostgreSQL and MySQL alike (BLOB/bytea, JSON). A hybrid score is the
dense cosine plus `sparse_weight` times the lexical score (BGE-M3's own way of combining them).
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping, Sequence

import numpy as np


def pack(dense: Sequence[float]) -> bytes:
    return np.asarray(dense, dtype="<f4").tobytes()


def unpack(data: bytes) -> np.ndarray:
    return np.frombuffer(data, dtype="<f4").astype(np.float32)


def sparse_to_json(sparse: Mapping[int, float] | None) -> dict[str, float] | None:
    return None if sparse is None else {str(k): float(v) for k, v in sparse.items()}


def sparse_from_json(data: Mapping[str, float] | None) -> dict[int, float] | None:
    return None if data is None else {int(k): float(v) for k, v in data.items()}


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


def lexical(query: Mapping[int, float], doc: Mapping[int, float]) -> float:
    """Sum of weight products over the tokens both texts have."""
    if len(doc) < len(query):
        query, doc = doc, query
    return sum(w * doc[t] for t, w in query.items() if t in doc)


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
