"""The background queue that applies received site events (events.apply_event).

The database is the queue: a row in `intake_events` with status queued is work to do, so nothing
is lost on a restart. In memory there is only the order of ids and `workers` tasks taking them;
each event runs as its own task so a withdrawal can cancel it without stopping its worker.
One process only (like the live transcript hub): several instances would need row claiming
(SELECT ... FOR UPDATE SKIP LOCKED on PostgreSQL) or a real queue (Cloud Tasks, Pub/Sub).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable

from interview_assistant.intake.events import IntakeContext, apply_event, resume_queue

log = logging.getLogger(__name__)


class IntakeQueue:
    def __init__(self, ctx: IntakeContext, workers: int) -> None:
        self.ctx = ctx
        self.workers = workers
        self._queue: asyncio.Queue[str] | None = None
        self._waiting: set[str] = set()
        self._running: dict[str, asyncio.Task[None]] = {}
        self._withdrawn: set[str] = set()
        self._tasks: list[asyncio.Task[None]] = []

    def start(self) -> list[asyncio.Task[None]]:
        """Inside the event loop: queue what the database still holds, start the workers."""
        self._queue = asyncio.Queue()
        with self.ctx.session_factory() as db:
            pending = resume_queue(db)
        for row_id in pending:
            self.enqueue(row_id)
        if pending:
            log.info("intake: resuming %d queued events", len(pending))
        self._tasks = [asyncio.create_task(self._work()) for _ in range(self.workers)]
        return self._tasks

    @property
    def size(self) -> int:
        return len(self._waiting) + len(self._running)

    def enqueue(self, row_id: str) -> None:
        if self._queue is None or row_id in self._waiting or row_id in self._running:
            return
        self._waiting.add(row_id)
        self._queue.put_nowait(row_id)

    def cancel(self, row_ids: Iterable[str]) -> None:
        """A withdrawal arrived for events being applied: stop them (they end skipped)."""
        for row_id in row_ids:
            task = self._running.get(row_id)
            if task is not None and not task.done():
                self._withdrawn.add(row_id)
                task.cancel()

    def _was_withdrawn(self, row_id: str) -> bool:
        return row_id in self._withdrawn

    async def _work(self) -> None:
        assert self._queue is not None
        while True:
            row_id = await self._queue.get()
            self._waiting.discard(row_id)
            task = asyncio.create_task(apply_event(self.ctx, row_id, withdrawn=self._was_withdrawn))
            self._running[row_id] = task
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                current = asyncio.current_task()
                if current is not None and current.cancelling():
                    task.cancel()  # shutting down: the event stays processing, resumed at start
                    await asyncio.wait({task})
                    raise
            except Exception:  # apply_event handles its own failures; this is a last resort
                log.exception("intake worker: event %s", row_id)
            finally:
                self._running.pop(row_id, None)
                self._withdrawn.discard(row_id)
                self._queue.task_done()
