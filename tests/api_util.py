"""Helpers for the API tests: waiting on background work, reading SSE, walking every GET."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

LIVE = "0a1b2c3d-0000-4000-9000-live00000000"  # seeded: in progress (1차), recording consent
SCHEDULED = "0a1b2c3d-0000-4000-9000-s10000000000"  # seeded: scheduled today (1차)
COMPLETED = "0a1b2c3d-0000-4000-9000-c10000000000"  # seeded: completed, AI-scored, 1차 passed
LIVE2 = "0a1b2c3d-0000-4000-9000-live20000000"  # seeded: P1 2차 in progress (CAND-0009)
ROUND2_DONE = "0a1b2c3d-0000-4000-9000-r2n100000000"  # seeded: P1 2차 evaluated, no decision
NEXT_ROUND2 = "0a1b2c3d-0000-4000-9000-s30000000000"  # seeded: P1 2차 scheduled (CAND-0003)
EVALUATING = "0a1b2c3d-0000-4000-9000-c20000000000"  # seeded: P1 1차 ended, 김서연 to submit
P1 = "b1d6a0c2-1f3e-4b8a-9c41-5e2f7a9d0001"
P3 = "b1d6a0c2-1f3e-4b8a-9c41-5e2f7a9d0003"  # draft posting, no applications


def round_id(client, posting_id: str, position: int = 1) -> str:
    rounds = client.get(f"/api/postings/{posting_id}/rounds").json()
    return next(r["id"] for r in rounds if r["position"] == position)


def wait_for(client, path: str, predicate: Callable[[Any], bool], timeout: float = 10) -> Any:
    deadline = time.monotonic() + timeout
    while True:
        body = client.get(path).json()
        if predicate(body):
            return body
        if time.monotonic() > deadline:
            raise AssertionError(f"timed out waiting on {path}: {body}")
        time.sleep(0.02)


def sse_events(text: str) -> list[tuple[str, dict[str, Any]]]:
    events = []
    for block in text.split("\n\n"):
        name, data = None, None
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line[len("event: ") :]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: ") :])
        if name is not None:
            events.append((name, data))
    return events


def get_paths(client) -> list[str]:
    """Every GET resource of the seeded app (finite streams included)."""
    paths = ["/api/me", "/api/dashboard", "/api/activity?limit=100", "/api/postings"]
    paths += ["/api/candidates", "/api/applications/schedulable", "/api/interviewers"]
    paths += ["/api/availabilities", "/api/sessions"]
    paths += ["/api/question-bank", "/api/rubric-examples"]
    paths += ["/api/admin/embedding-index", "/api/admin/follow-up-metrics"]
    for posting in client.get("/api/postings").json():
        pid = posting["id"]
        paths += [f"/api/postings/{pid}", f"/api/postings/{pid}/competency-sets"]
        paths += [f"/api/postings/{pid}/rounds", f"/api/postings/{pid}/applications"]
        for round_ in client.get(f"/api/postings/{pid}/rounds").json():
            paths.append(f"/api/rounds/{round_['id']}/competency-sets")
            for cs in client.get(f"/api/rounds/{round_['id']}/competency-sets").json():
                paths.append(f"/api/competency-sets/{cs['id']}/preset-questions")
        for row in client.get(f"/api/postings/{pid}/applications").json():
            paths.append(f"/api/applications/{row['application_id']}")
            paths.append(f"/api/applications/{row['application_id']}/decisions")
    for session in client.get("/api/sessions").json():
        sid = session["id"]
        paths += [f"/api/sessions/{sid}", f"/api/sessions/{sid}/evaluation"]
        paths.append(f"/api/sessions/{sid}/transcript")
        if session["status"] != "in_progress":  # live streams never end on their own
            paths.append(f"/api/sessions/{sid}/transcript/stream")
    return paths


def walk_json(value: Any, path: str = "") -> list[tuple[str, Any]]:
    """(key path, value) for every leaf of a JSON document."""
    out = []
    if isinstance(value, dict):
        for k, v in value.items():
            out += walk_json(v, f"{path}.{k}")
    elif isinstance(value, list):
        for i, v in enumerate(value):
            out += walk_json(v, f"{path}[{i}]")
    else:
        out.append((path, value))
    return out


def json_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in json_keys(v)}
    if isinstance(value, list):
        return {k for v in value for k in json_keys(v)}
    return set()
