"""Local model weights: what each downloadable model needs, whether it is on disk, and the download.

Weights are pinned to a Hugging Face commit and the large file to its sha256, so what runs is what
was reviewed. Nothing is fetched until an admin presses "다운로드" (admin > 모델 설정); checking
whether a model is present only looks at file sizes on disk, never the network. Files land in
`IA_WEIGHTS_DIR` (default `weights/`, git-ignored): `<dir>.partial/` while downloading, renamed to
`<dir>/` once every file is complete and verified. An interrupted download resumes where it
stopped. `HF_ENDPOINT` (mirror) and `HF_TOKEN` are honoured; HTTP(S)_PROXY as usual.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import threading
import time
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO, Literal

log = logging.getLogger(__name__)

MARKER = ".complete.json"
_CHUNK = 1 << 20


@dataclass(frozen=True)
class WeightFile:
    name: str
    size: int
    sha256: str | None = None  # Git LFS files carry one; small JSON/text files do not


@dataclass(frozen=True)
class WeightSet:
    key: str  # folder under the weights dir, e.g. "faster-whisper/medium"
    repo_id: str
    revision: str  # commit sha
    files: tuple[WeightFile, ...]
    license: str = "MIT"

    @property
    def size_bytes(self) -> int:
        return sum(f.size for f in self.files)

    def path(self, root: Path) -> Path:
        return Path(root) / self.key

    def url(self, name: str, endpoint: str) -> str:
        return f"{endpoint.rstrip('/')}/{self.repo_id}/resolve/{self.revision}/{name}"


def _whisper(size: str, repo_id: str, revision: str, *files: WeightFile) -> WeightSet:
    return WeightSet(f"faster-whisper/{size}", repo_id, revision, files)


# faster-whisper (CTranslate2) conversions of OpenAI Whisper, MIT. Checked 2026-10-25. v3 models
# carry 128 mel bins, hence the preprocessor config.
WHISPER: dict[str, WeightSet] = {
    "small": _whisper(
        "small",
        "Systran/faster-whisper-small",
        "536b0662742c02347bc0e980a01041f333bce120",
        WeightFile("config.json", 2370),
        WeightFile(
            "model.bin",
            483546902,
            "3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671",
        ),
        WeightFile("tokenizer.json", 2203239),
        WeightFile("vocabulary.txt", 459861),
    ),
    "medium": _whisper(
        "medium",
        "Systran/faster-whisper-medium",
        "08e178d48790749d25932bbc082711ddcfdfbc4f",
        WeightFile("config.json", 2257),
        WeightFile(
            "model.bin",
            1527906378,
            "9b45e1009dcc4ab601eff815b61d80e60ce3fd8c74c1a14f4a282258286b51ae",
        ),
        WeightFile("tokenizer.json", 2203239),
        WeightFile("vocabulary.txt", 459861),
    ),
    "large-v3": _whisper(
        "large-v3",
        "Systran/faster-whisper-large-v3",
        "edaa852ec7e145841d8ffdb056a99866b5f0a478",
        WeightFile("config.json", 2394),
        WeightFile(
            "model.bin",
            3087284237,
            "69f74147e3334731bc3a76048724833325d2ec74642fb52620eda87352e3d4f1",
        ),
        WeightFile("preprocessor_config.json", 340),
        WeightFile("tokenizer.json", 2480617),
        WeightFile("vocabulary.json", 1068114),
    ),
    # Formerly mobiuslabsgmbh/faster-whisper-large-v3-turbo (faster-whisper's "turbo" alias).
    "large-v3-turbo": _whisper(
        "large-v3-turbo",
        "dropbox-dash/faster-whisper-large-v3-turbo",
        "0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf",
        WeightFile("config.json", 2263),
        WeightFile(
            "model.bin",
            1617884929,
            "e76620f83d5f5b69efd3d87e3dc180c1bd21df9fbebacfd4335e5e1efcc018da",
        ),
        WeightFile("preprocessor_config.json", 340),
        WeightFile("tokenizer.json", 2710337),
        WeightFile("vocabulary.json", 1068114),
    ),
}


def is_complete(weights: WeightSet, root: Path) -> bool:
    """Every file present with its expected size, and the marker written after verification."""
    folder = weights.path(root)
    if not (folder / MARKER).is_file():
        return False
    for f in weights.files:
        p = folder / f.name
        if not p.is_file() or p.stat().st_size != f.size:
            return False
    return True


# --- download ---------------------------------------------------------------------------------

Status = Literal["missing", "downloading", "done", "failed", "cancelled"]
Opener = Callable[[urllib.request.Request], Any]  # urlopen-like; tests pass an in-memory one


@dataclass
class DownloadState:
    key: str
    status: Status
    total_bytes: int
    downloaded_bytes: int = 0
    error: str | None = None
    started_at: float | None = None
    finished_at: float | None = None
    cancel: threading.Event = field(default_factory=threading.Event, repr=False)
    thread: threading.Thread | None = field(default=None, repr=False)


class DownloadCancelled(Exception):
    pass


class DownloadManager:
    """Background downloads, one thread per model, progress readable at any time."""

    def __init__(
        self,
        root: Path,
        *,
        endpoint: str | None = None,
        token: str | None = None,
        opener: Opener | None = None,
    ) -> None:
        self.root = Path(root)
        self.endpoint = endpoint or os.environ.get("HF_ENDPOINT") or "https://huggingface.co"
        self.token = token if token is not None else os.environ.get("HF_TOKEN")
        self.opener: Opener = opener or (
            lambda request: urllib.request.urlopen(request, timeout=60)
        )
        self._states: dict[str, DownloadState] = {}
        self._lock = threading.Lock()

    def state(self, weights: WeightSet) -> DownloadState:
        with self._lock:
            current = self._states.get(weights.key)
        if current is not None and current.status in ("downloading", "failed", "cancelled"):
            return current
        if is_complete(weights, self.root):
            return DownloadState(weights.key, "done", weights.size_bytes, weights.size_bytes)
        return DownloadState(
            weights.key, "missing", weights.size_bytes, self._partial_bytes(weights)
        )

    def start(self, weights: WeightSet) -> DownloadState:
        with self._lock:
            current = self._states.get(weights.key)
            if current is not None and current.status == "downloading":
                return current
            if is_complete(weights, self.root):
                return DownloadState(weights.key, "done", weights.size_bytes, weights.size_bytes)
            state = DownloadState(
                weights.key,
                "downloading",
                weights.size_bytes,
                self._partial_bytes(weights),
                started_at=time.time(),
            )
            state.thread = threading.Thread(
                target=self._run, args=(weights, state), name=f"download {weights.key}", daemon=True
            )
            self._states[weights.key] = state
            state.thread.start()
            return state

    def cancel(self, weights: WeightSet) -> DownloadState:
        with self._lock:
            current = self._states.get(weights.key)
        if current is not None and current.status == "downloading":
            current.cancel.set()
            if current.thread is not None:
                current.thread.join(timeout=10)
        return self.state(weights)

    def wait(self, weights: WeightSet, timeout: float | None = None) -> DownloadState:
        with self._lock:
            current = self._states.get(weights.key)
        if current is not None and current.thread is not None:
            current.thread.join(timeout)
        return self.state(weights)

    def _partial_bytes(self, weights: WeightSet) -> int:
        partial = weights.path(self.root).with_name(weights.path(self.root).name + ".partial")
        if not partial.is_dir():
            return 0
        return sum(p.stat().st_size for p in partial.iterdir() if p.is_file())

    # Runs in the download thread.
    def _run(self, weights: WeightSet, state: DownloadState) -> None:
        final = weights.path(self.root)
        partial = final.with_name(final.name + ".partial")
        try:
            partial.mkdir(parents=True, exist_ok=True)
            done_before = 0
            for f in weights.files:
                self._fetch(weights, f, partial / f.name, state, done_before)
                done_before += f.size
                state.downloaded_bytes = done_before
            (partial / MARKER).write_text(
                json.dumps(
                    {
                        "repo_id": weights.repo_id,
                        "revision": weights.revision,
                        "files": {f.name: f.size for f in weights.files},
                    }
                ),
                encoding="utf-8",
            )
            if final.exists():
                shutil.rmtree(final)
            os.replace(partial, final)
            state.status = "done"
        except DownloadCancelled:
            shutil.rmtree(partial, ignore_errors=True)
            state.status = "cancelled"
            state.downloaded_bytes = 0
        except Exception as exc:  # network, disk, hash: reported on the admin screen
            log.warning("weights download failed for %s: %s", weights.key, exc)
            state.status = "failed"
            state.error = _describe(exc)
        finally:
            state.finished_at = time.time()

    def _fetch(
        self,
        weights: WeightSet,
        f: WeightFile,
        target: Path,
        state: DownloadState,
        done_before: int,
    ) -> None:
        digest = hashlib.sha256() if f.sha256 else None
        have = target.stat().st_size if target.exists() else 0
        if have > f.size:
            target.unlink()
            have = 0
        if have and digest is not None:
            with target.open("rb") as existing:
                for block in iter(lambda: existing.read(_CHUNK), b""):
                    digest.update(block)
        if have < f.size:
            headers = {"User-Agent": "interview-assistant"}
            if self.token:
                headers["Authorization"] = f"Bearer {self.token}"
            if have:
                headers["Range"] = f"bytes={have}-"
            request = urllib.request.Request(weights.url(f.name, self.endpoint), headers=headers)
            with self.opener(request) as response:
                if have and getattr(response, "status", 200) != 206:  # no resume: start over
                    have = 0
                    digest = hashlib.sha256() if f.sha256 else None
                with target.open("ab" if have else "wb") as out:
                    self._copy(response, out, digest, state, done_before + have)
        size = target.stat().st_size
        if size != f.size:
            raise OSError(f"{f.name}: expected {f.size} bytes, got {size}")
        if digest is not None and digest.hexdigest() != f.sha256:
            target.unlink()
            raise OSError(f"{f.name}: sha256 mismatch (the file was discarded)")

    @staticmethod
    def _copy(
        response: BinaryIO, out: BinaryIO, digest: Any, state: DownloadState, offset: int
    ) -> None:
        written = 0
        while True:
            if state.cancel.is_set():
                raise DownloadCancelled
            block = response.read(_CHUNK)
            if not block:
                return
            out.write(block)
            if digest is not None:
                digest.update(block)
            written += len(block)
            state.downloaded_bytes = offset + written


def _describe(exc: Exception) -> str:
    text = str(exc) or type(exc).__name__
    return f"{type(exc).__name__}: {text}"[:300]
