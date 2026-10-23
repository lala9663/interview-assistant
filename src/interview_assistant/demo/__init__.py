"""Fictional demo dataset (the same one the frontend mock API uses) and what is built from it:
the database seed (`seed.py`) and the scripted candidate answers for the simulated microphone
(`script.py`). No real people.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any

DATA_FILE = Path(__file__).with_name("mock_data.json")


@cache
def mock_data() -> dict[str, Any]:
    """frontend/src/mocks/data as JSON (regenerate with scripts/export_mock_data.mjs)."""
    return json.loads(DATA_FILE.read_text(encoding="utf-8"))
