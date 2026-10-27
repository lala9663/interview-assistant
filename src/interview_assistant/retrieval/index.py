"""Where vectors are searched: the `VectorIndex` interface and its in-memory implementation.

The app holds a few thousand short company texts (bank questions, rubric anchors, competency
dictionaries), so a brute-force search over a numpy matrix answers in well under a millisecond per
thousand. A database-side index (pgvector, or the chosen engine's own) can replace `MemoryIndex`
behind the same three calls once the database is decided; `where` filters map to a WHERE clause.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from interview_assistant.providers.base import Embedding
from interview_assistant.retrieval.vectors import lexical, text_hash

Key = tuple[str, str, int]  # owner type, owner id, part


@dataclass(frozen=True)
class Doc:
    """One text to embed: whose it is and the fields a search filters on."""

    owner_type: str
    owner_id: str
    part: int
    text: str
    meta: Mapping[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> Key:
        return (self.owner_type, self.owner_id, self.part)


def doc_hash(doc: Doc) -> str:
    """Changes with the text and with the fields searches filter on (an edited competency)."""
    fields = "".join(f"{k}={doc.meta[k]}" for k in sorted(doc.meta))
    return text_hash(f"{doc.text}{fields}")


@dataclass(frozen=True)
class Hit:
    doc: Doc
    score: float  # dense + sparse_weight * lexical
    dense: float
    lexical: float


def matches(meta: Mapping[str, Any], where: Mapping[str, Any] | None) -> bool:
    """`where` maps a field to a value, or to a set/list/tuple of allowed values (None allowed too)."""
    for name, wanted in (where or {}).items():
        value = meta.get(name)
        if isinstance(wanted, (set, frozenset, list, tuple)):
            if value not in wanted:
                return False
        elif value != wanted:
            return False
    return True


class VectorIndex(ABC):
    @abstractmethod
    def put(self, items: Sequence[tuple[Doc, Embedding]]) -> None:
        """Add or replace texts (by key)."""

    @abstractmethod
    def drop(self, keys: Iterable[Key]) -> None: ...

    @abstractmethod
    def search(
        self,
        query: Embedding,
        *,
        owner_type: str,
        where: Mapping[str, Any] | None = None,
        k: int = 5,
        sparse_weight: float = 0.0,
    ) -> list[Hit]: ...

    @abstractmethod
    def keys(self) -> set[Key]: ...

    @abstractmethod
    def vector(self, key: Key) -> np.ndarray | None:
        """The stored dense vector of a text (duplicate checks compare it without embedding again)."""


class _Table:
    def __init__(self) -> None:
        self.docs: list[Doc] = []
        self.dense: list[np.ndarray] = []
        self.sparse: list[dict[int, float] | None] = []
        self.position: dict[Key, int] = {}
        self._matrix: np.ndarray | None = None

    def matrix(self) -> np.ndarray:
        if self._matrix is None:
            self._matrix = np.vstack(self.dense) if self.dense else np.zeros((0, 0), np.float32)
        return self._matrix

    def put(self, doc: Doc, embedding: Embedding) -> None:
        vector = np.asarray(embedding.dense, dtype=np.float32)
        at = self.position.get(doc.key)
        if at is None:
            self.position[doc.key] = len(self.docs)
            self.docs.append(doc)
            self.dense.append(vector)
            self.sparse.append(embedding.sparse)
        else:
            self.docs[at], self.dense[at], self.sparse[at] = doc, vector, embedding.sparse
        self._matrix = None

    def drop(self, keys: set[Key]) -> None:
        keep = [i for i, d in enumerate(self.docs) if d.key not in keys]
        if len(keep) == len(self.docs):
            return
        self.docs = [self.docs[i] for i in keep]
        self.dense = [self.dense[i] for i in keep]
        self.sparse = [self.sparse[i] for i in keep]
        self.position = {d.key: i for i, d in enumerate(self.docs)}
        self._matrix = None


class MemoryIndex(VectorIndex):
    def __init__(self) -> None:
        self._tables: dict[str, _Table] = {}

    def __len__(self) -> int:
        return sum(len(t.docs) for t in self._tables.values())

    def count(self, owner_type: str) -> int:
        table = self._tables.get(owner_type)
        return len(table.docs) if table else 0

    def keys(self) -> set[Key]:
        return {d.key for t in self._tables.values() for d in t.docs}

    def vector(self, key: Key) -> np.ndarray | None:
        table = self._tables.get(key[0])
        at = table.position.get(key) if table else None
        return table.dense[at] if table is not None and at is not None else None

    def put(self, items: Sequence[tuple[Doc, Embedding]]) -> None:
        for doc, embedding in items:
            self._tables.setdefault(doc.owner_type, _Table()).put(doc, embedding)

    def drop(self, keys: Iterable[Key]) -> None:
        wanted = set(keys)
        for table in self._tables.values():
            table.drop(wanted)

    def search(
        self,
        query: Embedding,
        *,
        owner_type: str,
        where: Mapping[str, Any] | None = None,
        k: int = 5,
        sparse_weight: float = 0.0,
    ) -> list[Hit]:
        table = self._tables.get(owner_type)
        if table is None or not table.docs:
            return []
        rows = [i for i, d in enumerate(table.docs) if matches(d.meta, where)]
        if not rows:
            return []
        q = np.asarray(query.dense, dtype=np.float32)
        dense = table.matrix()[rows] @ q
        hits = []
        for row, score in zip(rows, dense.tolist(), strict=True):
            lex = 0.0
            if sparse_weight and query.sparse and table.sparse[row]:
                lex = lexical(query.sparse, table.sparse[row] or {})
            hits.append(Hit(table.docs[row], score + sparse_weight * lex, score, lex))
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:k]
