"""Embed the answer while the candidate is still talking (docs/audio-input.md 5장).

Follow-ups (ai/followups.py) embed the de-identified answer and the questions already asked before
they search the question bank. `Retrieval.encode` caches embeddings by text, so if the hub embeds
exactly the text the answer will be stored as while final transcript segments come in, the search
finds it in the cache the moment the answer closes. Only the latest text is embedded: a newer one
replaces a waiting one, and a call in progress is not interrupted.

Like the follow-up path, candidate text is embedded only once the guard passed it, and nothing is
stored: the cache lives in memory (bounded, emptied when the embedding model changes).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from typing import Any

from interview_assistant.ai.guard import IdentifierInPrompt, check_prompt

log = logging.getLogger(__name__)


class AnswerPrefetch:
    def __init__(self, retrieval: Any) -> None:
        self.retrieval = retrieval
        self._task: asyncio.Task[None] | None = None
        self._next: tuple[list[str], Any] | None = None
        self.embedded = 0  # texts sent for embedding (tests, measurements)

    def push(self, texts: Sequence[str], known: Any) -> None:
        """Embed `texts` (the answer so far, or questions asked) in the background."""
        texts = [t for t in texts if t]
        if self.retrieval is None or self.retrieval.serving is None or not texts:
            return
        self._next = (texts, known)
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        while self._next is not None:
            texts, known = self._next
            self._next = None
            try:
                check_prompt("", texts, known)
            except IdentifierInPrompt:
                continue
            try:
                await self.retrieval.encode(texts)
                self.embedded += len(texts)
            except Exception:
                log.exception("answer prefetch failed; follow-ups embed it themselves")

    async def wait(self) -> None:
        if self._task is not None:
            await asyncio.gather(self._task, return_exceptions=True)

    def cancel(self) -> None:
        self._next = None
        if self._task is not None and not self._task.done():
            self._task.cancel()
