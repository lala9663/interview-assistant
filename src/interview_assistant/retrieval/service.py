"""Retrieval for the app: keeps the vectors of approved company text in step with the database and
with the embedding model the admin chose, and answers searches.

One index serves searches at a time: the newest ready `embedding_indexes` row, loaded into memory.
When the admin applies an embedding model with another `index_key`, a background job embeds every
document with the new model, writing progress as it goes; searches keep using the old index (and
the provider that made it) until the job is done, then switch in one assignment and the old
vectors are deleted. A failed job leaves the old index serving. Options that do not change the
vectors (thresholds) just replace the serving provider.

Edits to the bank, rubric anchors or competency dictionaries call `refresh()`: missing or stale
vectors (hash of the text and its filter fields) are embedded with the serving model and vectors of items no longer approved are
dropped. Searches check approval again in the database, so a question retired a moment ago is
never suggested even before the index catches up.

Queries are embedded with the serving index's provider, not an interview session's pinned one:
vectors of different models cannot be compared. Candidate text is embedded only by callers that
ran the guard first (ai/followups.py), and nothing a query embeds is stored.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict
from collections.abc import Callable, Coroutine, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from interview_assistant.ai_models import store
from interview_assistant.ai_models.manager import ModelManager, Unavailable
from interview_assistant.config import ProviderSpec
from interview_assistant.models import (
    ActorType,
    AuditLog,
    EmbeddingIndex,
    EmbeddingVector,
    IndexStatus,
)
from interview_assistant.models.base import utcnow
from interview_assistant.providers import registry
from interview_assistant.providers.base import Embedding
from interview_assistant.retrieval.documents import documents
from interview_assistant.retrieval.index import Doc, Hit, Key, MemoryIndex, doc_hash
from interview_assistant.retrieval.vectors import pack, sparse_from_json, sparse_to_json, unpack

log = logging.getLogger(__name__)

CHUNK = 16  # documents per embedding call and per progress commit
CACHE = 4096  # query embeddings kept (asked questions are embedded again and again)
RETRIES = 5  # when SQLite is busy with another writer

Spawn = Callable[[Coroutine[Any, Any, Any]], "asyncio.Task[Any]"]


@dataclass
class Served:
    key: str
    provider: Any
    index: MemoryIndex
    built_at: Any = None


@dataclass(frozen=True)
class IndexState:
    key: str
    model: str
    dimensions: int
    status: str
    total: int
    done: int
    started_at: Any
    finished_at: Any
    error: str | None


class Retrieval:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        models: ModelManager,
        spawn: Spawn,
    ) -> None:
        self.session_factory = session_factory
        self.models = models
        self.spawn = spawn
        self.serving: Served | None = None
        self._job: asyncio.Task[Any] | None = None
        self._job_key: str | None = None
        self._lock = asyncio.Lock()  # one writer of the serving index at a time
        self._cache: OrderedDict[tuple[str, str], Embedding] = OrderedDict()
        self._running: dict[tuple[str, str], asyncio.Future[dict[str, Embedding]]] = {}
        self._pending: asyncio.Task[Any] | None = None
        self._again = False

    # --- startup and model changes ----------------------------------------------------------

    def start(self) -> None:
        """Load the newest ready index (no model call), then bring it up to date in the
        background. Safe on an unmigrated database: retrieval just stays off."""
        try:
            self.serving = self._load_ready()
        except Exception:
            log.exception("could not load the embedding index")
            self.serving = None
        self.models.listeners.append(self._on_model_change)
        self.changed()

    def _on_model_change(self, role: str) -> None:
        if role == "embedding":
            self.changed()

    def active_provider(self) -> Any | None:
        """The embedding role's provider now, or None when it could not be built."""
        provider = self.models.active.get("embedding")
        return None if isinstance(provider, Unavailable) else provider

    def _load_ready(self) -> Served | None:
        with self.session_factory() as db:
            row = db.scalars(
                select(EmbeddingIndex)
                .where(EmbeddingIndex.status == IndexStatus.ready)
                .order_by(EmbeddingIndex.finished_at.desc())
            ).first()
            if row is None:
                return None
            active = self.active_provider()
            if active is not None and active.index_key == row.index_key:
                provider = active
            else:
                spec = store.spec_from(row.spec)
                try:
                    provider = registry.resolve("embedding", spec, self.models.context)
                except Exception:
                    log.exception("cannot rebuild the provider of index %s", row.index_key)
                    return None
            index = self._read(db, row.index_key)
            return Served(row.index_key, provider, index, row.finished_at)

    def _read(self, db: Session, key: str) -> MemoryIndex:
        """The stored vectors of `key` that still match an approved document's current text."""
        docs = {d.key: d for d in documents(db)}
        index = MemoryIndex()
        items = []
        for row in db.scalars(select(EmbeddingVector).where(EmbeddingVector.index_key == key)):
            doc = docs.get((row.owner_type, row.owner_id, row.part))
            if doc is not None and row.text_hash == doc_hash(doc):
                items.append((doc, Embedding(unpack(row.dense).tolist(), sparse_from_json(row.sparse))))
        index.put(items)
        return index

    def changed(self) -> None:
        """Something indexed changed (or the model did): catch up in the background."""
        self._again = True
        if self._pending is None or self._pending.done():
            self._pending = self.spawn(self._catch_up())

    async def _catch_up(self) -> None:
        attempts = 0
        while self._again:
            self._again = False
            try:
                await self.refresh()
                attempts = 0
            except OperationalError:  # SQLite busy with another writer: try again shortly
                attempts += 1
                if attempts > RETRIES:
                    log.exception("embedding index refresh failed")
                    continue
                self._again = True
                await asyncio.sleep(attempts)
            except Exception:
                log.exception("embedding index refresh failed")

    async def refresh(self) -> None:
        """Bring searching up to date now: the serving index if the active model made it, else
        start (or keep) the job that builds the active model's index."""
        active = self.active_provider()
        if active is None:
            return
        served = self.serving
        if served is not None and served.key == active.index_key:
            served.provider = active  # thresholds and weights may have changed, vectors did not
            await self._sync(served)
            return
        if self._job is not None and not self._job.done():
            if self._job_key == active.index_key:
                return
            self._job.cancel()
        self._job_key = active.index_key
        self._announce(active)
        self._job = self.spawn(self._build(active))

    def _announce(self, provider: Any) -> None:
        """Record the build as started right away, so the admin screen shows it from the response
        that started it (the job itself runs a moment later)."""
        try:
            with self.session_factory() as db:
                row = db.get(EmbeddingIndex, provider.index_key)
                if row is None:
                    spec = self.models.active.specs.get("embedding")
                    row = EmbeddingIndex(
                        index_key=provider.index_key,
                        model=provider.model,
                        dimensions=provider.dimensions,
                        spec=store.spec_json(spec) if spec is not None else {"impl": "?", "options": {}},
                    )
                    db.add(row)
                row.status, row.error, row.started_at, row.finished_at = IndexStatus.building, None, utcnow(), None
                row.total, row.done = len(documents(db)), 0
                db.commit()
        except Exception:
            log.exception("could not record the start of the index build")

    def rebuild(self) -> None:
        """Start building the active model's index again (after a failure, or on request)."""
        active = self.active_provider()
        if active is None:
            return
        if self._job is not None and not self._job.done():
            return
        self._job_key = active.index_key
        self._announce(active)
        self._job = self.spawn(self._build(active, fresh=True))

    async def wait(self) -> None:
        """Until pending refreshes and a running build are done (tests, scripts)."""
        for _ in range(100):
            tasks = [t for t in (self._pending, self._job) if t is not None and not t.done()]
            if not tasks:
                return
            await asyncio.gather(*tasks, return_exceptions=True)

    # --- keeping vectors in step --------------------------------------------------------------

    def _todo(self, db: Session, key: str) -> tuple[list[Doc], list[Key], int]:
        docs = documents(db)
        stored = {
            (r.owner_type, r.owner_id, r.part): r.text_hash
            for r in db.execute(
                select(
                    EmbeddingVector.owner_type,
                    EmbeddingVector.owner_id,
                    EmbeddingVector.part,
                    EmbeddingVector.text_hash,
                ).where(EmbeddingVector.index_key == key)
            )
        }
        wanted = {d.key for d in docs}
        todo = [d for d in docs if stored.get(d.key) != doc_hash(d)]
        stale = [k for k in stored if k not in wanted]
        return todo, stale, len(docs)

    def _write(self, db: Session, key: str, items: Sequence[tuple[Doc, Embedding]]) -> None:
        for doc, emb in items:
            db.execute(
                delete(EmbeddingVector).where(
                    EmbeddingVector.index_key == key,
                    EmbeddingVector.owner_type == doc.owner_type,
                    EmbeddingVector.owner_id == doc.owner_id,
                    EmbeddingVector.part == doc.part,
                )
            )
            db.add(
                EmbeddingVector(
                    index_key=key,
                    owner_type=doc.owner_type,
                    owner_id=doc.owner_id,
                    part=doc.part,
                    text_hash=doc_hash(doc),
                    dimensions=len(emb.dense),
                    dense=pack(emb.dense),
                    sparse=sparse_to_json(emb.sparse),
                )
            )

    def _forget(self, db: Session, key: str, keys: Sequence[Key]) -> None:
        for owner_type, owner_id, part in keys:
            db.execute(
                delete(EmbeddingVector).where(
                    EmbeddingVector.index_key == key,
                    EmbeddingVector.owner_type == owner_type,
                    EmbeddingVector.owner_id == owner_id,
                    EmbeddingVector.part == part,
                )
            )

    async def _sync(self, served: Served) -> None:
        async with self._lock:
            with self.session_factory() as db:
                todo, stale, _ = self._todo(db, served.key)
                if stale:
                    self._forget(db, served.key, stale)
                    db.commit()
            served.index.drop(stale)
            for start in range(0, len(todo), CHUNK):
                chunk = todo[start : start + CHUNK]
                embeddings = await served.provider.encode([d.text for d in chunk])
                items = list(zip(chunk, embeddings, strict=True))
                with self.session_factory() as db:
                    self._write(db, served.key, items)
                    db.commit()
                served.index.put(items)
            if todo or stale:
                self._audit(
                    "embedding.index_synced",
                    served.key,
                    model=served.provider.model,
                    added=len(todo),
                    removed=len(stale),
                )

    async def _build(self, provider: Any, *, fresh: bool = False) -> None:
        """Embed every document with `provider`, then serve its index. A busy database (another
        writer holds SQLite) is retried; any other failure leaves the serving index as it was."""
        for attempt in range(RETRIES + 1):
            try:
                await self._build_once(provider, fresh=fresh and attempt == 0)
                return
            except OperationalError as exc:
                if attempt == RETRIES:
                    log.exception('building the embedding index %s failed', provider.index_key)
                    self._fail(provider.index_key, str(exc).strip()[:200])
                    return
                await asyncio.sleep(1 + attempt)

    async def _build_once(self, provider: Any, *, fresh: bool) -> None:
        key = provider.index_key
        started = time.perf_counter()
        spec = self.models.active.specs.get("embedding")
        with self.session_factory() as db:
            row = db.get(EmbeddingIndex, key)
            if row is None:
                row = EmbeddingIndex(index_key=key, model=provider.model, dimensions=provider.dimensions)
                db.add(row)
            if fresh:
                db.execute(delete(EmbeddingVector).where(EmbeddingVector.index_key == key))
            row.spec = store.spec_json(spec) if spec is not None else {"impl": "?", "options": {}}
            row.status, row.error, row.started_at, row.finished_at = IndexStatus.building, None, utcnow(), None
            row.total = row.done = 0
            db.commit()
        try:
            await provider.warm_up()
            while True:
                with self.session_factory() as db:
                    todo, stale, total = self._todo(db, key)
                    self._forget(db, key, stale)
                    row = db.get(EmbeddingIndex, key)
                    assert row is not None
                    row.total, row.done = total, total - len(todo)
                    db.commit()
                if not todo:
                    break
                for start in range(0, len(todo), CHUNK):
                    chunk = todo[start : start + CHUNK]
                    embeddings = await provider.encode([d.text for d in chunk])
                    with self.session_factory() as db:
                        self._write(db, key, list(zip(chunk, embeddings, strict=True)))
                        row = db.get(EmbeddingIndex, key)
                        assert row is not None
                        row.done = min(row.total, row.done + len(chunk))
                        db.commit()
            async with self._lock:
                with self.session_factory() as db:
                    index = self._read(db, key)
                    row = db.get(EmbeddingIndex, key)
                    assert row is not None
                    row.status, row.finished_at = IndexStatus.ready, utcnow()
                    row.done = row.total
                    docs = row.total
                    finished = row.finished_at
                    # The old model's vectors go once the new ones serve.
                    db.execute(delete(EmbeddingVector).where(EmbeddingVector.index_key != key))
                    db.execute(delete(EmbeddingIndex).where(EmbeddingIndex.index_key != key))
                    db.commit()
                self.serving = Served(key, provider, index, finished)
                self._cache.clear()
            self._audit(
                "embedding.index_built",
                key,
                model=provider.model,
                documents=docs,
                seconds=round(time.perf_counter() - started, 1),
            )
        except asyncio.CancelledError:
            self._fail(key, "다른 모델로 바뀌어 중단했습니다.")
            raise
        except OperationalError:
            raise
        except Exception as exc:
            log.exception("building the embedding index %s failed", key)
            self._fail(key, str(exc).strip() or type(exc).__name__)
            self._audit("embedding.index_failed", key, model=provider.model, error=type(exc).__name__)

    def _fail(self, key: str, error: str) -> None:
        try:
            with self.session_factory() as db:
                row = db.get(EmbeddingIndex, key)
                if row is not None:
                    row.status, row.error, row.finished_at = IndexStatus.failed, error[:500], utcnow()
                    db.commit()
        except Exception:
            log.exception("could not record the failed index %s", key)

    def _audit(self, action: str, key: str, **details: Any) -> None:
        with self.session_factory() as db:
            db.add(
                AuditLog(
                    actor_type=ActorType.system,
                    action=action,
                    target_type="embedding_index",
                    target_id=key,
                    model=details.get("model"),
                    details=details,
                )
            )
            db.commit()

    # --- state for the admin screen -----------------------------------------------------------

    def states(self) -> list[IndexState]:
        with self.session_factory() as db:
            rows = db.scalars(select(EmbeddingIndex).order_by(EmbeddingIndex.started_at.desc())).all()
            return [
                IndexState(
                    r.index_key,
                    r.model,
                    r.dimensions,
                    r.status.value,
                    r.total,
                    r.done,
                    r.started_at,
                    r.finished_at,
                    r.error,
                )
                for r in rows
            ]

    # --- searching ----------------------------------------------------------------------------

    @property
    def provider(self) -> Any | None:
        return self.serving.provider if self.serving is not None else None

    @property
    def model(self) -> str | None:
        provider = self.provider
        return str(getattr(provider, "model", "")) if provider is not None else None

    async def encode(self, texts: Sequence[str]) -> list[Embedding]:
        """Texts embedded with the serving index's model (cached by text). A text another caller
        is embedding right now (the answer prefetched while the candidate spoke) is waited for,
        not embedded a second time behind it."""
        served = self.serving
        if served is None:
            raise LookupError("no embedding index is ready")
        found: dict[str, Embedding] = {}
        waits: dict[str, asyncio.Future[dict[str, Embedding]]] = {}
        todo: list[str] = []
        for text in texts:
            key = (served.key, text)
            if text in found or text in waits or text in todo:
                continue
            hit = self._cache.get(key)
            if hit is not None:
                self._cache.move_to_end(key)
                found[text] = hit
            elif key in self._running:
                waits[text] = self._running[key]
            else:
                todo.append(text)
        if todo:
            # Not tied to this caller: if it goes away, the result still reaches the cache and
            # whoever waits for the same text.
            job = asyncio.ensure_future(self._embed(served, todo))
            for text in todo:
                waits[text] = self._running[(served.key, text)] = job
        for job in dict.fromkeys(waits.values()):
            found |= await asyncio.shield(job)
        return [found[text] for text in texts]

    async def _embed(self, served: Served, texts: list[str]) -> dict[str, Embedding]:
        try:
            fresh = await served.provider.encode(texts)
        finally:
            for text in texts:
                self._running.pop((served.key, text), None)
        for text, emb in zip(texts, fresh, strict=True):
            self._cache[(served.key, text)] = emb
        while len(self._cache) > CACHE:
            self._cache.popitem(last=False)
        return dict(zip(texts, fresh, strict=True))

    def search(
        self,
        query: Embedding,
        *,
        owner_type: str,
        where: Mapping[str, Any] | None = None,
        k: int = 5,
    ) -> list[Hit]:
        served = self.serving
        if served is None:
            return []
        weight = float(getattr(served.provider, "sparse_weight", 0.0) or 0.0)
        return served.index.search(query, owner_type=owner_type, where=where, k=k, sparse_weight=weight)

    def threshold(self, name: str, default: float) -> float:
        return float(getattr(self.provider, name, default) or default)
