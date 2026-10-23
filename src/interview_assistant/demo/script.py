"""What the simulated candidate says: the scripted answer for a question from the demo dataset.

Preset questions and the dataset's own follow-ups have a written answer. Anything else (a typed
question, an AI follow-up) gets the next answer from the posting's generic pool, in turn.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from interview_assistant.demo import mock_data


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.?!])\s+", text) if s.strip()]


class DemoScript:
    def __init__(self, data: dict[str, Any] | None = None) -> None:
        data = data or mock_data()
        bank = data["answer_bank"]
        self.by_question: dict[str, str] = {}
        self.generic: dict[str, list[str]] = {}
        for posting in data["postings"]:
            for preset in posting["presets"]:
                seed = bank.get(preset["id"])
                if seed is None:
                    continue
                self.by_question[preset["question"]] = seed["answer"]
                for suggestion in seed["suggestions"]:
                    self.by_question[suggestion["question"]] = suggestion["answer"]
            pool = data["generic_bank"].get(posting["key"])
            if pool:
                self.generic[posting["id"]] = pool["answers"]
        self.fallback = [a for pool in data["generic_bank"].values() for a in pool["answers"]]
        self._turns: dict[str, int] = defaultdict(int)

    def answer_for(self, posting_id: str, question: str) -> str:
        if question in self.by_question:
            return self.by_question[question]
        pool = self.generic.get(posting_id) or self.fallback
        n = self._turns[posting_id]
        self._turns[posting_id] += 1
        return pool[n % len(pool)]
